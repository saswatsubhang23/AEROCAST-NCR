"use client";

import { useMemo, useState } from "react";
import { EChart } from "@/components/charts/EChart";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { sampleBilinear, windSpeedAt, type FieldKey, type FieldsResponse } from "@/lib/twin/fields";
import { formatIST } from "@/lib/weather/time";
import { compass } from "@/lib/weather/wind";

const AXIS = { axisLine: { lineStyle: { color: "#22314d" } }, axisLabel: { color: "#9db0cc" }, splitLine: { lineStyle: { color: "#16233a" } } };
const SHOWN: FieldKey[] = ["temperature_2m", "relative_humidity_2m", "pressure_msl", "precipitation", "cloud_cover", "boundary_layer_height"];

/** Values of every field at the clicked point and hour, with the whole time series of one variable beside it. Clicking the chart moves the timeline. */
export function FieldInspector({ fields, index, point, onSeek }: {
  fields: FieldsResponse; index: number; point: { lat: number; lon: number } | null; onSeek: (i: number) => void;
}) {
  const [variable, setVariable] = useState<FieldKey>("precipitation");
  const lattice = fields.grid;

  const at = useMemo(() => {
    if (!point) return null;
    const u = fields.variables.wind_u.values[index];
    const v = fields.variables.wind_v.values[index];
    const uu = sampleBilinear(u, lattice, point.lat, point.lon);
    const vv = sampleBilinear(v, lattice, point.lat, point.lon);
    return {
      values: SHOWN.map((k) => ({ key: k, value: sampleBilinear(fields.variables[k].values[index], lattice, point.lat, point.lon) })),
      speed: windSpeedAt(u, v, lattice, point.lat, point.lon),
      fromDeg: uu !== null && vv !== null ? ((Math.atan2(-uu, -vv) * 180) / Math.PI + 360) % 360 : null,
    };
  }, [fields, index, point, lattice]);

  const series = useMemo(
    () => (point ? fields.variables[variable].values.map((g) => sampleBilinear(g, lattice, point.lat, point.lon)) : null),
    [fields, variable, point, lattice],
  );

  const option = useMemo(() => {
    if (!series) return null;
    const unit = fields.variables[variable].unit;
    return {
      grid: { left: 48, right: 12, top: 16, bottom: 28 },
      tooltip: { trigger: "axis", valueFormatter: (x: number | null) => (x === null ? "no value" : `${x.toFixed(1)} ${unit}`) },
      xAxis: { type: "category", data: fields.times.map((t) => formatIST(t)), ...AXIS, axisLabel: { color: "#9db0cc", hideOverlap: true } },
      yAxis: { type: "value", name: unit, nameTextStyle: { color: "#9db0cc" }, ...AXIS },
      series: [{
        type: variable === "precipitation" ? "bar" : "line", data: series, showSymbol: false, color: "#79dfd0", connectNulls: false,
        markLine: { symbol: "none", silent: true, label: { formatter: "selected hour", color: "#9db0cc" }, lineStyle: { color: "#ffd23f", type: "dashed" }, data: [{ xAxis: index }] },
      }],
    };
  }, [series, fields, variable, index]);

  if (!point) return <p className="text-sm text-muted">Click the map to inspect the model values at that point.</p>;
  const label = (k: FieldKey) => fields.variables[k].label;
  return (
    <div className="space-y-3 text-sm">
      <div>
        <h2 className="font-semibold">Inspected point</h2>
        <p className="text-xs text-muted">{point.lat.toFixed(3)}°N, {point.lon.toFixed(3)}°E · {formatIST(fields.times[index])}</p>
      </div>
      {at && (
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Model values at the inspected point and selected hour</caption>
          <thead className="border-b border-line uppercase tracking-wider text-muted">
            <tr>
              <th scope="col" className="py-1 pr-2 font-medium">Variable</th>
              <th scope="col" className="py-1 font-medium">Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {at.values.map((r) => (
              <tr key={r.key}>
                <th scope="row" className="py-1 pr-2 text-left font-normal">{label(r.key)}</th>
                <td className="py-1 font-mono">{r.value === null ? "no value" : `${r.value.toFixed(r.key === "precipitation" || r.key === "pressure_msl" ? 1 : 0)} ${fields.variables[r.key].unit}`}</td>
              </tr>
            ))}
            <tr>
              <th scope="row" className="py-1 pr-2 text-left font-normal">Wind (10 m)</th>
              <td className="py-1 font-mono">
                {at.speed === null || at.fromDeg === null ? "no value" : `${at.speed.toFixed(1)} m/s from ${compass(at.fromDeg)} (${at.fromDeg.toFixed(0)}°)`}
              </td>
            </tr>
          </tbody>
        </table>
      )}
      <label className="flex items-center gap-1.5 text-xs text-muted">
        Time series
        <select value={variable} onChange={(e) => setVariable(e.target.value as FieldKey)} className="h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
          {SHOWN.map((k) => (
            <option key={k} value={k}>{label(k)}</option>
          ))}
        </select>
      </label>
      {option && (
        <EChart option={option} height={200} ariaLabel={`${label(variable)} at the inspected point over the loaded window; click to move the timeline`} onSelectIndex={onSeek} />
      )}
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <ProvenanceBadge kind="weather_forecast" />
        Bilinear interpolation of model values between lattice points about {fields.grid.spacing_deg.lat.toFixed(2)}° apart; not a measurement at this spot.
      </p>
    </div>
  );
}
