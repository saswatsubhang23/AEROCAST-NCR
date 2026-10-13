"use client";

import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { ChartContainer } from "@/components/ui/ChartContainer";
import { Metric } from "@/components/ui/Metric";
import { ErrorState, LoadingState, UnavailableState } from "@/components/ui/states";
import { fetchRecent, type RecentWeather as Recent } from "@/lib/air/api";
import { buildChartOption, COLORS, type ChartSeries } from "@/lib/weather/chartOptions";
import { useResource } from "@/lib/weather/context";
import { formatISTAxis } from "@/lib/weather/time";

export type RecentChart = "wind" | "blh" | "rain" | "temp";

function Frame({
  title, caption, children,
}: { title: string; caption: string; children: React.ReactNode }) {
  return <ChartContainer title={title} caption={caption}>{children}</ChartContainer>;
}

function build(d: Recent, which: RecentChart) {
  const labels = d.times.map(formatISTAxis);
  const get = (k: string) => d.series[k] ?? null;
  const line = (key: string, name: string, unit: string, color: string, extra: Partial<ChartSeries> = {}) => {
    const data = get(key);
    return data ? [{ name, unit, data, color, kind: "line" as const, ...extra }] : [];
  };
  switch (which) {
    case "wind": {
      const speed = get("wind_speed_10m");
      const dir = get("wind_direction_10m");
      return buildChartOption({
        labels, selected: -1,
        series: line("wind_speed_10m", "Wind speed", "km/h", COLORS.cyan, { kind: "area" }),
        axes: [{ name: "km/h", min: 0 }],
        arrows: speed && dir ? { from: dir, speed, every: Math.max(3, Math.round(labels.length / 24)) } : undefined,
      });
    }
    case "blh": {
      const vi = d.derived.ventilation_index;
      return buildChartOption({
        labels, selected: -1,
        series: [
          ...line("boundary_layer_height", "Boundary layer height", "m", COLORS.cyan, { kind: "area" }),
          ...(vi ? [{ name: "Ventilation index (derived)", unit: vi.unit, data: vi.values, color: COLORS.pale, kind: "line" as const, dashed: true, axis: 1 }] : []),
        ],
        axes: [{ name: "m", min: 0 }, { name: "m²/s", min: 0 }],
      });
    }
    case "rain":
      return buildChartOption({
        labels, selected: -1,
        series: [{ name: "Precipitation", unit: "mm", data: get("precipitation") ?? [], color: COLORS.blue, kind: "bar" }],
        axes: [{ name: "mm", min: 0 }],
      });
    case "temp":
      return buildChartOption({
        labels, selected: -1,
        series: [
          ...line("temperature_2m", "Temperature", "°C", COLORS.cyan),
          ...line("relative_humidity_2m", "Relative humidity", "%", COLORS.blue, { axis: 1 }),
        ],
        axes: [{ name: "°C" }, { name: "%", min: 0, max: 100 }],
      });
  }
}

const META: Record<RecentChart, { title: string; caption: string; needs: string[]; label: string }> = {
  wind: { title: "Wind", caption: "Speed at 10 m; arrows show where the wind blows toward.", needs: ["wind_speed_10m"], label: "Wind speed and direction" },
  blh: {
    title: "Boundary layer height and ventilation index",
    caption: "Model values, plus the derived ventilation index (boundary layer height × wind speed; not a measurement).",
    needs: ["boundary_layer_height"], label: "Boundary layer height and ventilation index",
  },
  rain: { title: "Rainfall", caption: "Hourly precipitation.", needs: ["precipitation"], label: "Hourly precipitation" },
  temp: { title: "Temperature and humidity", caption: "Hourly.", needs: ["temperature_2m"], label: "Temperature and relative humidity" },
};

/** Past-window weather for the same hourly grid as the air-quality charts. All values are weather-model output. */
export function RecentWeather({
  lat, lon, hours, place, charts, showIndicators = false,
}: { lat: number; lon: number; hours: number; place: string; charts: RecentChart[]; showIndicators?: boolean }) {
  const res = useResource(`recent:${lat.toFixed(3)}:${lon.toFixed(3)}:${hours}`, 0, (s) => fetchRecent(lat, lon, hours, s));
  const data = res.status === "ready" ? res.data : null;
  const options = useMemo(
    () => (data ? Object.fromEntries(charts.map((c) => [c, build(data, c)])) : {}),
    [data, charts],
  );

  if (res.status === "loading") return <LoadingState label="Loading meteorological context" />;
  if (res.status === "error") return <ErrorState title="Weather context is unavailable" message={res.error.message} />;
  const d = res.data;

  const hsr = d.derived.hours_since_rain?.values;
  const lastHsr = hsr ? hsr[hsr.length - 1] : null;
  const vi = d.derived.ventilation_index?.values;
  const lastVi = vi ? vi[vi.length - 1] : null;

  return (
    <div>
      <p className="mb-3 text-xs text-muted">
        Weather-model values for the grid cell at {place} ({d.location.grid_lat.toFixed(2)}°N, {d.location.grid_lon.toFixed(2)}°E),
        {" "}{d.coverage.hours} hours ending {formatISTAxis(d.times[d.times.length - 1])} IST. {d.source.attribution.text}.
        {d.unavailable.length > 0 && ` Not provided: ${d.unavailable.join(", ")}.`}
      </p>
      {showIndicators && (
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Metric
            label="Ventilation index (derived)"
            value={lastVi ?? null}
            unit="m²/s"
            definition={d.derived.ventilation_index?.definition ?? "Needs boundary layer height and wind speed, which the source did not provide."}
            note="Latest hour. A descriptive quantity, not a measurement or a class."
          />
          <Metric
            label="Hours since rain (derived)"
            value={lastHsr ?? null}
            unit="h"
            definition={d.derived.hours_since_rain?.definition ?? "Needs precipitation, which the source did not provide."}
            note={lastHsr === null ? "No rain seen in this window, or a data gap hides it." : "Counted within the window."}
          />
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {charts.map((c) => {
          const m = META[c];
          const present = m.needs.every((k) => d.series[k]);
          return (
            <Frame key={c} title={m.title} caption={m.caption}>
              {present ? (
                <EChart option={options[c]} ariaLabel={m.label} />
              ) : (
                <UnavailableState title="Not provided by the source" reason={`${m.needs.join(", ")} is unavailable for this location.`} />
              )}
            </Frame>
          );
        })}
      </div>
    </div>
  );
}
