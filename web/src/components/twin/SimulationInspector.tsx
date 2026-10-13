"use client";

import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { nearestStation, sampleRun, type SimulationRun } from "@/lib/twin/simulation";
import { windSpeedAt } from "@/lib/twin/fields";
import { formatIST } from "@/lib/weather/time";

const AXIS = { axisLine: { lineStyle: { color: "#22314d" } }, axisLabel: { color: "#9db0cc" }, splitLine: { lineStyle: { color: "#16233a" } } };

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <tr>
      <th scope="row" className="py-1 pr-2 text-left font-normal">{k}</th>
      <td className="py-1 font-mono">{children}</td>
    </tr>
  );
}

/** Click-to-inspect for a run: simulated value, spread, nearest observation, wind, and the simulated series with the observations of the nearest station. */
export function SimulationInspector({ run, index, point, onSeek }: { run: SimulationRun; index: number; point: { lat: number; lon: number } | null; onSeek: (i: number) => void }) {
  const f = Math.min(index, run.concentration.length - 1);
  const near = useMemo(() => (point ? nearestStation(run, point.lat, point.lon) : null), [run, point]);

  const series = useMemo(() => {
    if (!point) return null;
    const sim = run.concentration.map((g) => sampleRun(g, run.grid, point.lat, point.lon));
    const lo = run.spread ? run.concentration.map((g, k) => { const c = sampleRun(g, run.grid, point.lat, point.lon); const s = sampleRun(run.spread![k], run.grid, point.lat, point.lon); return c === null || s === null ? null : Math.max(0, c - s / 2); }) : null;
    const hi = run.spread ? run.concentration.map((g, k) => { const c = sampleRun(g, run.grid, point.lat, point.lon); const s = sampleRun(run.spread![k], run.grid, point.lat, point.lon); return c === null || s === null ? null : c + s / 2; }) : null;
    const base = run.baseline_concentration ? run.baseline_concentration.map((g) => sampleRun(g, run.grid, point.lat, point.lon)) : null;
    const obs = near ? run.observed.map((row) => row[near.index] ?? null) : null;
    return { sim, lo, hi, base, obs };
  }, [run, point, near]);

  const option = useMemo(() => {
    if (!series) return null;
    const s: unknown[] = [];
    if (series.lo && series.hi) {
      s.push({ name: "spread low", type: "line", data: series.lo, showSymbol: false, lineStyle: { opacity: 0 }, stack: "band", silent: true });
      s.push({ name: "spread", type: "line", data: series.hi.map((h, i) => (h === null || series.lo![i] === null ? null : h - (series.lo![i] as number))), showSymbol: false, lineStyle: { opacity: 0 }, stack: "band", areaStyle: { color: "#6b74c7", opacity: 0.3 }, silent: true });
    }
    s.push({ name: run.mode === "scenario" ? "Scenario (hypothetical)" : "Simulated", type: "line", data: series.sim, showSymbol: false, color: "#79dfd0", connectNulls: false,
      markLine: { symbol: "none", silent: true, label: { formatter: "selected hour", color: "#9db0cc" }, lineStyle: { color: "#ffd23f", type: "dashed" }, data: [{ xAxis: f }] } });
    if (series.base) s.push({ name: "Baseline", type: "line", data: series.base, showSymbol: false, color: "#9db0cc", lineStyle: { type: "dashed" }, connectNulls: false });
    if (series.obs) s.push({ name: "Observed (nearest station)", type: "scatter", data: series.obs, color: "#ffffff", symbolSize: 7 });
    return {
      grid: { left: 48, right: 12, top: 28, bottom: 28 },
      legend: { top: 0, textStyle: { color: "#9db0cc" }, data: s.map((x) => (x as { name: string }).name).filter((n) => n !== "spread low" && n !== "spread") },
      tooltip: { trigger: "axis", valueFormatter: (x: number | null) => (x === null || x === undefined ? "no value" : `${Number(x).toFixed(1)} ${run.unit}`) },
      xAxis: { type: "category", data: run.valid_times.map((t) => formatIST(t)), ...AXIS, axisLabel: { color: "#9db0cc", hideOverlap: true } },
      yAxis: { type: "value", name: run.unit, nameTextStyle: { color: "#9db0cc" }, min: 0, ...AXIS },
      series: s,
    };
  }, [series, run, f]);

  if (!point) return <p className="text-sm text-muted">Click the map to inspect the simulation at that point.</p>;
  const sim = sampleRun(run.concentration[f], run.grid, point.lat, point.lon);
  const spread = run.spread ? sampleRun(run.spread[f], run.grid, point.lat, point.lon) : null;
  const wu = run.wind.u[Math.min(f, run.wind.u.length - 1)];
  const wv = run.wind.v[Math.min(f, run.wind.v.length - 1)];
  const speed = windSpeedAt(wu, wv, { lats: run.wind.lats, lons: run.wind.lons }, point.lat, point.lon);
  const obsVal = near ? run.observed[f]?.[near.index] ?? null : null;
  return (
    <div className="space-y-3 text-sm">
      <div>
        <h2 className="font-semibold">Inspected point</h2>
        <p className="text-xs text-muted">{point.lat.toFixed(3)}°N, {point.lon.toFixed(3)}°E · {formatIST(run.valid_times[f])}</p>
      </div>
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Simulation values at the inspected point and selected hour</caption>
        <thead className="border-b border-line uppercase tracking-wider text-muted">
          <tr><th scope="col" className="py-1 pr-2 font-medium">Quantity</th><th scope="col" className="py-1 font-medium">Value</th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          <Row k={run.mode === "scenario" ? "Scenario (hypothetical)" : "Simulated"}>{sim === null ? "no information here" : `${sim.toFixed(1)} ${run.unit}`}</Row>
          {run.baseline_concentration && <Row k="Baseline">{(() => { const b = sampleRun(run.baseline_concentration![f], run.grid, point.lat, point.lon); return b === null ? "no information" : `${b.toFixed(1)} ${run.unit}`; })()}</Row>}
          {run.spread && <Row k="Sensitivity spread">{spread === null ? "not available" : `±${(spread / 2).toFixed(1)} ${run.unit} (range ${spread.toFixed(1)})`}</Row>}
          <Row k="Wind (model)">{speed === null ? "no value" : `${speed.toFixed(1)} m/s`}</Row>
          <Row k={near ? `Observed, ${run.stations[near.index].name} (${near.km.toFixed(1)} km)` : "Observed"}>{obsVal === null ? "no observation at this hour" : `${obsVal.toFixed(1)} ${run.unit}`}</Row>
        </tbody>
      </table>
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <ProvenanceBadge kind={run.mode === "scenario" ? "hypothetical" : "simulated"} />
        <ProvenanceBadge kind="observed" />
        Simulated values are a computed field; the observation is a different station at a different place.
      </p>
      {option && <EChart option={option} height={220} ariaLabel="Simulated concentration at the inspected point over the run, with the nearest station's observations; click to move the timeline" onSelectIndex={onSeek} />}
    </div>
  );
}
