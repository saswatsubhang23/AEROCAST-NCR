"use client";

import { useMemo, useState } from "react";
import { EChart } from "@/components/charts/EChart";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useLocation } from "@/lib/location";
import { getJson } from "@/lib/weather/api";
import { useResource } from "@/lib/weather/context";
import { labelOf } from "@/lib/air/pollutants";
import type { PollutantKey } from "@/lib/air/types";

const PAST_HOURS = 24;

type ModelAir = {
  source: string;
  times_utc: string[];
  pollutants: Record<string, { unit: string; values: (number | null)[] }>;
  notes: string;
};

/** Modelled concentrations from the Open-Meteo air-quality model: past 24 h and the next 48 h, plainly labelled as not measured. */
export function ModelAirPanel() {
  const { location } = useLocation();
  const [pollutant, setPollutant] = useState<PollutantKey>("pm25");
  const res = useResource(`model-air-${location.id}`, 0, (s) =>
    getJson<ModelAir>(`/api/air/model-forecast?lat=${location.lat.toFixed(4)}&lon=${location.lon.toFixed(4)}&past_hours=${PAST_HOURS}&forecast_hours=48`, s),
  );
  const data = res.status === "ready" ? res.data : null;
  const series = data?.pollutants[pollutant];
  const option = useMemo(() => {
    if (!data || !series) return null;
    const labels = data.times_utc.map((t) => new Date(t).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }));
    const nowIdx = PAST_HOURS; // the response holds PAST_HOURS past hours, then the current hour onwards
    return {
      grid: { left: 52, right: 14, top: 16, bottom: 36 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#9db0cc" }, axisLine: { lineStyle: { color: "#22314d" } } },
      yAxis: { type: "value", name: series.unit, nameTextStyle: { color: "#9db0cc" }, axisLabel: { color: "#9db0cc" }, splitLine: { lineStyle: { color: "#16233a" } } },
      series: [{
        type: "line", data: series.values, showSymbol: false, color: "#79dfd0", connectNulls: false,
        markLine: nowIdx > 0 ? { symbol: "none", label: { formatter: "now", color: "#9db0cc" }, lineStyle: { color: "#9db0cc", type: "dashed" }, data: [{ xAxis: nowIdx }] } : undefined,
      }],
    };
  }, [data, series]);

  if (res.status === "loading") return <LoadingState label="Loading modelled concentrations" />;
  if (res.status === "error") return <ErrorState title="Modelled air quality is unavailable" message={res.error.message} />;
  return (
    <div className="space-y-3 text-sm">
      <label className="flex items-center gap-1.5 text-xs text-muted">
        Pollutant
        <select value={pollutant} onChange={(e) => setPollutant(e.target.value as PollutantKey)} className="h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
          {Object.keys(res.data.pollutants).map((p) => (
            <option key={p} value={p}>{labelOf(p as PollutantKey)}</option>
          ))}
        </select>
      </label>
      {option && <EChart option={option} height={240} ariaLabel={`Modelled ${labelOf(pollutant)} concentration for ${location.name}, past 24 hours and next 48 hours`} />}
      <p className="text-xs text-muted">{res.data.source}. {res.data.notes}</p>
    </div>
  );
}
