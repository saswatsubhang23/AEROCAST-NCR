"use client";

import { CameraControls } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { colourAtValue, colourAtSpeed, seededRng, type Scale } from "@/lib/flow/field";
import { windAtHeight, type LevelStack } from "@/lib/flow/levels";
import { IMAGERY_URL } from "@/lib/terrain/api";
import { drapeMesh, groundHeight, terrainMesh, type Heightmap } from "@/lib/terrain/terrain";
import { sampleBilinear, type Grid2D } from "@/lib/twin/fields";
import { latticeBounds, rasterDataUrl } from "@/lib/twin/layers/raster";
import { DOMAIN, SCENE_DEPTH_KM, SCENE_WIDTH_KM, VERTICAL_EXAGGERATION, fromScene, heightToScene, toScene } from "@/lib/twin/scene/geometry";
import { CAMERA_PRESETS, type CameraPreset } from "@/components/twin/scene3d/cameraPresets";
import { meshGeometry, useTextureUrl } from "@/components/twin/scene3d/ground";

export type Flow3DProps = {
  terrain: Heightmap | null;
  stack: LevelStack | null;
  scalar: { grid: Grid2D; lats: number[]; lons: number[]; scale: Scale } | null;
  /** Mixed-layer depth (m above ground) at a point, from the weather model; null where unknown. */
  blhAt: (lat: number, lon: number) => number | null;
  blhMean: number | null;
  colourBy: "pollutant" | "wind";
  count: number;
  paused: boolean;
  concentrationOpacity: number;
  preset: CameraPreset;
  presetToken: number;
  onPick: (lat: number, lon: number) => void;
};

const TRAIL = 8; // positions kept per particle
const MAX_H = 3200; // m above ground: the highest model level used
const STEP_SECONDS = 420; // simulated drift per step
const STEP_MS = 40;

