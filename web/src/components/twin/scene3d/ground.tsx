"use client";

import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";

/** Loads an image as a texture and disposes the GPU copy when the url changes or the scene unmounts. `null` while loading or on failure. */
export function useTextureUrl(url: string | null, opts: { anisotropy?: number } = {}): THREE.Texture | null {
  const [loaded, setLoaded] = useState<{ url: string; tex: THREE.Texture } | null>(null);
  const anisotropy = opts.anisotropy ?? 4;
  useEffect(() => {
    if (!url) return;
    let live = true;
    let tex: THREE.Texture | null = null;
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");
    loader.load(
      url,
      (t) => {
        if (!live) {
          t.dispose();
          return;
        }
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = anisotropy;
        tex = t;
        setLoaded({ url, tex: t });
      },
      undefined,
      () => undefined, // a texture that cannot load is simply absent; the ground is then drawn in plain colour
    );
    return () => {
      live = false;
      tex?.dispose();
    };
  }, [url, anisotropy]);
  return loaded && loaded.url === url ? loaded.tex : null;
}

export function meshGeometry(m: { positions: Float32Array; uvs: Float32Array; indices: Uint32Array }, normals: boolean): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(m.positions, 3));
  g.setAttribute("uv", new THREE.BufferAttribute(m.uvs, 2));
  g.setIndex(new THREE.BufferAttribute(m.indices, 1));
  if (normals) g.computeVertexNormals();
  return g;
}


/**
 * A text label drawn into a canvas texture and shown as a sprite. It replaces drei's <Html>, which mounts a separate React root for every
 * label and unmounts it synchronously during React 19's commit phase; under StrictMode that produced "removeChild" and "createRoot" errors
 * on every mount of the 3D view. A sprite lives entirely inside WebGL, so there is no DOM node to get out of step.
 */
export function TextSprite({
  text, position, scale = 6, color = "#c8d4e8", background = "rgba(10,17,32,0.8)", fontPx = 28, lines,
}: { text?: string; position: [number, number, number]; scale?: number; color?: string; background?: string | null; fontPx?: number; lines?: string[] }) {
  const content = lines ?? (text ? [text] : []);
  const key = content.join("|") + color + (background ?? "") + fontPx;
  const made = useMemo(() => {
    if (typeof document === "undefined" || content.length === 0) return null;
    const pad = 10;
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d");
    if (!ctx) return null;
    ctx.font = `600 ${fontPx}px system-ui, sans-serif`;
    const w = Math.ceil(Math.max(...content.map((l) => ctx.measureText(l).width))) + pad * 2;
    const h = content.length * (fontPx + 6) + pad * 2;
    c.width = w;
    c.height = h;
    const x = c.getContext("2d")!;
    if (background) {
      x.fillStyle = background;
      x.fillRect(0, 0, w, h);
    }
    x.font = `600 ${fontPx}px system-ui, sans-serif`;
    x.fillStyle = color;
    x.textBaseline = "top";
    content.forEach((l, i) => x.fillText(l, pad, pad + i * (fontPx + 6)));
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.minFilter = THREE.LinearFilter;
    return { tex, aspect: w / h };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => () => made?.tex.dispose(), [made]);
  if (!made) return null;
  return (
    <sprite position={position} scale={[scale * made.aspect, scale, 1]} renderOrder={5}>
      <spriteMaterial map={made.tex} transparent depthTest={false} sizeAttenuation />
    </sprite>
  );
}
