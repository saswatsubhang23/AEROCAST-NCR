"use client";

import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { labelOf } from "@/lib/air/pollutants";
import { speed } from "@/lib/twin/timeline";
import type { TwinBacktest, TwinMode, TwinWindow } from "@/lib/twin/types";
import type { ApiError } from "@/lib/weather/api";
import { formatIST, formatISTAxis } from "@/lib/weather/time";

const AXIS = { axisLine: { lineStyle: { color: "#22314d" } }, axisLabel: { color: "#9db0cc" }, splitLine: { lineStyle: { color: "#16233a" } } };

export type BacktestState = { status: "idle" } | { status: "loading" } | { status: "error"; error: ApiError } | { status: "ready"; data: TwinBacktest };

export function StationCharts({ w, k, index, mode, backtest }: { w: TwinWindow; k: number; index: number; mode: TwinMode; backtest: BacktestState }) {
  const st = w.stations[k];
  const label = labelOf(w.pollutant);
  const observed = w.values[k];
  const stats = useMemo(() => {
    const v = observed.filter((x): x is number => x !== null);
    return { n: v.length, of: observed.length, min: v.length ? Math.min(...v) : null, max: v.length ? Math.max(...v) : null, mean: v.length ? v.reduce((a, b) => a + b, 0) / v.length : null };
  }, [observed]);

  const seriesOption = useMemo(
    () => ({
      grid: { left: 52, right: 14, top: 18, bottom: 28 },
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v === null || v === undefined ? "no data" : `${Number(v).toFixed(1)} ${w.unit}`) },
      xAxis: { type: "category", data: w.times.map(formatISTAxis), axisLabel: { color: "#9db0cc", hideOverlap: true }, axisLine: AXIS.axisLine },
      yAxis: { type: "value", name: w.unit, nameTextStyle: { color: "#9db0cc" }, scale: false, min: 0, ...AXIS },
      series: [
        {
          name: label, type: "line", data: observed, connectNulls: false, showSymbol: observed.length < 80, color: "#22d3ee",
          markLine: { silent: true, symbol: "none", lineStyle: { color: "#e8eef8", type: "dashed" }, data: [{ xAxis: formatISTAxis(w.times[index]) }], label: { show: false } },
        },
      ],
    }),
    [observed, w, index, label],
  );

  const weatherOption = useMemo(() => {
    if (!w.weather) return null;
    const vRow = w.weather.wind_v_ms[k];
    const ws = w.weather.wind_u_ms[k].map((u, i) => {
      const v = vRow[i];
      return u === null || v === null ? null : Number(speed(u, v).toFixed(2));
    });
    return {
      grid: { left: 52, right: 56, top: 18, bottom: 28 },
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#9db0cc" }, top: 0, right: 0 },
      xAxis: { type: "category", data: w.times.map(formatISTAxis), axisLabel: { color: "#9db0cc", hideOverlap: true }, axisLine: AXIS.axisLine },
      yAxis: [
        { type: "value", name: "m/s", nameTextStyle: { color: "#9db0cc" }, min: 0, ...AXIS },
        { type: "value", name: "m", nameTextStyle: { color: "#9db0cc" }, min: 0, position: "right", axisLabel: { color: "#9db0cc" }, splitLine: { show: false }, axisLine: AXIS.axisLine },
      ],
      series: [
        { name: "Wind speed (model)", type: "line", data: ws, connectNulls: false, showSymbol: false, color: "#3b82f6" },
        { name: "Boundary layer height (model)", type: "line", yAxisIndex: 1, data: w.weather.boundary_layer_height_m[k], connectNulls: false, showSymbol: false, color: "#79dfd0" },
      ],
    };
  }, [w, k]);

  const bt = backtest.status === "ready" ? backtest.data : null;
  const backtestOption = useMemo(() => {
    if (!bt) return null;
    const x = bt.rows.map((r) => formatISTAxis(r.time));
    const hasBand = bt.rows.every((r) => r.lower !== null && r.upper !== null);
    return {
      grid: { left: 52, right: 14, top: 26, bottom: 28 },
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#9db0cc" }, top: 0, right: 0 },
      xAxis: { type: "category", data: x, axisLabel: { color: "#9db0cc" }, axisLine: AXIS.axisLine },
      yAxis: { type: "value", name: bt.unit, nameTextStyle: { color: "#9db0cc" }, min: 0, ...AXIS },
      series: [
        ...(hasBand
          ? [
              { name: "range base", type: "line", stack: "band", data: bt.rows.map((r) => r.lower), lineStyle: { opacity: 0 }, showSymbol: false, tooltip: { show: false }, silent: true },
              { name: `${Math.round((bt.interval_level ?? 0) * 100)}% interval`, type: "line", stack: "band", data: bt.rows.map((r) => (r.upper as number) - (r.lower as number)), lineStyle: { opacity: 0 }, areaStyle: { color: "#3b82f6", opacity: 0.2 }, showSymbol: false },
            ]
          : []),
        { name: "Model forecast", type: "line", data: bt.rows.map((r) => r.predicted), color: "#3b82f6", showSymbol: true },
        { name: "Observed afterwards", type: "scatter", data: bt.rows.map((r) => r.observed), color: "#22d3ee", symbolSize: 9 },
      ],
    };
  }, [bt]);

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">{st.name}</h2>
          <ProvenanceBadge kind="observed" />
        </div>
        <p className="text-xs text-muted">
          {st.zone ?? "NCR"} · {st.agency ?? "unknown agency"} · {st.lat.toFixed(4)}°N {st.lon.toFixed(4)}°E · {stats.n} of {stats.of} hours observed in this window
          {stats.min !== null && ` · min ${stats.min.toFixed(1)}, mean ${(stats.mean as number).toFixed(1)}, max ${(stats.max as number).toFixed(1)} ${w.unit}`}
        </p>
      </div>
      <EChart option={seriesOption} height={220} ariaLabel={`${label} hourly observations at ${st.name}; ${stats.n} of ${stats.of} hours have data. Gaps are hours without an observation.`} />
      {weatherOption && (
        <div>
          <p className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
            Weather at the station point <ProvenanceBadge kind="weather_forecast" />
          </p>
          <EChart option={weatherOption} height={200} ariaLabel={`Wind speed and boundary layer height at ${st.name}`} />
        </div>
      )}
      {mode === "forecast" && (
        <div>
          <p className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
            Model forecast from {formatIST(w.times[index])} against what was observed <ProvenanceBadge kind="model_forecast" />
          </p>
          {backtest.status === "loading" && <LoadingState label="Running the trained model" />}
          {backtest.status === "error" && <ErrorState title="No model forecast for this station and hour" message={backtest.error.message} />}
          {bt && backtestOption && (
            <>
              <EChart option={backtestOption} height={240} ariaLabel={`Model forecast and later observations of ${label} at ${st.name}`} />
              <p className="mt-1 text-xs text-muted">
                Model {bt.model_version}. {bt.scored.n} of {bt.rows.length} forecast hours have an observation afterwards
                {bt.scored.mae !== null && ` (mean absolute error ${bt.scored.mae.toFixed(1)} ${bt.unit} for this single origin)`}. {bt.note}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
