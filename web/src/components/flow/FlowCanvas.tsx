"use client";

import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import {
  DEFAULT_PARTICLE_OPTIONS, colourAtSpeed, colourAtValue, createParticles, fieldBounds, sampleVector, seededRng, stepParticles, type ParticleSet, type Scale, type VectorField,
} from "@/lib/flow/field";
import { sampleBilinear, type Grid2D } from "@/lib/twin/fields";

export type FlowRender = {
  field: VectorField | null;
  /** The concentration the particles are coloured by (pollutant mode). `null` colours by wind speed. */
  scalar: { grid: Grid2D; lats: number[]; lons: number[]; scale: Scale } | null;
  colourBy: "pollutant" | "wind";
  count: number;
  /** Simulated seconds of drift per animation frame. */
  secondsPerFrame: number;
  opacity: number;
  paused: boolean;
  /** True on a light basemap (Voyager): streaks get a white halo and a dark neutral colour so they never vanish into the map. */
  lightBase?: boolean;
};

const LUT_STEPS = 40;
const UNKNOWN_LIGHT_ON_DARK = "rgb(205,214,228)";
const UNKNOWN_DARK_ON_LIGHT = "rgb(62,76,99)";
const FADE = 0.045;
const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function rgb(c: [number, number, number]): string {
  return `rgb(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])})`;
}

/**
 * Animated air over a MapLibre map: particles carried by the weather-model wind, each coloured by the concentration of air at its
 * position (or by wind speed). One 2-D canvas, bounded particle count, trails by fading the previous frame. Everything that is drawn is
 * the field it is given: no particle exists outside the lattice and none is drawn where the wind is unknown. Cleans up on unmount.
 */
export function FlowCanvas({ map, render }: { map: MapLibreMap | null; render: FlowRender }) {
  const ref = useRef(render);
  useEffect(() => {
    ref.current = render;
  });

  useEffect(() => {
    if (!map) return;
    const container = map.getCanvasContainer();
    const canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;";
    container.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      canvas.remove();
      return;
    }
    const rng = seededRng(20261011);
    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    let particles: ParticleSet | null = null;
    let sig = "";
    let raf = 0;
    let last = 0;
    let clearNext = true;

    const resize = () => {
      const w = map.getCanvas().clientWidth;
      const h = map.getCanvas().clientHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      clearNext = true;
    };
    resize();
    const clear = () => {
      clearNext = true;
    };
    map.on("resize", resize);
    map.on("movestart", clear);
    map.on("zoomstart", clear);
    map.on("move", clear);

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (now - last < 33) return; // about 30 frames per second
      last = now;
      const r = ref.current;
      const w = canvas.width;
      const h = canvas.height;
      if (clearNext) {
        ctx.clearRect(0, 0, w, h);
        clearNext = false;
      }
      if (!r.field || r.opacity <= 0) {
        ctx.clearRect(0, 0, w, h);
        return;
      }
      const b = fieldBounds(r.field);
      const nextSig = `${r.count}|${b.south}|${b.north}|${b.west}|${b.east}`;
      if (!particles || nextSig !== sig) {
        particles = createParticles(r.count, r.field, rng, DEFAULT_PARTICLE_OPTIONS);
        sig = nextSig;
        ctx.clearRect(0, 0, w, h);
      }
      if (reduced()) {
        drawStatic(ctx, map, r, dpr);
        return;
      }
      if (!r.paused) stepParticles(particles, r.field, r.secondsPerFrame, rng, DEFAULT_PARTICLE_OPTIONS);

      // fade what is already there, then draw this frame's segments in colour buckets (one path per colour)
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = `rgba(0,0,0,${FADE})`;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = Math.min(Math.max(r.opacity, 0), 1);
      ctx.lineWidth = 1.7 * dpr;
      ctx.lineCap = "round";

      const usePoll = r.colourBy === "pollutant" && r.scalar !== null;
      const unknown = r.lightBase ? UNKNOWN_DARK_ON_LIGHT : UNKNOWN_LIGHT_ON_DARK;
      const lut: string[] = [];
      let maxV = 1;
      if (usePoll && r.scalar) {
        const bins = r.scalar.scale.bins;
        maxV = bins[bins.length - 1].lo * 1.35;
        for (let i = 0; i <= LUT_STEPS; i++) {
          const c = colourAtValue(r.scalar.scale, (i / LUT_STEPS) * maxV);
          lut.push(c ? rgb(c) : unknown);
        }
      } else {
        for (let i = 0; i <= LUT_STEPS; i++) lut.push(rgb(colourAtSpeed((i / LUT_STEPS) * 16)));
      }
      const lattice = r.scalar ? { lats: r.scalar.lats, lons: r.scalar.lons } : null;
      const buckets: number[][] = Array.from({ length: LUT_STEPS + 2 }, () => []);
      const p = particles;
      for (let i = 0; i < p.count; i++) {
        if (!p.moved[i]) continue;
        let idx: number;
        if (usePoll && r.scalar && lattice) {
          const v = sampleBilinear(r.scalar.grid, lattice, p.lat[i], p.lon[i]);
          idx = v === null ? LUT_STEPS + 1 : Math.min(LUT_STEPS, Math.max(0, Math.round((v / maxV) * LUT_STEPS)));
        } else {
          idx = Math.min(LUT_STEPS, Math.round((p.speed[i] / 16) * LUT_STEPS));
        }
        const a = map.project([p.prevLon[i], p.prevLat[i]]);
        const c = map.project([p.lon[i], p.lat[i]]);
        buckets[idx].push(a.x * dpr, a.y * dpr, c.x * dpr, c.y * dpr);
      }
      // a halo under every coloured streak keeps it readable over a concentration field of the same colours; air whose concentration is
      // unknown is drawn faintly and without a halo, so it shows the wind without pretending to show a value
      ctx.strokeStyle = r.lightBase ? "rgba(255,255,255,0.55)" : "rgba(4,9,20,0.5)";
      ctx.lineWidth = 3.0 * dpr;
      ctx.beginPath();
      for (let k = 0; k < LUT_STEPS + 1; k++) {
        const seg = buckets[k];
        for (let s = 0; s < seg.length; s += 4) {
          ctx.moveTo(seg[s], seg[s + 1]);
          ctx.lineTo(seg[s + 2], seg[s + 3]);
        }
      }
      ctx.stroke();
      ctx.lineWidth = 1.6 * dpr;
      for (let k = 0; k < buckets.length; k++) {
        const seg = buckets[k];
        if (seg.length === 0) continue;
        const isUnknown = k === LUT_STEPS + 1;
        ctx.globalAlpha = Math.min(Math.max(r.opacity, 0), 1) * (isUnknown ? 0.38 : 1);
        ctx.strokeStyle = isUnknown ? unknown : lut[k];
        ctx.beginPath();
        for (let s = 0; s < seg.length; s += 4) {
          ctx.moveTo(seg[s], seg[s + 1]);
          ctx.lineTo(seg[s + 2], seg[s + 3]);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      map.off("resize", resize);
      map.off("movestart", clear);
      map.off("zoomstart", clear);
      map.off("move", clear);
      canvas.remove();
    };
  }, [map]);

  return null;
}

