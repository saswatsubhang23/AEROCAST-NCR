"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { TOOLTIP_STYLE, useBaseMap } from "@/components/map/useBaseMap";
import { advect, type Particle } from "@/lib/twin/fields";
import type { WindField } from "@/lib/twin/layers/types";
import { PARTICLE_COUNT, PARTICLE_FRAME_MS, PARTICLE_LIFE_FRAMES, SIM_SECONDS_PER_FRAME, particleLayer, reducedMotion } from "@/lib/twin/layers/particles";

type OverlayRef = ReturnType<typeof useBaseMap>["overlay"];

/** Pushes the static layers plus the current particle trails to the one deck.gl overlay of the map. */
function applyLayers(overlay: OverlayRef, base: { current: unknown[] }, particles: { current: Particle[] }, opacity: number) {
  if (!overlay.current) return;
  overlay.current.setProps({ layers: [...base.current, ...(particles.current.length ? [particleLayer(particles.current, opacity)] : [])] as never });
}

/**
 * The twin's one map. It draws whatever layer list the registry built for the current state and animates the wind particles it is given;
 * it knows nothing about stations, estimates or simulations. Creating and tearing down MapLibre, the deck.gl overlay and the animation
 * loop is done here and only here.
 */
export default function TwinMap({
  layers,
  wind,
  badge,
  timeLabel,
  ariaLabel,
  resetToken,
  onMapClick,
  onPickStation,
  tooltipFor,
  footer,
}: {
  layers: unknown[];
  wind: WindField | null;
  badge: ReactNode;
  timeLabel: string;
  ariaLabel: string;
  resetToken: number;
  onMapClick?: (p: { lat: number; lon: number }) => void;
  onPickStation?: (id: number) => void;
  tooltipFor?: (object: unknown) => string | null;
  footer?: ReactNode;
}) {
  const { container, overlay, basemapFailed, basemap, resetView } = useBaseMap();
  const base = useRef<unknown[]>([]);
  const particles = useRef<Particle[]>([]);
  const opacity = useRef(0.9);
  const handlers = useRef({ onMapClick, onPickStation, tooltipFor });
  useEffect(() => {
    handlers.current = { onMapClick, onPickStation, tooltipFor };
  });

  useEffect(() => {
    if (resetToken > 0) resetView();
  }, [resetToken, resetView]);

  // Click and tooltip handlers are installed once; they read the latest callbacks from a ref.
  useEffect(() => {
    if (!overlay.current) return;
    overlay.current.setProps({
      getTooltip: ({ object }: { object?: unknown }) => {
        const html = object ? handlers.current.tooltipFor?.(object) : null;
        return html ? { html, style: TOOLTIP_STYLE } : null;
      },
      onClick: ({ object, coordinate }: { object?: { station_id?: number } | null; coordinate?: number[] }) => {
        if (object && typeof object.station_id === "number") handlers.current.onPickStation?.(object.station_id);
        else if (coordinate) handlers.current.onMapClick?.({ lon: coordinate[0], lat: coordinate[1] });
      },
    });
  }, [overlay]);

  useEffect(() => {
    base.current = layers;
    applyLayers(overlay, base, particles, opacity.current);
  }, [layers, overlay]);

  // Wind particles: advected through the given field. The loop is cancelled whenever its inputs change or the map unmounts, it is bounded
  // (fixed particle count and lifetime), and it is not started when the user prefers reduced motion.
  useEffect(() => {
    particles.current = [];
    if (!wind || reducedMotion()) {
      applyLayers(overlay, base, particles, opacity.current);
      return;
    }
    opacity.current = wind.opacity;
    const { lats, lons } = wind;
    const lattice = { lats, lons };
    const seed = (): Particle => {
      const lat = lats[0] + Math.random() * (lats[lats.length - 1] - lats[0]);
      const lon = lons[0] + Math.random() * (lons[lons.length - 1] - lons[0]);
      return { lat, lon, age: Math.floor(Math.random() * PARTICLE_LIFE_FRAMES), trail: [[lon, lat]] };
    };
    particles.current = Array.from({ length: PARTICLE_COUNT }, seed);
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (now - last < PARTICLE_FRAME_MS) return;
      last = now;
      particles.current = particles.current.map((p) => {
        const next = p.age >= PARTICLE_LIFE_FRAMES ? null : advect(p, wind.u, wind.v, lattice, SIM_SECONDS_PER_FRAME);
        return next ?? seed();
      });
      applyLayers(overlay, base, particles, wind.opacity);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [wind, overlay]);

  return (
    <div>
      <div className="relative overflow-hidden rounded-lg border border-line">
        <div ref={container} className="h-[380px] w-full sm:h-[480px]" role="application" aria-label={ariaLabel} />
        <div className="absolute left-2 top-2 flex items-center gap-2 rounded bg-surface/90 px-2 py-1 text-xs">
          {badge}
          <span className="text-muted">{timeLabel}</span>
        </div>
        {basemapFailed && <p className="absolute bottom-2 left-2 rounded bg-surface-2 px-2 py-1 text-xs text-muted">Basemap tiles could not be loaded; data layers are still shown.</p>}
        {!basemapFailed && basemap === "satellite" && (
          <p className="pointer-events-none absolute bottom-6 left-2 max-w-[70%] rounded bg-surface/90 px-2 py-1 text-[11px] text-muted">
            Satellite: Sentinel-2 cloudless composite, 2020. A reference image, not today&apos;s view; coloured fields are model output.
          </p>
        )}
      </div>
      {footer && <div className="mt-3 space-y-2">{footer}</div>}
    </div>
  );
}
