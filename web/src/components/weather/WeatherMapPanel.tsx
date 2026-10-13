"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { IconLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TOOLTIP_STYLE, useBaseMap } from "@/components/map/useBaseMap";
import { MapLegend } from "@/components/ui/MapLegend";
import { ErrorState, LoadingState, UnavailableState } from "@/components/ui/states";
import { useLocation } from "@/lib/location";
import { LOCATIONS } from "@/lib/locations";
import { useWeather } from "@/lib/weather/context";
import { MAP_LAYERS, makeScale, type MapLayerKey } from "@/lib/weather/scales";
import { formatIST } from "@/lib/weather/time";
import { compass, deckArrowAngle } from "@/lib/weather/wind";
import type { GridForecast } from "@/lib/weather/types";

const ARROW = `data:image/svg+xml;utf8,${encodeURIComponent(
  "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64' viewBox='0 0 64 64'><path d='M32 4 L50 36 H37 V60 H27 V36 H14 Z' fill='white'/></svg>",
)}`;

type Cell = {
  lon: number;
  lat: number;
  elevation: number | null;
  values: Record<string, number | null>;
};

function cellsAt(grid: GridForecast, i: number): Cell[] {
  return grid.points.map((p) => ({
    lon: p.location.grid_lon,
    lat: p.location.grid_lat,
    elevation: p.location.elevation_m,
    values: Object.fromEntries(grid.variables.map((v) => [v.key, p.series[v.key]?.[i] ?? null])),
  }));
}

function tooltipHtml(grid: GridForecast, cell: Cell): string {
  const rows = grid.variables
    .map((v) => {
      const val = cell.values[v.key];
      const text =
        val === null
          ? "no data"
          : v.key === "wind_direction_10m"
            ? `${val}° (${compass(val)})`
            : `${val} ${v.unit}`;
      return `<div>${v.label}: <b>${text}</b></div>`;
    })
    .join("");
  const elev = cell.elevation !== null ? ` · ${cell.elevation} m` : "";
  return `<div style="font-weight:600;margin-bottom:4px">Model cell ${cell.lat.toFixed(2)}°N ${cell.lon.toFixed(2)}°E${elev}</div>${rows}`;
}

