"use client";

import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { ChartContainer } from "@/components/ui/ChartContainer";
import { UnavailableState } from "@/components/ui/states";
import { labelOf, unitKey } from "@/lib/air/pollutants";
import type { HistoryResponse, SeriesInfo } from "@/lib/air/types";
import { buildChartOption, COLORS, type ChartSeries } from "@/lib/weather/chartOptions";
import { formatISTAxis } from "@/lib/weather/time";

const PALETTE = [COLORS.cyan, COLORS.blue, COLORS.pale, "#7dd3fc", "#818cf8", COLORS.muted];

function plot(history: HistoryResponse, series: SeriesInfo[], unit: string) {
  const labels = history.times.map(formatISTAxis);
  const chartSeries: ChartSeries[] = series.map((s, i) => ({
    name: s.station_name,
    unit,
    data: s.values,
    color: PALETTE[i % PALETTE.length],
    kind: "line",
    symbols: true,
  }));
  return buildChartOption({ labels, selected: -1, series: chartSeries, axes: [{ name: unit, min: 0 }] });
}

function coverageNote(s: SeriesInfo, hours: number) {
  return s.missing_hours === 0
    ? `All ${hours} hours observed.`
    : `${s.observed_hours} of ${hours} hours observed; ${s.missing_hours} missing (shown as gaps).`;
}

/** One station's hourly observations. Missing hours stay gaps; nothing is interpolated. */
export function HistoryChart({ history, stationId }: { history: HistoryResponse; stationId: number }) {
  const s = history.series.find((x) => x.station_id === stationId);
  const option = useMemo(() => (s && s.observed_hours > 0 ? plot(history, [s], s.unit ?? "") : null), [history, s]);
  if (!s) return null;
  return (
    <ChartContainer
      title={`${labelOf(history.pollutant)} at ${s.station_name}`}
      caption={`Hourly observations (hour-ending, IST), ${s.unit ?? ""}. ${coverageNote(s, history.times.length)}`}
    >
      {option ? (
        <EChart option={option} ariaLabel={`Hourly ${labelOf(history.pollutant)} at ${s.station_name}`} />
      ) : (
        <UnavailableState
          title="No observations in this window"
          reason={s.unit === null ? `${s.station_name} has no ${labelOf(history.pollutant)} sensor.` : "The source reported no hourly values for this period."}
        />
      )}
    </ChartContainer>
  );
}

/** Several stations on one axis. Stations reporting a different unit cannot share the axis and are listed instead. */
export function CompareChart({ history }: { history: HistoryResponse }) {
  const { shown, unit, skipped } = useMemo(() => {
    const withData = history.series.filter((s) => s.observed_hours > 0 && s.unit);
    const groups = new Map<string, SeriesInfo[]>();
    for (const s of withData) groups.set(unitKey(s.unit!), [...(groups.get(unitKey(s.unit!)) ?? []), s]);
    const main = [...groups.values()].sort((a, b) => b.length - a.length)[0] ?? [];
    return {
      shown: main,
      unit: main[0]?.unit ?? "",
      skipped: history.series.filter((s) => !main.includes(s)),
    };
  }, [history]);
  const option = useMemo(() => (shown.length ? plot(history, shown, unit) : null), [history, shown, unit]);

  return (
    <ChartContainer
      title={`${labelOf(history.pollutant)}: station comparison`}
      caption={`Same hourly grid for every station (IST). Tick a station in the table to add it; up to 6.`}
    >
      {option ? (
        <EChart option={option} ariaLabel={`Comparison of hourly ${labelOf(history.pollutant)} across stations`} />
      ) : (
        <UnavailableState title="Nothing to compare" reason="None of the selected stations reported this pollutant in the window." />
      )}
      {skipped.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-warn">
          {skipped.map((s) => (
            <li key={s.station_id}>
              {s.station_name}: not plotted ({s.unit === null ? "no sensor" : s.observed_hours === 0 ? "no observations in the window" : `reports ${s.unit}, a different unit`}).
            </li>
          ))}
        </ul>
      )}
    </ChartContainer>
  );
}