// ---------------------------------------------------------------------------------------------- ground
function Ground({ terrain, scalar, opacity, onPick }: { terrain: Heightmap | null; scalar: Flow3DProps["scalar"]; opacity: number; onPick: Flow3DProps["onPick"] }) {
  const imagery = useTextureUrl(IMAGERY_URL, { anisotropy: 8 });
  const fieldUrl = useMemo(() => (scalar && opacity > 0 ? rasterDataUrl(scalar.grid, { lats: scalar.lats, lons: scalar.lons }, scalar.scale.bins, 512, { kind: "ramp" }) : null), [scalar, opacity]);
  const field = useTextureUrl(fieldUrl);
  const bounds = useMemo(() => (scalar ? latticeBounds({ lats: scalar.lats, lons: scalar.lons }) : null), [scalar]);

  const groundGeo = useMemo(() => (terrain ? meshGeometry(terrainMesh(terrain), true) : null), [terrain]);
  useEffect(() => () => groundGeo?.dispose(), [groundGeo]);
  const drapeGeo = useMemo(() => {
    if (!bounds) return null;
    const [w, s, e, n] = bounds;
    const nx = terrain ? Math.max(48, Math.round(((e - w) / (terrain.east - terrain.west)) * (terrain.cols - 1)) + 1) : 48;
    const ny = terrain ? Math.max(48, Math.round(((n - s) / (terrain.north - terrain.south)) * (terrain.rows - 1)) + 1) : 48;
    return meshGeometry(drapeMesh(terrain, bounds, nx, ny, 0.25), false);
  }, [terrain, bounds]);
  useEffect(() => () => drapeGeo?.dispose(), [drapeGeo]);

  const pick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    const p = fromScene(e.point.x, e.point.z);
    onPick(p.lat, p.lon);
  };
  return (
    <group>
      {groundGeo ? (
        <mesh geometry={groundGeo} onClick={pick}>
          <meshStandardMaterial map={imagery ?? undefined} color={imagery ? "#ffffff" : "#16233b"} roughness={1} metalness={0} />
        </mesh>
      ) : (
        <mesh rotation={[-Math.PI / 2, 0, 0]} onClick={pick}>
          <planeGeometry args={[SCENE_WIDTH_KM, SCENE_DEPTH_KM]} />
          <meshStandardMaterial map={imagery ?? undefined} color={imagery ? "#ffffff" : "#101a2e"} roughness={1} />
        </mesh>
      )}
      {drapeGeo && field && (
        <mesh geometry={drapeGeo} renderOrder={2}>
          <meshBasicMaterial map={field} transparent opacity={opacity} depthWrite={false} toneMapped={false} polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} />
        </mesh>
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------------------------- air: particles with trails at real model heights
function Air({ terrain, stack, scalar, blhAt, colourBy, count, paused }: Pick<Flow3DProps, "terrain" | "stack" | "scalar" | "blhAt" | "colourBy" | "count" | "paused">) {
  const rng = useMemo(() => seededRng(777), []);
  const sim = useRef<{ lon: Float32Array; lat: Float32Array; h: Float32Array; age: Uint16Array; life: Uint16Array; trail: Float32Array; col: Float32Array } | null>(null);
  const acc = useRef(0);
  const props = useRef({ terrain, stack, scalar, blhAt, colourBy, paused });
  useEffect(() => {
    props.current = { terrain, stack, scalar, blhAt, colourBy, paused };
  });

  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const n = count * (TRAIL - 1) * 2;
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    return g;
  }, [count]);
  useEffect(() => () => geo.dispose(), [geo]);

  const bounds = useMemo(() => {
    if (stack) {
      const f = stack.fields[0];
      return { south: f.lats[0], north: f.lats[f.lats.length - 1], west: f.lons[0], east: f.lons[f.lons.length - 1] };
    }
    return { south: DOMAIN.south, north: DOMAIN.north, west: DOMAIN.west, east: DOMAIN.east };
  }, [stack]);

  const seed = (i: number, s: NonNullable<typeof sim.current>) => {
    s.lat[i] = bounds.south + rng() * (bounds.north - bounds.south);
    s.lon[i] = bounds.west + rng() * (bounds.east - bounds.west);
    // Most particles are seeded inside the model's mixed layer (at least the lowest 150 m), where a concentration applies; the rest are spread up to
    // about 3 km so the real vertical wind structure is visible too. The height of a particle never changes: there is no vertical wind in this flow.
    const top = Math.min(Math.max(props.current.blhAt(s.lat[i], s.lon[i]) ?? 150, 150), 2500);
    s.h[i] = rng() < 0.62 ? 10 + (top - 10) * rng() : top + (MAX_H - top) * Math.pow(rng(), 1.4);
    s.age[i] = 0;
    s.life[i] = 60 + Math.round(rng() * 90);
    const p = toScene(s.lat[i], s.lon[i]);
    const y = groundHeight(props.current.terrain, s.lat[i], s.lon[i]) + heightToScene(s.h[i]);
    for (let k = 0; k < TRAIL; k++) s.trail.set([p?.x ?? 0, y, p?.z ?? 0], (i * TRAIL + k) * 3);
  };

  useEffect(() => {
    const s = {
      lon: new Float32Array(count), lat: new Float32Array(count), h: new Float32Array(count), age: new Uint16Array(count), life: new Uint16Array(count),
      trail: new Float32Array(count * TRAIL * 3), col: new Float32Array(count * 3),
    };
    sim.current = s;
    for (let i = 0; i < count; i++) {
      seed(i, s);
      s.age[i] = Math.floor(rng() * s.life[i]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count, bounds]);

  function step() {
    const s = sim.current;
    const p = props.current;
    if (!s || !p.stack) return;
    const pos = geo.getAttribute("position") as THREE.BufferAttribute;
    const col = geo.getAttribute("color") as THREE.BufferAttribute;
    const mixedTop = (lat: number, lon: number) => p.blhAt(lat, lon);
    for (let i = 0; i < count; i++) {
      if (!p.paused) {
        if (s.age[i] >= s.life[i]) seed(i, s);
        const w = windAtHeight(p.stack, s.lat[i], s.lon[i], s.h[i]);
        if (!w) {
          seed(i, s);
        } else {
          const cos = Math.max(0.2, Math.cos((s.lat[i] * Math.PI) / 180));
          s.lat[i] += (w.v * STEP_SECONDS) / 111_320;
          s.lon[i] += (w.u * STEP_SECONDS) / (111_320 * cos);
          s.age[i]++;
          const q = toScene(s.lat[i], s.lon[i]);
          const y = groundHeight(p.terrain, s.lat[i], s.lon[i]) + heightToScene(s.h[i]);
          // shift the trail and add the new head
          const base = i * TRAIL * 3;
          s.trail.copyWithin(base, base + 3, base + TRAIL * 3);
          s.trail.set([q?.x ?? 0, y, q?.z ?? 0], base + (TRAIL - 1) * 3);
          // colour: inside the mixed layer the concentration at the surface below (an assumption, stated in the scene), above it a neutral cool grey
          let c: [number, number, number];
          const top = mixedTop(s.lat[i], s.lon[i]);
          if (p.colourBy === "wind") c = colourAtSpeed(Math.hypot(w.u, w.v));
          else if (p.scalar && top !== null && s.h[i] <= top) {
            const v = sampleBilinear(p.scalar.grid, { lats: p.scalar.lats, lons: p.scalar.lons }, s.lat[i], s.lon[i]);
            const cc = colourAtValue(p.scalar.scale, v);
            c = cc ?? [150, 160, 180];
          } else c = [92, 112, 150];
          // additive blending sums overlapping streaks, so each is dimmed (air above the mixed layer more so) to keep colours readable
          const gain = p.colourBy === "wind" ? 0.62 : p.scalar && top !== null && s.h[i] <= top ? 0.7 : 0.42;
          s.col.set([(c[0] / 255) * gain, (c[1] / 255) * gain, (c[2] / 255) * gain], i * 3);
        }
      }
      // write this particle's trail as TRAIL-1 segments, fading toward the tail
      for (let k = 0; k < TRAIL - 1; k++) {
        const v = (i * (TRAIL - 1) + k) * 2;
        const a = (i * TRAIL + k) * 3;
        const b = a + 3;
        pos.setXYZ(v, s.trail[a], s.trail[a + 1], s.trail[a + 2]);
        pos.setXYZ(v + 1, s.trail[b], s.trail[b + 1], s.trail[b + 2]);
        const f0 = k / (TRAIL - 1);
        const f1 = (k + 1) / (TRAIL - 1);
        col.setXYZ(v, s.col[i * 3] * f0, s.col[i * 3 + 1] * f0, s.col[i * 3 + 2] * f0);
        col.setXYZ(v + 1, s.col[i * 3] * f1, s.col[i * 3 + 1] * f1, s.col[i * 3 + 2] * f1);
      }
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
  }

  useFrame((_, delta) => {
    acc.current += delta * 1000;
    if (acc.current < STEP_MS) return;
    acc.current = 0;
    step();
  });

  return (
    <lineSegments geometry={geo} frustumCulled={false}>
      <lineBasicMaterial vertexColors transparent opacity={0.95} blending={THREE.AdditiveBlending} depthWrite={false} />
    </lineSegments>
  );
}

// ---------------------------------------------------------------------------------------------- the mixed layer's top (model, area mean) and the altitude axis
function MixedLayerTop({ terrainMax, blhMean }: { terrainMax: number; blhMean: number | null }) {
  if (blhMean === null) return null;
  const y = terrainMax + heightToScene(blhMean);
  return (
    <mesh position={[0, y, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[SCENE_WIDTH_KM, SCENE_DEPTH_KM]} />
      <meshBasicMaterial color="#c2589a" transparent opacity={0.07} depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  );
}

function AltitudeAxis({ base }: { base: number }) {
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const x = -SCENE_WIDTH_KM / 2;
    const z = SCENE_DEPTH_KM / 2;
    const pts: number[] = [x, base, z, x, base + heightToScene(3000), z];
    for (const km of [0.5, 1, 2, 3]) {
      const y = base + heightToScene(km * 1000);
      pts.push(x, y, z, x + 3, y, z);
    }
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pts), 3));
    return g;
  }, [base]);
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <lineSegments geometry={geo}>
      <lineBasicMaterial color="#e8eef8" />
    </lineSegments>
  );
}

