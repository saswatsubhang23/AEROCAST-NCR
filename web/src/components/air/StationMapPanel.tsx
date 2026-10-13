"use client";

import { useEffect, useMemo } from "react";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TOOLTIP_STYLE, useBaseMap } from "@/components/map/useBaseMap";
import { MapLegend } from "@/components/ui/MapLegend";
import { commonUnit, formatAgeShort, labelOf, unitKey } from "@/lib/air/pollutants";
import type { PollutantKey, Station } from "@/lib/air/types";
import { makeScale } from "@/lib/weather/scales";
import { formatIST } from "@/lib/weather/time";

function tooltip(s: Station, p: PollutantKey): string {
  const r = s.latest[p];
  const head = `<div style="font-weight:600">${s.name}</div>${s.locality ? `<div>${s.locality}</div>` : ""}`;
  const prov = `<div style="color:#9db0cc">${s.provider ?? "Unknown provider"}</div>`;
  let body: string;
  if (r) {
    body = `<div style="margin-top:4px">${labelOf(p)}: <b>${r.value} ${r.unit}</b></div><div>${formatIST(r.observed_at)} (${formatAgeShort(r.age_s)})${r.stale ? " · stale" : ""}</div>`;
  } else if (!s.pollutants[p]) {
    body = `<div style="margin-top:4px">No ${labelOf(p)} sensor at this station</div>`;
  } else {
    body = `<div style="margin-top:4px">${labelOf(p)}: no recent reading</div>`;
  }
  return `${head}${prov}${body}<div style="color:#9db0cc;margin-top:4px">Click to select</div>`;
}

export default function StationMapPanel({
  stations,
  pollutant,
  selectedId,
  onSelect,
}: {
  stations: Station[];
  pollutant: PollutantKey;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const { container, overlay, basemapFailed } = useBaseMap();

  const unit = useMemo(() => commonUnit(stations, pollutant), [stations, pollutant]);
  const { valued, other, scale } = useMemo(() => {
    const valued: Station[] = [];
    const other: Station[] = [];
    for (const s of stations) {
      const r = s.latest[pollutant];
      (r && unit && unitKey(r.unit) === unitKey(unit) ? valued : other).push(s);
    }
    const values = valued.map((s) => s.latest[pollutant]!.value);
    const scale = makeScale(values, { min: 0, decimals: pollutant === "co" ? 1 : 0 });
    return { valued, other, scale };
  }, [stations, pollutant, unit]);

  useEffect(() => {
    if (!overlay.current) return;
    const selected = stations.filter((s) => s.id === selectedId);
    overlay.current.setProps({
      layers: [
        new ScatterplotLayer<Station>({
          id: "no-value",
          data: other,
          getPosition: (s) => [s.lon, s.lat],
          radiusUnits: "pixels",
          getRadius: 8,
          filled: false,
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 2,
          getLineColor: [157, 176, 204, 255],
          pickable: true,
        }),
        new ScatterplotLayer<Station>({
          id: "valued",
          data: valued,
          getPosition: (s) => [s.lon, s.lat],
          radiusUnits: "pixels",
          getRadius: 11,
          getFillColor: (s) => scale?.colorFor(s.latest[pollutant]!.value) ?? [0, 0, 0, 0],
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 1.5,
          getLineColor: [10, 17, 32, 255],
          pickable: true,
          updateTriggers: { getFillColor: [pollutant, scale] },
        }),
        new ScatterplotLayer<Station>({
          id: "selected",
          data: selected,
          getPosition: (s) => [s.lon, s.lat],
          radiusUnits: "pixels",
          getRadius: 17,
          filled: false,
          stroked: true,
          lineWidthUnits: "pixels",
          getLineWidth: 3,
          getLineColor: [34, 211, 238, 255],
        }),
        new TextLayer<Station>({
          id: "selected-label",
          data: selected,
          getPosition: (s) => [s.lon, s.lat],
          getText: (s) => s.name,
          getSize: 12,
          getColor: [232, 238, 248, 255],
          getPixelOffset: [0, -28],
          outlineWidth: 3,
          outlineColor: [10, 17, 32, 255],
          fontSettings: { sdf: true },
        }),
      ],
      getTooltip: ({ object }) =>
        object ? { html: tooltip(object as Station, pollutant), style: TOOLTIP_STYLE } : null,
      onClick: ({ object }) => {
        if (object) onSelect((object as Station).id);
      },
    });
  }, [overlay, other, valued, scale, selectedId, stations, pollutant, onSelect]);

  return (
    <div>
      <div className="relative overflow-hidden rounded-lg border border-line">
        <div
          ref={container}
          className="h-[360px] w-full sm:h-[440px]"
          role="application"
          aria-label="Map of air-quality monitoring stations in Delhi-NCR"
        />
        {basemapFailed && (
          <p className="absolute bottom-2 left-2 rounded bg-surface-2 px-2 py-1 text-xs text-muted">
            Basemap tiles could not be loaded; stations are still shown.
          </p>
        )}
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          {scale && unit ? (
            <MapLegend title={`Latest ${labelOf(pollutant)}`} unit={unit} items={scale.legend} />
          ) : (
            <p className="rounded-lg border border-line bg-surface p-3 text-sm text-muted">
              No station has a recent {labelOf(pollutant)} reading.
            </p>
          )}
          <p className="flex items-center gap-2 text-xs text-muted">
            <span className="inline-block h-3 w-3 rounded-full border-2 border-muted" aria-hidden="true" />
            Hollow ring: no recent reading, no sensor, or a different unit than the legend.
          </p>
        </div>
        <p className="max-w-md text-xs text-muted">
          Each dot is a real monitoring station, coloured by its latest reported concentration (not an AQI). Values are
          not interpolated between stations, and no pollution forecast or heatmap is shown.
        </p>
      </div>
    </div>
  );
}