/** For people who prefer reduced motion: a still picture of the flow (short streamlines from a fixed set of seeds), redrawn only when the field changes. */
function drawStatic(ctx: CanvasRenderingContext2D, map: MapLibreMap, r: FlowRender, dpr: number) {
  const f = r.field;
  if (!f) return;
  const w = ctx.canvas.width;
  const h = ctx.canvas.height;
  ctx.clearRect(0, 0, w, h);
  const b = fieldBounds(f);
  const rng = seededRng(5);
  ctx.lineWidth = 1.4 * dpr;
  ctx.globalAlpha = Math.min(Math.max(r.opacity, 0), 1);
  const usePoll = r.colourBy === "pollutant" && r.scalar !== null;
  const lattice = r.scalar ? { lats: r.scalar.lats, lons: r.scalar.lons } : null;
  for (let s = 0; s < 500; s++) {
    let lat = b.south + rng() * (b.north - b.south);
    let lon = b.west + rng() * (b.east - b.west);
    const v0 = usePoll && r.scalar && lattice ? sampleBilinear(r.scalar.grid, lattice, lat, lon) : null;
    const wind0 = sampleVector(f, lat, lon);
    const col = usePoll && r.scalar ? colourAtValue(r.scalar.scale, v0) : wind0 ? colourAtSpeed(Math.hypot(wind0.u, wind0.v)) : null;
    ctx.strokeStyle = col ? rgb(col) : r.lightBase ? UNKNOWN_DARK_ON_LIGHT : UNKNOWN_LIGHT_ON_DARK;
    ctx.beginPath();
    const p0 = map.project([lon, lat]);
    ctx.moveTo(p0.x * dpr, p0.y * dpr);
    for (let k = 0; k < 14; k++) {
      const wv = sampleVector(f, lat, lon);
      if (!wv) break;
      const cos = Math.max(0.2, Math.cos((lat * Math.PI) / 180));
      lat += (wv.v * 1800) / 111_320;
      lon += (wv.u * 1800) / (111_320 * cos);
      const q = map.project([lon, lat]);
      ctx.lineTo(q.x * dpr, q.y * dpr);
    }
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}
