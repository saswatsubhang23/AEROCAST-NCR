"use client";

import { CameraControls } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { LOCATIONS } from "@/lib/locations";
import { IMAGERY_URL } from "@/lib/terrain/api";
import { TextSprite, meshGeometry, useTextureUrl } from "./ground";
import { TERRAIN_EXAGGERATION, drapeMesh, groundHeight, terrainMesh } from "@/lib/terrain/terrain";
import { advect, type Particle } from "@/lib/twin/fields";
import { PARTICLE_COUNT, PARTICLE_LIFE_FRAMES, SIM_SECONDS_PER_FRAME, reducedMotion } from "@/lib/twin/layers/particles";
import type { SceneData } from "@/lib/twin/scene/data";
import {
  ALTITUDE_LEVELS_KM, MAX_ALTITUDE_KM, SCENE_DEPTH_KM, SCENE_WIDTH_KM, VERTICAL_EXAGGERATION, fromScene, graticule, heightSurface, heightToScene, toScene,
} from "@/lib/twin/scene/geometry";

import { CAMERA_PRESETS, type CameraPreset } from "./cameraPresets";

const BLH_RAMP = ["#4a2c7a", "#7b3fa0", "#c2589a", "#f08a6a", "#ffd479"];

function rampColor(t: number): [number, number, number] {
  const x = Math.min(Math.max(t, 0), 1) * (BLH_RAMP.length - 1);
  const i = Math.min(Math.floor(x), BLH_RAMP.length - 2);
  const f = x - i;
  const a = new THREE.Color(BLH_RAMP[i]);
  const b = new THREE.Color(BLH_RAMP[i + 1]);
  return [a.r + (b.r - a.r) * f, a.g + (b.g - a.g) * f, a.b + (b.b - a.b) * f];
}

// ---------------------------------------------------------------------------------------------- ground
/**
 * The ground: the real terrain (SRTM-based height map) textured with a Sentinel-2 composite registered to the same latitude/longitude
 * frame, and the active data field draped on it. Without a height map the ground is flat, which the scene notes say.
 */
