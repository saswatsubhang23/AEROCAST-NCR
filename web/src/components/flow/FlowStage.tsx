"use client";

import { BitmapLayer, ScatterplotLayer } from "@deck.gl/layers";
import { useEffect, useMemo } from "react";
import { TOOLTIP_STYLE, useBaseMap } from "@/components/map/useBaseMap";
import { colourAtValue, type Scale, type VectorField } from "@/lib/flow/field";
import type { FlowFrames } from "@/lib/flow/frames";
import { latticeBounds, rasterDataUrl } from "@/lib/twin/layers/raster";
import { FlowCanvas } from "./FlowCanvas";

export type StageProps = {
  frames: FlowFrames;
  k: number;
  scale: Scale;
  colourBy: "pollutant" | "wind";
  particles: number;
  concentrationOpacity: number;
  flowOpacity: number;
  paused: boolean;
  showStations: boolean;
  /** Simulated seconds of drift per animation frame. */
  secondsPerFrame: number;
  resetToken: number;
  onPick: (p: { lat: number; lon: number }) => void;
  picked: { lat: number; lon: number } | null;
  /** Shown in the corner of the map. */
  corner?: React.ReactNode;
};

/** The 2-D air-flow stage: a MapLibre map, the concentration field under it, and air flowing over it. */
export default function FlowStage(p: StageProps) {
  const { container, overlay, basemapFailed, basemap, map, resetView } = useBaseMap();
  const scalar = useMemo(() => p.frames.scalarAt(p.k), [p.frames, p.k]);
  const wind: VectorField | null = useMemo(() => p.frames.windAt(p.k), [p.frames, p.k]);

  useEffect(() => {
    if (p.resetToken > 0) resetView();
  }, [p.resetToken, resetView]);

  // concentration field and station rings (deck.gl, one overlay)
  useEffect(() => {
    const layers: unknown[] = [];
    if (scalar && p.concentrationOpacity > 0) {
      const lattice = { lats: scalar.lats, lons: scalar.lons };
      const url = rasterDataUrl(scalar.grid, lattice, p.scale.bins, 320, { kind: "ramp" });
      if (url) layers.push(new BitmapLayer({ id: "flow-concentration", image: url, bounds: latticeBounds(lattice), opacity: p.concentrationOpacity, pickable: false }));
    }
    if (p.showStations) {
      const st = p.frames.stationsAt(p.k).filter((s) => Number.isFinite(s.lat) && Number.isFinite(s.lon));
      layers.push(
        new ScatterplotLayer<(typeof st)[number]>({
          id: "flow-stations", data: st, getPosition: (d) => [d.lon, d.lat], radiusUnits: "pixels", getRadius: 5, filled: true,
          getFillColor: (d) => { const c = colourAtValue(p.scale, d.value); return c ? [c[0], c[1], c[2], 255] : [0, 0, 0, 0]; },
          stroked: true, lineWidthUnits: "pixels", getLineWidth: 1.5, getLineColor: [240, 244, 252, 230], pickable: true,
          updateTriggers: { getFillColor: [p.scale, p.k, p.frames] },
        }),
      );
    }
    if (p.picked) {
      layers.push(
        new ScatterplotLayer<{ lat: number; lon: number }>({
          id: "flow-picked", data: [p.picked], getPosition: (d) => [d.lon, d.lat], radiusUnits: "pixels", getRadius: 11, filled: false, stroked: true,
          lineWidthUnits: "pixels", getLineWidth: 2.5, getLineColor: [255, 210, 63, 255], pickable: false,
        }),
      );
    }
    overlay.current?.setProps({
      layers: layers as never,
      getTooltip: ({ object }: { object?: { name?: string; value?: number | null } }) =>
        object && object.name ? { html: `<div style="font-weight:600">${object.name}</div><div>${object.value === null || object.value === undefined ? "no value at this hour" : `${object.value.toFixed(1)} ${p.frames.unit}`}</div>`, style: TOOLTIP_STYLE } : null,
    });
  }, [scalar, p.scale, p.concentrationOpacity, p.showStations, p.frames, p.k, p.picked, overlay]);

  // clicks inspect a point
  useEffect(() => {
    if (!map) return;
    const click = (e: { lngLat: { lat: number; lng: number } }) => p.onPick({ lat: e.lngLat.lat, lon: e.lngLat.lng });
    map.on("click", click);
    return () => {
      map.off("click", click);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-line">
      <div ref={container} className="h-[min(72vh,640px)] min-h-[380px] w-full" role="application" aria-label="Map of Delhi-NCR with air flowing over it, coloured by concentration" />
      <FlowCanvas
        map={map}
        render={{
          field: wind,
          scalar: scalar ? { ...scalar, scale: p.scale } : null,
          colourBy: p.colourBy,
          count: p.particles,
          secondsPerFrame: p.secondsPerFrame,
          opacity: p.flowOpacity,
          paused: p.paused,
          lightBase: basemap === "voyager",
        }}
      />
      {p.corner}
      {!wind && <p className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-surface/95 px-3 py-1.5 text-xs text-warn">No weather-model wind for this hour: nothing is animated, and no flow is invented.</p>}
      {basemapFailed && <p className="absolute bottom-2 left-2 rounded bg-surface-2 px-2 py-1 text-xs text-muted">Basemap tiles could not be loaded; the data are still shown.</p>}
      {basemap === "satellite" && <p className="pointer-events-none absolute bottom-6 left-2 max-w-[60%] rounded bg-surface/90 px-2 py-1 text-[11px] text-muted">Satellite: Sentinel-2 composite from 2020, a reference image, not today&apos;s view.</p>}
    </div>
  );
}
