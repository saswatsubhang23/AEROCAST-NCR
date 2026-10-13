"use client";

import { useMemo } from "react";
import { ChartContainer } from "@/components/ui/ChartContainer";
import { UnavailableState } from "@/components/ui/states";
import { EChart } from "@/components/charts/EChart";
import { buildChartOption, COLORS, type ChartSeries, type ChartSpec } from "@/lib/weather/chartOptions";
import { useWeather } from "@/lib/weather/context";
import { formatISTAxis } from "@/lib/weather/time";
import type { PointForecast } from "@/lib/weather/types";

const pick = (d: PointForecast, key: string) => d.series[key] ?? null;

function Chart({
  title, caption, spec, ariaLabel, missing,
}: { title: string; caption: string; spec: Omit<ChartSpec, "labels" | "selected">; ariaLabel: string; missing: string[] }) {
  const { point, selected, setSelected } = useWeather();
  const labels = useMemo(() => (point.status === "ready" ? point.data.times.map(formatISTAxis) : []), [point]);
  const option = useMemo(() => buildChartOption({ ...spec, labels, selected }), [spec, labels, selected]);
  return (
    <ChartContainer title={title} caption={caption}>
      {missing.length > 0 && spec.series.length === 0 ? (
        <UnavailableState title="Not provided by the source" reason={`Unavailable: ${missing.join(", ")}.`} />
      ) : (
        <EChart option={option} ariaLabel={ariaLabel} onSelectIndex={setSelected} />
      )}
    </ChartContainer>
  );
}

type SeriesDef = Omit<ChartSeries, "data"> & { key: string };

/** Builds chart series from the forecast, silently omitting variables the source did not provide. */
function series(d: PointForecast, defs: SeriesDef[]): ChartSeries[] {
  return defs.flatMap(({ key, ...rest }) => {
    const data = pick(d, key);
    return data ? [{ ...rest, data }] : [];
  });
}

export function TemperatureHumidityChart({ data }: { data: PointForecast }) {
  const spec = useMemo(() => ({
    series: series(data, [
      { key: "temperature_2m", name: "Temperature", unit: "°C", color: COLORS.cyan, kind: "line", axis: 0 },
      { key: "dew_point_2m", name: "Dew point", unit: "°C", color: COLORS.pale, kind: "line", axis: 0, dashed: true },
      { key: "relative_humidity_2m", name: "Relative humidity", unit: "%", color: COLORS.blue, kind: "line", axis: 1 },
    ]),
    axes: [{ name: "°C" }, { name: "%", min: 0, max: 100 }],
  }), [data]);
  return <Chart title="Temperature, dew point and humidity" caption="Hourly, IST. Click the chart to move the timeline." spec={spec} ariaLabel="Temperature, dew point and relative humidity over the forecast horizon" missing={data.unavailable} />;
}

export function WindChart({ data }: { data: PointForecast }) {
  const spec = useMemo(() => {
    const speed = pick(data, "wind_speed_10m");
    const dir = pick(data, "wind_direction_10m");
    return {
      series: series(data, [{ key: "wind_speed_10m", name: "Wind speed", unit: "km/h", color: COLORS.cyan, kind: "area" }]),
      axes: [{ name: "km/h", min: 0 }],
      arrows: speed && dir ? { from: dir, speed, every: 3 } : undefined,
    };
  }, [data]);
  return <Chart title="Wind" caption="Speed at 10 m. Arrows show where the wind is blowing toward, every 3 h." spec={spec} ariaLabel="Wind speed and direction over the forecast horizon" missing={data.unavailable} />;
}

export function RainfallChart({ data }: { data: PointForecast }) {
  const spec = useMemo(() => ({
    series: series(data, [{ key: "precipitation", name: "Precipitation", unit: "mm", color: COLORS.blue, kind: "bar" }]),
    axes: [{ name: "mm", min: 0 }],
  }), [data]);
  const values = data.series.precipitation;
  const known = values?.filter((v): v is number => v !== null) ?? [];
  const total = known.reduce((a, b) => a + b, 0);
  const caption = values
    ? `Hourly. Total over the horizon: ${total.toFixed(1)} mm${known.length < values.length ? ` (${values.length - known.length} hours missing)` : ""}.`
    : "Hourly.";
  return <Chart title="Rainfall" caption={caption} spec={spec} ariaLabel="Hourly precipitation over the forecast horizon" missing={data.unavailable} />;
}

export function PressureCloudChart({ data }: { data: PointForecast }) {
  const spec = useMemo(() => ({
    series: series(data, [
      { key: "surface_pressure", name: "Surface pressure", unit: "hPa", color: COLORS.cyan, kind: "line", axis: 0 },
      { key: "cloud_cover", name: "Cloud cover", unit: "%", color: COLORS.muted, kind: "area", axis: 1 },
    ]),
    axes: [{ name: "hPa" }, { name: "%", min: 0, max: 100 }],
  }), [data]);
  return <Chart title="Pressure and cloud cover" caption="Hourly, IST." spec={spec} ariaLabel="Surface pressure and cloud cover over the forecast horizon" missing={data.unavailable} />;
}

export function BoundaryLayerChart({ data }: { data: PointForecast }) {
  const spec = useMemo(() => ({
    series: series(data, [{ key: "boundary_layer_height", name: "Boundary layer height", unit: "m", color: COLORS.cyan, kind: "area" }]),
    axes: [{ name: "m", min: 0 }],
  }), [data]);
  return <Chart title="Boundary layer height" caption="Hourly, IST. Higher values mean deeper mixing." spec={spec} ariaLabel="Boundary layer height over the forecast horizon" missing={data.unavailable} />;
}