function Ground({ data, onPoint }: { data: SceneData; onPoint: (lat: number, lon: number) => void }) {
  const hm = data.terrain;
  const imagery = useTextureUrl(IMAGERY_URL, { anisotropy: 8 });
  const field = useTextureUrl(data.ground?.url ?? null);

  const terrainGeo = useMemo(() => (hm ? meshGeometry(terrainMesh(hm), true) : null), [hm]);
  useEffect(() => () => terrainGeo?.dispose(), [terrainGeo]);

  // The drape must be at least as finely sampled as the ground under it, or ridges poke through between its vertices.
  const drapeGeo = useMemo(() => {
    if (!data.ground) return null;
    const [w, s, e, n] = data.ground.bounds;
    const nx = hm ? Math.max(48, Math.round(((e - w) / (hm.east - hm.west)) * (hm.cols - 1)) + 1) : 48;
    const ny = hm ? Math.max(48, Math.round(((n - s) / (hm.north - hm.south)) * (hm.rows - 1)) + 1) : 48;
    return meshGeometry(drapeMesh(hm, data.ground.bounds, nx, ny, 0.25), false);
  }, [hm, data.ground]);
  useEffect(() => () => drapeGeo?.dispose(), [drapeGeo]);

  const pick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    const p = fromScene(e.point.x, e.point.z);
    onPoint(p.lat, p.lon);
  };

  return (
    <group>
      {terrainGeo ? (
        <mesh geometry={terrainGeo} onClick={pick}>
          <meshStandardMaterial map={imagery ?? undefined} color={imagery ? "#ffffff" : "#16233b"} roughness={1} metalness={0} />
        </mesh>
      ) : (
        <mesh rotation={[-Math.PI / 2, 0, 0]} onClick={pick}>
          <planeGeometry args={[SCENE_WIDTH_KM, SCENE_DEPTH_KM]} />
          <meshStandardMaterial map={imagery ?? undefined} color={imagery ? "#ffffff" : "#101a2e"} roughness={1} metalness={0} />
        </mesh>
      )}
      {drapeGeo && field && data.ground && (
        <mesh geometry={drapeGeo} renderOrder={2}>
          <meshBasicMaterial map={field} transparent opacity={data.ground.opacity} depthWrite={false} toneMapped={false} polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} />
        </mesh>
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------------------------- frame: graticule, boundary, cities, altitude axis and levels
function Frame({ showGraticule, showLevels, terrain }: { showGraticule: boolean; showLevels: boolean; terrain: SceneData["terrain"] }) {
  const grat = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(graticule(0.25, 0.15, terrain ? (la, lo) => groundHeight(terrain, la, lo) : undefined), 3));
    return g;
  }, [terrain]);
  useEffect(() => () => grat.dispose(), [grat]);
  const topY = heightToScene(MAX_ALTITUDE_KM * 1000);
  const cx = -SCENE_WIDTH_KM / 2;
  const cz = SCENE_DEPTH_KM / 2;
  const axis = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array([cx, 0, cz, cx, topY, cz]), 3));
    return g;
  }, [cx, cz, topY]);
  const levelGeo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const w = SCENE_WIDTH_KM / 2;
    const d = SCENE_DEPTH_KM / 2;
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array([-w, 0, -d, w, 0, -d, w, 0, d, -w, 0, d]), 3));
    return g;
  }, []);
  useEffect(() => () => { axis.dispose(); levelGeo.dispose(); }, [axis, levelGeo]);
  const cities = useMemo(() => LOCATIONS.flatMap((l) => { const p = toScene(l.lat, l.lon); return p ? [{ ...p, y: groundHeight(terrain, l.lat, l.lon), name: l.name }] : []; }), [terrain]);

  return (
    <group>
      {showGraticule && (
        <>
          <lineSegments geometry={grat}>
            <lineBasicMaterial color="#35527f" transparent opacity={0.5} />
          </lineSegments>
          {cities.map((c) => (
            <group key={c.name} position={[c.x, c.y + 0.2, c.z]}>
              <mesh rotation={[-Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.7, 1.1, 24]} />
                <meshBasicMaterial color="#9db0cc" />
              </mesh>
              <TextSprite text={c.name} position={[0, 2.2, 0]} scale={2.6} fontPx={26} />
            </group>
          ))}
        </>
      )}
      <line>
        <primitive object={axis} attach="geometry" />
        <lineBasicMaterial color="#e8eef8" />
      </line>
      {ALTITUDE_LEVELS_KM.map((km) => (
        <group key={km}>
          <TextSprite text={`${km} km`} position={[cx - 5, heightToScene(km * 1000), cz]} scale={2.4} fontPx={26} background={null} />
          {showLevels && (
            <lineLoop geometry={levelGeo} position={[0, heightToScene(km * 1000), 0]}>
              <lineBasicMaterial color="#9db0cc" transparent opacity={0.18} />
            </lineLoop>
          )}
        </group>
      ))}
      <TextSprite text={`atmosphere heights ×${VERTICAL_EXAGGERATION}${terrain ? ` · terrain ×${TERRAIN_EXAGGERATION}` : ""}`} position={[cx + 14, topY + 3, cz]} scale={2.6} fontPx={26} color="#ffd479" />
    </group>
  );
}