function CameraRig({ preset, token }: { preset: CameraPreset; token: number }) {
  const ref = useRef<CameraControls>(null);
  const aspect = useThree((s) => s.size.width / Math.max(s.size.height, 1));
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const p = CAMERA_PRESETS[preset];
    const k = Math.max(1, 1.25 / aspect);
    const pos: [number, number, number] = [p.target[0] + (p.position[0] - p.target[0]) * k, p.target[1] + (p.position[1] - p.target[1]) * k, p.target[2] + (p.position[2] - p.target[2]) * k];
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    void c.setLookAt(...pos, ...p.target, !reduce);
  }, [preset, token, aspect]);
  return <CameraControls ref={ref} minDistance={15} maxDistance={340} maxPolarAngle={Math.PI / 2 - 0.03} smoothTime={0.35} draggingSmoothTime={0.12} />;
}

export default function AirFlow3D(p: Flow3DProps) {
  const [lost, setLost] = useState(false);
  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-[#0a1120]" style={{ height: "min(72vh, 640px)", minHeight: 380 }}>
      <Canvas
        role="img" aria-label="3D view of Delhi-NCR terrain with air flowing at several heights, coloured by concentration inside the mixed layer"
        dpr={[1, 2]} camera={{ position: CAMERA_PRESETS.oblique.position, fov: 38, near: 0.5, far: 1400 }} gl={{ antialias: true, powerPreference: "high-performance" }}
        onCreated={({ gl }) => gl.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); setLost(true); })}
      >
        <color attach="background" args={["#0a1120"]} />
        <fog attach="fog" args={["#0a1120", 190, 620]} />
        <ambientLight intensity={0.85} />
        <directionalLight position={[70, 130, 50]} intensity={1.15} />
        <CameraRig preset={p.preset} token={p.presetToken} />
        <Ground terrain={p.terrain} scalar={p.scalar} opacity={p.concentrationOpacity} onPick={p.onPick} />
        <MixedLayerTop terrainMax={0} blhMean={p.blhMean} />
        <AltitudeAxis base={0} />
        <Air terrain={p.terrain} stack={p.stack} scalar={p.scalar} blhAt={p.blhAt} colourBy={p.colourBy} count={p.count} paused={p.paused} />
      </Canvas>
      <div className="pointer-events-none absolute right-3 top-3 max-w-[16rem] rounded-md bg-[#0a1120cc] px-2 py-1.5 text-[11px] leading-snug text-muted">
        {p.stack?.surfaceOnly ? "Only the 10 m wind is available for this hour, so every height uses it." : `Flow at ${p.stack?.heights.length ?? 0} model heights, 10 m to ${Math.round((p.stack?.heights[(p.stack?.heights.length ?? 1) - 1] ?? 0) / 100) / 10} km.`}
        {" "}Heights ×{VERTICAL_EXAGGERATION}, terrain ×30. Concentration colours apply inside the mixed layer (an assumption, not a measurement); above it the air is grey.
      </div>
      {lost && <p className="absolute inset-x-2 bottom-2 rounded bg-surface-2 px-2 py-1 text-xs text-warn">The 3D context was lost by the browser. Reload the page to restore it; the map view is unaffected.</p>}
    </div>
  );
}