export default function WeatherMapPanel() {
  const { grid, point, selected } = useWeather();
  const { location, setLocationId } = useLocation();
  const [layerKey, setLayerKey] = useState<MapLayerKey>("temperature_2m");
  const [show, setShow] = useState({ values: true, wind: true, cities: true });

  const { container, overlay, basemapFailed } = useBaseMap();
  const selectCity = useRef(setLocationId);
  useEffect(() => {
    selectCity.current = setLocationId;
  }, [setLocationId]);

  const gridData = grid.status === "ready" ? grid.data : null;
  // Map index for the selected timestamp; -1 if the grid does not cover it.
  const gi = useMemo(() => {
    if (!gridData || point.status !== "ready") return -1;
    return gridData.times.indexOf(point.data.times[selected]);
  }, [gridData, point, selected]);

  const layerDef = MAP_LAYERS.find((l) => l.key === layerKey)!;
  const available = useMemo(() => new Set(gridData?.variables.map((v) => v.key)), [gridData]);
  const scale = useMemo(() => {
    if (!gridData) return null;
    const all = gridData.points.flatMap((p) => p.series[layerKey] ?? []);
    const { decimals } = layerDef;
    const o = layerDef as { min?: number; max?: number; minSpan?: number };
    return makeScale(all, { decimals, min: o.min, max: o.max, minSpan: o.minSpan });
  }, [gridData, layerKey, layerDef]);
  const unit = gridData?.variables.find((v) => v.key === layerKey)?.unit;

  const cells = useMemo(() => (gridData && gi >= 0 ? cellsAt(gridData, gi) : []), [gridData, gi]);

  useEffect(() => {
    if (!overlay.current) return;
    const layers = [];
    if (gridData && gi >= 0) {
      if (show.values && scale) {
        layers.push(
          new ScatterplotLayer<Cell>({
            id: "cells",
            data: cells.filter((c) => c.values[layerKey] !== null),
            getPosition: (c) => [c.lon, c.lat],
            radiusUnits: "pixels",
            getRadius: 22,
            getFillColor: (c) => scale.colorFor(c.values[layerKey]) ?? [0, 0, 0, 0],
            stroked: true,
            lineWidthUnits: "pixels",
            getLineWidth: 1,
            getLineColor: [232, 238, 248, 110],
            pickable: true,
            updateTriggers: { getFillColor: [layerKey, scale] },
          }),
        );
      }
      if (show.wind && available.has("wind_speed_10m") && available.has("wind_direction_10m")) {
        layers.push(
          new IconLayer<Cell>({
            id: "wind",
            data: cells.filter((c) => c.values.wind_speed_10m !== null && c.values.wind_direction_10m !== null),
            iconAtlas: ARROW,
            iconMapping: { arrow: { x: 0, y: 0, width: 64, height: 64, mask: true } },
            getIcon: () => "arrow",
            getPosition: (c) => [c.lon, c.lat],
            getAngle: (c) => deckArrowAngle(c.values.wind_direction_10m as number),
            getSize: (c) => 14 + Math.min(c.values.wind_speed_10m as number, 40) * 0.7,
            sizeUnits: "pixels",
            getColor: [8, 14, 26, 255],
            pickable: true,
          }),
        );
      }
    }
    if (show.cities) {
      layers.push(
        new ScatterplotLayer({
          id: "cities",
          data: LOCATIONS,
          getPosition: (l) => [l.lon, l.lat],
          radiusUnits: "pixels",
          getRadius: (l) => (l.id === location.id ? 8 : 5),
          getFillColor: (l) => (l.id === location.id ? [34, 211, 238, 255] : [232, 238, 248, 255]),
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 2,
          getLineColor: [10, 17, 32, 255],
          pickable: true,
          updateTriggers: { getRadius: location.id, getFillColor: location.id },
        }),
        new TextLayer({
          id: "city-labels",
          data: LOCATIONS,
          getPosition: (l) => [l.lon, l.lat],
          getText: (l) => l.name,
          getSize: 12,
          getColor: [232, 238, 248, 255],
          getPixelOffset: [0, -18],
          outlineWidth: 3,
          outlineColor: [10, 17, 32, 255],
          fontSettings: { sdf: true },
        }),
      );
    }
    overlay.current.setProps({
      layers,
      getTooltip: ({ object, layer }) => {
        if (!object || !gridData) return null;
        if (layer?.id === "cities") {
          const l = object as (typeof LOCATIONS)[number];
          return { html: `<b>${l.name}</b><div>Click to select this location</div>`, style: TOOLTIP_STYLE };
        }
        return { html: tooltipHtml(gridData, object as Cell), style: TOOLTIP_STYLE };
      },
      onClick: ({ object, layer }) => {
        if (layer?.id === "cities" && object) selectCity.current((object as (typeof LOCATIONS)[number]).id);
      },
    });
  }, [overlay, gridData, gi, cells, scale, layerKey, show, location.id, available]);

  if (grid.status === "loading") return <LoadingState label="Loading map data" />;
  if (grid.status === "error")
    return <ErrorState title="Map data is unavailable" message={grid.error.message} />;

  const toggles: { key: keyof typeof show; label: string; disabled?: boolean }[] = [
    { key: "values", label: "Value circles" },
    { key: "wind", label: "Wind vectors", disabled: !available.has("wind_speed_10m") || !available.has("wind_direction_10m") },
    { key: "cities", label: "Cities" },
  ];

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-8 gap-y-3 rounded-lg border border-line bg-surface p-3">
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-muted">Colour by</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {MAP_LAYERS.map((l) => {
              const ok = available.has(l.key);
              return (
                <label key={l.key} className={`flex items-center gap-1.5 text-sm ${ok ? "" : "opacity-50"}`}>
                  <input
                    type="radio"
                    name="map-layer"
                    className="accent-accent"
                    checked={layerKey === l.key}
                    disabled={!ok}
                    onChange={() => setLayerKey(l.key)}
                  />
                  {l.label}
                  {!ok && <span className="text-xs text-muted">(not provided)</span>}
                </label>
              );
            })}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-muted">Show</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {toggles.map((t) => (
              <label key={t.key} className={`flex items-center gap-1.5 text-sm ${t.disabled ? "opacity-50" : ""}`}>
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={show[t.key] && !t.disabled}
                  disabled={t.disabled}
                  onChange={(e) => setShow((s) => ({ ...s, [t.key]: e.target.checked }))}
                />
                {t.label}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      {gi < 0 && (
        <div className="mb-3">
          <UnavailableState title="No map data for the selected time" reason="The sampled grid does not cover this hour." />
        </div>
      )}

      <div className="relative overflow-hidden rounded-lg border border-line">
        <div ref={container} className="h-[380px] w-full sm:h-[460px]" role="application" aria-label="Map of Delhi-NCR weather at the selected time" />
        {basemapFailed && (
          <p className="absolute bottom-2 left-2 rounded bg-surface-2 px-2 py-1 text-xs text-muted">
            Basemap tiles could not be loaded; weather layers are still shown.
          </p>
        )}
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto]">
        {scale && show.values ? (
          <MapLegend title={layerDef.label} unit={unit} items={scale.legend} />
        ) : (
          <div />
        )}
        <p className="max-w-md text-xs text-muted">
          {gridData && gi >= 0 && `Showing ${formatIST(gridData.times[gi])}. `}
          Circles are forecast values at {gridData?.points.length} model grid cells, with no interpolation between them.
          Dark arrows point where the wind blows toward; longer arrows mean stronger wind. Colour ranges cover the whole
          horizon so colours are comparable across hours.
        </p>
      </div>
    </div>
  );
}