// ---------------------------------------------------------------------------------------------- station columns and rings
function Columns({ data, selectedId, onPick }: { data: SceneData; selectedId: number | string | null; onPick: (id: number | string, lat: number, lon: number) => void }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const [hover, setHover] = useState<number | null>(null);
  const cols = data.columns;
  useEffect(() => {
    const m = ref.current;
    if (!m) return;
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    cols.forEach((c, i) => {
      dummy.position.set(c.x, c.base + c.height / 2, c.z);
      dummy.scale.set(1, c.height, 1);
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
      color.setRGB(c.rgb[0] / 255, c.rgb[1] / 255, c.rgb[2] / 255, THREE.SRGBColorSpace);
      m.setColorAt(i, color);
    });
    m.count = cols.length;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }, [cols]);

  const rings = data.rings;
  const hovered = hover !== null ? cols[hover] : null;
  return (
    <group>
      <instancedMesh
        ref={ref}
        key={cols.length} // a different count needs a new buffer
        args={[undefined, undefined, Math.max(cols.length, 1)]}
        onPointerMove={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); setHover(e.instanceId ?? null); }}
        onPointerOut={() => setHover(null)}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation();
          const c = e.instanceId !== undefined ? cols[e.instanceId] : null;
          if (c) { const p = fromScene(c.x, c.z); onPick(c.id, p.lat, p.lon); }
        }}
      >
        <cylinderGeometry args={[0.9, 0.9, 1, 12]} />
        <meshStandardMaterial roughness={0.6} metalness={0.05} />
      </instancedMesh>
      {rings.map((r) => (
        <mesh key={String(r.id)} position={[r.x, r.y + 0.2, r.z]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.7, 1.1, 20]} />
          <meshBasicMaterial color="#9db0cc" />
        </mesh>
      ))}
      {cols.filter((c) => c.id === selectedId).map((c) => (
        <mesh key={`sel-${String(c.id)}`} position={[c.x, c.base + c.height + 0.8, c.z]}>
          <coneGeometry args={[0.8, 1.6, 12]} />
          <meshBasicMaterial color="#22d3ee" />
        </mesh>
      ))}
      {hovered && (
        <TextSprite lines={[hovered.name, `${hovered.value.toFixed(hovered.value >= 100 ? 0 : 1)} ${data.columnUnit}`]} position={[hovered.x, hovered.base + hovered.height + 4, hovered.z]} scale={4.4} fontPx={28} color="#e8eef8" background="rgba(20,32,54,0.92)" />
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------------------------- boundary-layer surface
function BlhSurface({ blh, terrain }: { blh: NonNullable<SceneData["blh"]>; terrain: SceneData["terrain"] }) {
  const geo = useMemo(() => {
    const s = heightSurface(blh.lats, blh.lons, blh.heights, (la, lo) => groundHeight(terrain, la, lo));
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(s.positions, 3));
    const colors = new Float32Array(s.vertexCount * 3);
    for (let i = 0; i < s.vertexCount; i++) {
      const lat = blh.lats[Math.floor(i / blh.lons.length)];
      const lon = blh.lons[i % blh.lons.length];
      const hKm = (s.positions[i * 3 + 1] - groundHeight(terrain, lat, lon)) / VERTICAL_EXAGGERATION;
      const [r, gg, b] = rampColor(hKm / 2);
      colors.set([r, gg, b], i * 3);
    }
    g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    g.setIndex(new THREE.BufferAttribute(s.indices, 1));
    g.computeVertexNormals();
    return g;
  }, [blh, terrain]);
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <mesh geometry={geo}>
      <meshStandardMaterial vertexColors transparent opacity={blh.opacity} side={THREE.DoubleSide} depthWrite={false} roughness={0.8} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------------------------- mixed-layer slab (illustrative)
function Slab({ slab }: { slab: NonNullable<SceneData["slab"]> }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const m = ref.current;
    if (!m) return;
    const dummy = new THREE.Object3D();
    const color = new THREE.Color();
    slab.cells.forEach((c, i) => {
      dummy.position.set(c.x, c.base + c.height / 2, c.z);
      dummy.scale.set(c.w * 0.98, c.height, c.d * 0.98);
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
      color.setRGB(c.rgb[0] / 255, c.rgb[1] / 255, c.rgb[2] / 255, THREE.SRGBColorSpace);
      m.setColorAt(i, color);
    });
    m.count = slab.cells.length;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }, [slab]);
  return (
    <instancedMesh ref={ref} key={slab.cells.length} args={[undefined, undefined, Math.max(slab.cells.length, 1)]}>
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial transparent opacity={slab.opacity} depthWrite={false} roughness={0.9} />
    </instancedMesh>
  );
}

