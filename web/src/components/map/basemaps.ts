// The basemaps every map in the application can show. Voyager and Dark are CARTO vector maps; Satellite and Relief are static reference
// layers (a 2020 cloud-free composite and a terrain-shaded relief), never live imagery, and are described that way on the map.

import type { StyleSpecification } from "maplibre-gl";

export type BasemapId = "voyager" | "dark" | "satellite" | "relief";

/** CARTO account key (web/.env.local). Public by design, like any tile key; restrict it to your domains in the CARTO dashboard. Blank works too. */
const CARTO_KEY = process.env.NEXT_PUBLIC_CARTO_API_KEY ?? "";
const keyed = (url: string) => (CARTO_KEY ? `${url}${url.includes("?") ? "&" : "?"}key=${encodeURIComponent(CARTO_KEY)}` : url);

export const BASEMAPS: { id: BasemapId; label: string; hint: string }[] = [
  { id: "voyager", label: "Voyager", hint: "CARTO Voyager: roads, water and place names on a light map" },
  { id: "dark", label: "Dark", hint: "Roads and place names on a dark background" },
  { id: "satellite", label: "Satellite", hint: "Sentinel-2 cloudless composite, 2020. Not today's view: it does not show current cloud or haze." },
  { id: "relief", label: "Relief", hint: "Terrain shading from SRTM-based elevation tiles, with place names" },
];

export const DEFAULT_BASEMAP: BasemapId = "voyager";
export const DARK_STYLE_URL = keyed("https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json");
export const VOYAGER_STYLE_URL = keyed("https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json");

const S2_TILES = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg";
const DEM_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
const LABEL_TILES = keyed("https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png");
const BG = "#0f1829";

const labels = {
  source: { type: "raster" as const, tiles: [LABEL_TILES], tileSize: 256, maxzoom: 18, attribution: "© OpenStreetMap contributors © CARTO" },
  layer: { id: "labels", type: "raster" as const, source: "labels", paint: { "raster-opacity": 0.95 } },
};

export const SATELLITE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    s2: {
      type: "raster", tiles: [S2_TILES], tileSize: 256, maxzoom: 13,
      attribution: "Sentinel-2 cloudless © <a href=\"https://s2maps.eu\" target=\"_blank\" rel=\"noreferrer\">EOX IT Services</a> (contains modified Copernicus Sentinel data 2020), CC BY-NC-SA 4.0",
    },
    labels: labels.source,
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": BG } },
    { id: "s2", type: "raster", source: "s2", paint: { "raster-saturation": -0.12, "raster-brightness-max": 0.92 } },
    labels.layer,
  ],
};

export const RELIEF_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    dem: { type: "raster-dem", tiles: [DEM_TILES], encoding: "terrarium", tileSize: 256, maxzoom: 12, attribution: "Terrain Tiles © Mapzen, AWS Open Data (SRTM, ASTER and other public DEMs)" },
    labels: labels.source,
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#18243b" } },
    {
      id: "relief", type: "hillshade", source: "dem",
      paint: { "hillshade-exaggeration": 1, "hillshade-shadow-color": "#05080f", "hillshade-highlight-color": "#9fb4d6", "hillshade-accent-color": "#33496e", "hillshade-illumination-direction": 315 },
    },
    labels.layer,
  ],
};

const KEY = "aerocast.basemap";

export function readStoredBasemap(): BasemapId {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === "voyager" || v === "dark" || v === "satellite" || v === "relief") return v;
  } catch {
    // storage can be blocked (private window); the default is used
  }
  return DEFAULT_BASEMAP;
}

export function storeBasemap(id: BasemapId): void {
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    // not persisted; the choice still applies for this page
  }
}

export function styleFor(id: BasemapId): string | StyleSpecification {
  return id === "satellite" ? SATELLITE_STYLE : id === "relief" ? RELIEF_STYLE : id === "voyager" ? VOYAGER_STYLE_URL : DARK_STYLE_URL;
}
