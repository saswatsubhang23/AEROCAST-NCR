"use client";

import { Metric } from "@/components/ui/Metric";
import { useWeather, valueAt } from "@/lib/weather/context";
import { compass } from "@/lib/weather/wind";
import type { PointForecast } from "@/lib/weather/types";

const DEFINITIONS: Record<string, string> = {
  dew_point_2m: "Temperature at which the air would become saturated. Close to the air temperature means humid, muggy air.",
  boundary_layer_height: "Depth of the lowest atmospheric layer in which surface air mixes. Shallow layers trap pollutants near the ground.",
  precipitation: "Total liquid-equivalent precipitation in the hour ending at this time.",
  wind_direction_10m: "Direction the wind blows from, in degrees clockwise from north.",
};

const SHOWN = [
  "temperature_2m", "relative_humidity_2m", "dew_point_2m", "wind_speed_10m", "wind_direction_10m",
  "precipitation", "surface_pressure", "cloud_cover", "boundary_layer_height",
];
const LABELS: Record<string, [string, string]> = {
  temperature_2m: ["Temperature", "°C"],
  relative_humidity_2m: ["Relative humidity", "%"],
  dew_point_2m: ["Dew point", "°C"],
  wind_speed_10m: ["Wind speed", "km/h"],
  wind_direction_10m: ["Wind direction", ""],
  precipitation: ["Precipitation", "mm"],
  surface_pressure: ["Surface pressure", "hPa"],
  cloud_cover: ["Cloud cover", "%"],
  boundary_layer_height: ["Boundary layer height", "m"],
};

/** Metrics for the selected hour. A metric with no value shows "No data" rather than a number. */
export function CurrentConditions({ data, keys = SHOWN }: { data: PointForecast; keys?: string[] }) {
  const { selected } = useWeather();
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
      {keys.map((k) => {
        const [label, unit] = LABELS[k];
        const v = valueAt(data.series, k, selected);
        const shown = v === null ? null : k === "wind_direction_10m" ? `${Math.round(v)}° ${compass(v)}` : v;
        return <Metric key={k} label={label} value={shown} unit={k === "wind_direction_10m" ? undefined : unit} definition={DEFINITIONS[k]} />;
      })}
    </div>
  );
}