// ---------------------------------------------------------------------------------------------- pressure contours, forecast marker, inspected point
function Lines({ positions, color, opacity }: { positions: Float32Array; color: string; opacity: number }) {
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return g;
  }, [positions]);
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <lineSegments geometry={geo}>
      <lineBasicMaterial color={color} transparent opacity={opacity} />
    </lineSegments>
  );
}

// ---------------------------------------------------------------------------------------------- wind particles (10 m wind, bounded budget)
function WindParticles({ wind, animate, terrain }: { wind: NonNullable<SceneData["wind"]>; animate: boolean; terrain: SceneData["terrain"] }) {
  const particles = useRef<Particle[]>([]);
  const acc = useRef(0);
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(PARTICLE_COUNT * 3), 3));
    return g;
  }, []);
  useEffect(() => () => geo.dispose(), [geo]);

  const seed = useMemo(
    () => (): Particle => {
      const { lats, lons } = wind;
      const lat = lats[0] + Math.random() * (lats[lats.length - 1] - lats[0]);
      const lon = lons[0] + Math.random() * (lons[lons.length - 1] - lons[0]);
      return { lat, lon, age: Math.floor(Math.random() * PARTICLE_LIFE_FRAMES), trail: [[lon, lat]] };
    },
    [wind],
  );

  useEffect(() => {
    particles.current = Array.from({ length: PARTICLE_COUNT }, seed);
    write();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  function write() {
    const attr = geo.getAttribute("position") as THREE.BufferAttribute;
    const y = heightToScene(10); // the data are 10 m winds: drawn 10 m above the ground, with no vertical structure implied
    particles.current.forEach((p, i) => {
      const s = toScene(p.lat, p.lon);
      attr.setXYZ(i, s ? s.x : 0, groundHeight(terrain, p.lat, p.lon) + y + 0.05, s ? s.z : 0);
    });
    attr.needsUpdate = true;
  }

  useFrame((_, delta) => {
    if (!animate) return;
    acc.current += delta;
    if (acc.current < 0.05) return;
    acc.current = 0;
    const lattice = { lats: wind.lats, lons: wind.lons };
    particles.current = particles.current.map((p) => (p.age >= PARTICLE_LIFE_FRAMES ? null : advect(p, wind.u, wind.v, lattice, SIM_SECONDS_PER_FRAME)) ?? seed());
    write();
  });

  return (
    <points geometry={geo} frustumCulled={false}>
      <pointsMaterial color="#e8fbf4" size={0.6} sizeAttenuation transparent opacity={0.85 * wind.opacity} depthWrite={false} />
    </points>
  );
}

// ---------------------------------------------------------------------------------------------- camera
function CameraRig({ preset, token }: { preset: CameraPreset; token: number }) {
  const ref = useRef<CameraControls>(null);
  const aspect = useThree((s) => s.size.width / Math.max(s.size.height, 1));
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const p = CAMERA_PRESETS[preset];
    // On a narrow canvas the horizontal field of view is small, so the camera backs away until the whole domain fits.
    const k = Math.max(1, 1.25 / aspect);
    const pos: [number, number, number] = [
      p.target[0] + (p.position[0] - p.target[0]) * k,
      p.target[1] + (p.position[1] - p.target[1]) * k,
      p.target[2] + (p.position[2] - p.target[2]) * k,
    ];
    // smooth transition unless the user prefers reduced motion
    void c.setLookAt(...pos, ...p.target, !reducedMotion());
  }, [preset, token, aspect]);
  return <CameraControls ref={ref} minDistance={15} maxDistance={320} maxPolarAngle={Math.PI / 2 - 0.03} smoothTime={0.35} draggingSmoothTime={0.12} />;
}

