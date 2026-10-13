"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { BasemapControl } from "./BasemapControl";
import { DEFAULT_BASEMAP, readStoredBasemap, storeBasemap, styleFor, type BasemapId } from "./basemaps";

// MapLibre's worker cannot be bundled; it is copied to /public by scripts/copy-maplibre-worker.mjs.
maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const BLANK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#0f1829" } }],
};
const NCR_BOUNDS: [[number, number], [number, number]] = [[76.6, 28.05], [77.95, 29.1]];

/**
 * Creates a Delhi-NCR map with a deck.gl overlay inside `container`. Data layers are set through `overlay.current.setProps`.
 * Every map gets the same Voyager / Dark / Satellite / Relief switch; the choice is remembered in this browser.
 */
export function useBaseMap() {
  const container = useRef<HTMLDivElement>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [basemap, setBasemap] = useState<BasemapId>(DEFAULT_BASEMAP);
  // exposed so overlays that draw on the map (the air-flow canvas) can project coordinates; null before the map exists and after it is removed
  const [map, setMap] = useState<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const initial = readStoredBasemap();
    setBasemap(initial);
    const map = new maplibregl.Map({
      container: container.current,
      style: styleFor(initial),
      bounds: NCR_BOUNDS,
      fitBoundsOptions: { padding: 16 },
      attributionControl: { compact: true },
      dragRotate: false,
    });
    mapRef.current = map;
    setMap(map);
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(
      new BasemapControl(initial, (id) => {
        storeBasemap(id);
        setBasemap(id);
        setBasemapFailed(false);
        fellBack = false;
        map.setStyle(styleFor(id));
      }),
      "top-right",
    );
    const ov = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(ov as unknown as maplibregl.IControl);
    overlay.current = ov;

    let fellBack = false;
    map.on("error", () => {
      // If the basemap cannot load (offline, blocked), keep the data layers usable on a plain background.
      if (!fellBack && !map.isStyleLoaded()) {
        fellBack = true;
        map.setStyle(BLANK_STYLE);
        setBasemapFailed(true);
      }
    });
    return () => {
      overlay.current = null;
      mapRef.current = null;
      setMap(null);
      map.remove();
    };
  }, []);

  /** Back to the whole Delhi-NCR view. */
  const resetView = useCallback(() => mapRef.current?.fitBounds(NCR_BOUNDS, { padding: 16, duration: 400 }), []);

  return { container, overlay, basemapFailed, basemap, resetView, map };
}

export const TOOLTIP_STYLE = {
  backgroundColor: "#142036",
  color: "#e8eef8",
  border: "1px solid #22314d",
  borderRadius: "6px",
  fontSize: "12px",
  padding: "8px 10px",
};
