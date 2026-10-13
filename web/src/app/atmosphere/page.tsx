"use client";

import { RegimePanel } from "@/components/twin/RegimePanel";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { FilterBar, SegmentedField } from "@/components/ui/FilterBar";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { CurrentConditions } from "@/components/weather/CurrentConditions";
import { PointGate } from "@/components/weather/PointGate";
import { RecentWeather } from "@/components/weather/RecentWeather";
import { Timeline } from "@/components/weather/Timeline";
import { VerticalProfile } from "@/components/weather/VerticalProfile";
import { BoundaryLayerChart } from "@/components/weather/WeatherCharts";
import { useLocation } from "@/lib/location";
import { useWindow, WINDOWS } from "@/lib/window";

export default function AtmospherePage() {
  const { location } = useLocation();
  const { hours, setHours } = useWindow();

  return (
    <>
      <PageHeader
        title="Atmospheric Conditions"
        description={`How the atmosphere mixes and ventilates pollutants over ${location.name}. Weather-model values, not measurements; all times are IST.`}
      />

      <Section title="Recent conditions" aside={<ProvenanceBadge kind="derived" detail="Indicators computed by arithmetic from weather-model values." />}>
        <FilterBar>
          <SegmentedField
            label="Time range (shared with Air Quality)"
            value={String(hours)}
            onChange={(v) => setHours(Number(v))}
            options={WINDOWS.map((w) => ({ value: String(w.hours), label: w.label }))}
          />
        </FilterBar>
        <RecentWeather
          lat={location.lat}
          lon={location.lon}
          hours={hours}
          place={location.name}
          charts={["wind", "blh", "rain", "temp"]}
          showIndicators
        />
        <p className="mt-3 text-xs text-muted">
          The two derived indicators are plain arithmetic on model values, with no thresholds or risk labels. They do not
          show whether a temperature inversion exists; that needs vertical temperature data (see Vertical structure below).
        </p>
      </Section>

      <PointGate>
        {(data) => (
          <>
            <Section title="Forecast" aside={<ProvenanceBadge kind="weather_forecast" />}>
              <Timeline data={data} />
              <CurrentConditions data={data} keys={["boundary_layer_height", "wind_speed_10m", "cloud_cover", "surface_pressure"]} />
              <div className="mt-4">
                <BoundaryLayerChart data={data} />
              </div>
            </Section>
            <Section title="Vertical structure">
              <VerticalProfile />
            </Section>
          </>
        )}
      </PointGate>
      <Section title="Weather regimes and PM2.5 (learned from stored history)">
        <RegimePanel time={null} stationId={null} />
      </Section>
    </>
  );
}