// ---------------------------------------------------------------------------------------------- scene
export default function Scene3D({
  data,
  selected,
  preset,
  presetToken,
  onPickStation,
  onPickPoint,
  badge,
  timeLabel,
  ariaLabel,
  presets,
  notes,
}: {
  data: SceneData;
  selected: { lat: number; lon: number; stationId: number | string | null } | null;
  preset: CameraPreset;
  presetToken: number;
  onPickStation: (id: number | string, lat: number, lon: number) => void;
  onPickPoint: (lat: number, lon: number) => void;
  badge: ReactNode;
  timeLabel: string;
  ariaLabel: string;
  presets: ReactNode;
  notes: ReactNode;
}) {
  const [lost, setLost] = useState(false);
  const animate = !!data.wind && !reducedMotion();
  const sel = selected ? toScene(selected.lat, selected.lon) : null;
  const showGraticule = data.active.includes("scene-graticule");
  const showLevels = data.active.includes("altitude-levels");

  return (
    <div>
      <div className="relative overflow-hidden rounded-lg border border-line bg-[#0a1120]" style={{ height: 480 }}>
        <Canvas
          role="img"
          aria-label={ariaLabel}
          dpr={[1, 2]}
          frameloop={animate ? "always" : "demand"}
          camera={{ position: CAMERA_PRESETS.oblique.position, fov: 38, near: 0.5, far: 1200 }}
          gl={{ antialias: true, powerPreference: "high-performance" }}
          onCreated={({ gl }) => {
            gl.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); setLost(true); });
            // opt-in diagnostic for resource checks: open the page with ?debug3d to expose the renderer's memory counters
            if (new URLSearchParams(window.location.search).has("debug3d")) (window as unknown as { __twin3d?: unknown }).__twin3d = { info: gl.info };
          }}
        >
          <color attach="background" args={["#0a1120"]} />
          <fog attach="fog" args={["#0a1120", 170, 520]} />
          <ambientLight intensity={0.85} />
          <directionalLight position={[70, 130, 50]} intensity={1.15} />
          <CameraRig preset={preset} token={presetToken} />
          <Ground data={data} onPoint={onPickPoint} />
          <Frame showGraticule={showGraticule} showLevels={showLevels} terrain={data.terrain} />
          <Columns data={data} selectedId={selected?.stationId ?? null} onPick={onPickStation} />
          {data.blh && <BlhSurface blh={data.blh} terrain={data.terrain} />}
          {data.slab && <Slab slab={data.slab} />}
          {data.pressureLines && data.pressureLines.length > 0 && <Lines positions={data.pressureLines} color="#e8eef8" opacity={0.85} />}
          {data.wind && <WindParticles wind={data.wind} animate={animate} terrain={data.terrain} />}
          {sel && !selected?.stationId && (
            <mesh position={[sel.x, groundHeight(data.terrain, selected!.lat, selected!.lon) + 0.3, sel.z]} rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[1.2, 1.7, 28]} />
              <meshBasicMaterial color="#ffd23f" />
            </mesh>
          )}
          {data.forecast && (
            <mesh position={[data.forecast.x, data.forecast.y + 1, data.forecast.z]} rotation={[-Math.PI / 2, 0, 0]}>
              <torusGeometry args={[1.8, 0.28, 10, 32]} />
              <meshBasicMaterial color="#ffd23f" />
            </mesh>
          )}
        </Canvas>
        <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-2 rounded bg-surface/90 px-2 py-1 text-xs">
          {badge}
          <span className="text-muted">{timeLabel}</span>
        </div>
        <div className="absolute bottom-2 left-2 right-2 rounded bg-surface/90 p-1">{presets}</div>
        {lost && <p className="absolute inset-x-2 bottom-2 rounded bg-surface-2 px-2 py-1 text-xs text-warn">The 3D context was lost by the browser. Reload the page to restore it; the map view is unaffected.</p>}
      </div>
      <div className="mt-3 space-y-2">{notes}</div>
    </div>
  );
}

