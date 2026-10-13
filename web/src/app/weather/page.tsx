"use client";

import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { CurrentConditions } from "@/components/weather/CurrentConditions";
import { PointGate } from "@/components/weather/PointGate";
import { SourcePanel } from "@/components/weather/SourcePanel";
import { Timeline } from "@/components/weather/Timeline";
import { WeatherMap } from "@/components/weather/WeatherMap";
import {
  PressureCloudChart,
  RainfallChart,
  TemperatureHumidityChart,
  WindChart,
} from "@/components/weather/WeatherCharts";
import { useLocation } from "@/lib/location";
import { formatIST } from "@/lib/weather/time";
import { useWeather } from "@/lib/weather/context";

export default function WeatherPage() {
  const { location } = useLocation();
  const { selected } = useWeather();

  return (
    <>
      <PageHeader
        title="Weather"
        description={`Hourly weather-model forecast for ${location.name}. All times are IST.`}
      />
      <PointGate>
        {(data) => (
          <>
            <SourcePanel data={data} />
            <Timeline data={data} />

            <Section title={`Conditions at ${formatIST(data.times[selected])}`}>
              <CurrentConditions data={data} />
            </Section>

            <Section title="Map" aside={<ProvenanceBadge kind="weather_forecast" />}>
              <WeatherMap />
            </Section>

            <Section title="Forecast charts" aside={<ProvenanceBadge kind="weather_forecast" />}>
              <div className="grid gap-4 lg:grid-cols-2">
                <TemperatureHumidityChart data={data} />
                <WindChart data={data} />
                <RainfallChart data={data} />
                <PressureCloudChart data={data} />
              </div>
            </Section>
          </>
        )}
      </PointGate>
    </>
  );
}
