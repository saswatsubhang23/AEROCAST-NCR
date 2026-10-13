"use client";

import { useMemo, useState } from "react";
import { EChart } from "@/components/charts/EChart";
import type { ModelStatus, TwinPollutant } from "@/lib/twin/types";

const AXIS = { axisLine: { lineStyle: { color: "#22314d" } }, axisLabel: { color: "#9db0cc" }, splitLine: { lineStyle: { color: "#16233a" } } };

/** Charts drawn only from the saved run: held-out MAE against persistence, interval coverage, and tree-model feature importance. */
export function ModelDiagnostics({ model }: { model: ModelStatus }) {
  const pollutants = useMemo(() => [...new Set(model.targets.map((t) => t.pollutant))], [model.targets]);
  const [pollutant, setPollutant] = useState<TwinPollutant>(pollutants[0]);
  const rows = model.targets.filter((t) => t.pollutant === pollutant).sort((a, b) => a.horizon_hours - b.horizon_hours);

  const maeOption = useMemo(
    () => ({
      grid: { left: 52, right: 14, top: 28, bottom: 28 },
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#9db0cc" }, top: 0, right: 0 },
      xAxis: { type: "category", data: rows.map((r) => `+${r.horizon_hours} h`), ...AXIS },
      yAxis: { type: "value", name: "MAE µg/m³", nameTextStyle: { color: "#9db0cc" }, min: 0, ...AXIS },
      series: [
        { name: "Persistence", type: "bar", data: rows.map((r) => r.persistence_test?.mae ?? null), color: "#35527f" },
        { name: "Trained model", type: "bar", data: rows.map((r) => r.test?.mae ?? null), color: "#22d3ee" },
      ],
    }),
    [rows],
  );

  const imp = model.importance?.[pollutant];
  const [firstModel] = imp ? Object.keys(imp) : [];
  const top = (firstModel ? imp![firstModel] : []).slice(0, 10).reverse();
  const impOption = useMemo(
    () => ({
      grid: { left: 150, right: 20, top: 8, bottom: 24 },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => `${(v * 100).toFixed(1)}%` },
      xAxis: { type: "value", axisLabel: { color: "#9db0cc", formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: "#16233a" } } },
      yAxis: { type: "category", data: top.map((t) => t.feature), axisLabel: { color: "#9db0cc" }, axisLine: AXIS.axisLine },
      series: [{ type: "bar", data: top.map((t) => t.importance), color: "#79dfd0" }],
    }),
    [top],
  );

  return (
    <section aria-label="Model diagnostics" className="space-y-4 rounded-lg border border-line bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-semibold">Held-out diagnostics</h2>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Pollutant
          <select value={pollutant} onChange={(e) => setPollutant(e.target.value as TwinPollutant)} className="h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
            {pollutants.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-muted">Mean absolute error on the held-out period, model against persistence (lower is better)</p>
        <EChart option={maeOption} height={220} ariaLabel={`Held-out mean absolute error for ${pollutant} by horizon, trained model against persistence`} />
      </div>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Interval coverage and station spread by horizon, scrollable">
        <table className="w-full min-w-96 text-left text-xs">
          <caption className="sr-only">Prediction-interval coverage and location spread by horizon</caption>
          <thead className="border-b border-line uppercase tracking-wider text-muted">
            <tr>
              {["Horizon", "Interval nominal", "Measured coverage (test)", "Mean width", "Station MAE min / median / max"].map((h) => (
                <th key={h} scope="col" className="px-2 py-1 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.horizon_hours}>
                <td className="px-2 py-1">+{r.horizon_hours} h</td>
                <td className="px-2 py-1 font-mono">{r.calibration ? `${Math.round(r.calibration.nominal * 100)}%` : "n/a"}</td>
                <td className="px-2 py-1 font-mono">{r.calibration ? `${(r.calibration.empirical_coverage_test * 100).toFixed(1)}%` : "n/a"}</td>
                <td className="px-2 py-1 font-mono">{r.calibration ? r.calibration.mean_width.toFixed(1) : "n/a"}</td>
                <td className="px-2 py-1 font-mono">{r.per_station ? `${r.per_station.mae_min?.toFixed(1)} / ${r.per_station.mae_median?.toFixed(1)} / ${r.per_station.mae_max?.toFixed(1)} (${r.per_station.stations} st)` : "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {top.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted">Most influential inputs ({firstModel}, gain importance; indicative, not causal)</p>
          <EChart option={impOption} height={260} ariaLabel={`Top input features of the ${firstModel} model for ${pollutant}`} />
        </div>
      )}
    </section>
  );
}
