"use client";

import Link from "next/link";
import { FileSpreadsheet } from "lucide-react";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { useCallback, useState } from "react";
import { AlertsPanel } from "@/components/air/AlertsPanel";
import { ForecastPanel } from "@/components/air/ForecastPanel";
import { ModelAirPanel } from "@/components/air/ModelAirPanel";
import { AqSourcePanel } from "@/components/air/AqSourcePanel";
import { CompareChart, HistoryChart } from "@/components/air/ObservationCharts";
import { SetupGuide } from "@/components/air/SetupGuide";
import { StationDetail } from "@/components/air/StationDetail";
import { StationMap } from "@/components/air/StationMap";
import { StationTable } from "@/components/air/StationTable";
import { FilterBar, SegmentedField, SelectField } from "@/components/ui/FilterBar";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { RecentWeather } from "@/components/weather/RecentWeather";
import { fetchHistory, fetchStations } from "@/lib/air/api";
import { labelOf, POLLUTANTS } from "@/lib/air/pollutants";
import type { PollutantKey, StationsResponse } from "@/lib/air/types";
import { useResource } from "@/lib/weather/context";
import { useWindow, WINDOWS } from "@/lib/window";

const MAX_EXTRA = 5;

export default function AirQualityPage() {
  const [version, setVersion] = useState(0);
  const stations = useResource("aq-stations", version, (s) => fetchStations(s));
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return (
    <>
      <PageHeader
        title="Air Quality"
        description="Observations from monitoring stations across Delhi-NCR. Concentrations are measurements; the AQI shown for a station is a separate calculated value."
        actions={
          <Link
            href="/air-quality/batch"
            className="inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/20 transition-colors shadow-sm"
          >
            <FileSpreadsheet className="h-3.5 w-3.5" />
            Batch CSV Coordinates
          </Link>
        }
      />
      <Section title="Modelled pollution, next 48 h" aside={<ProvenanceBadge kind="atmospheric_model" detail="Atmospheric-chemistry model output on a coarse grid; not station measurements." />}>
        <ModelAirPanel />
      </Section>
      {stations.status === "loading" && (
        <LoadingState label="Loading stations and their latest readings (the first load can take up to a minute)" />
      )}
      {stations.status === "error" &&
        (stations.error.code === "not_configured" || stations.error.code === "upstream_auth" ? (
          <SetupGuide reasonCode={stations.error.code} />
        ) : (
          <ErrorState title="Air-quality data is unavailable" message={stations.error.message} onRetry={reload} />
        ))}
      {stations.status === "ready" &&
        (stations.data.stations.length === 0 ? (
          <EmptyState
            title="No active stations"
            message="The source lists no active monitoring stations for Delhi-NCR with PM2.5, PM10, NO₂, SO₂, CO or O₃ sensors."
          />
        ) : (
          <Content data={stations.data} onReload={reload} />
        ))}
    </>
  );
}

function Content({ data, onReload }: { data: StationsResponse; onReload: () => void }) {
  const { hours, setHours } = useWindow();
  const [pollutant, setPollutant] = useState<PollutantKey>("pm25");
  const [pickedId, setPickedId] = useState<number | null>(null);
  const [extra, setExtra] = useState<number[]>([]);

  // Default to a station that actually has a reading for the chosen pollutant.
  const station =
    data.stations.find((s) => s.id === pickedId) ??
    data.stations.find((s) => s.latest[pollutant]) ??
    data.stations[0];
  const extraIds = extra.filter((id) => id !== station.id && data.stations.some((s) => s.id === id));
  const ids = [station.id, ...extraIds];

  const history = useResource(`aq-history:${ids.join(",")}:${pollutant}:${hours}`, 0, (s) =>
    fetchHistory(ids, pollutant, hours, s),
  );

  const toggleCompare = useCallback((id: number) => {
    setExtra((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : cur.length < MAX_EXTRA ? [...cur, id] : cur));
  }, []);

  return (
    <>
      <AqSourcePanel data={data} onReload={onReload} />
      <FilterBar>
        <SelectField
          label="Pollutant"
          value={pollutant}
          onChange={(v) => setPollutant(v as PollutantKey)}
          options={POLLUTANTS.map((p) => ({ value: p.key, label: p.label }))}
        />
        <SegmentedField
          label="Time range"
          value={String(hours)}
          onChange={(v) => setHours(Number(v))}
          options={WINDOWS.map((w) => ({ value: String(w.hours), label: w.label }))}
        />
      </FilterBar>

      <Section title="Monitoring stations" aside={<ProvenanceBadge kind="observed" detail="Latest reported value per station; readings older than 3 h are marked stale." />}>
        <StationMap stations={data.stations} pollutant={pollutant} selectedId={station.id} onSelect={setPickedId} />
        <div className="mt-4">
          <StationTable
            stations={data.stations}
            pollutant={pollutant}
            selectedId={station.id}
            compareIds={extraIds}
            onSelect={setPickedId}
            onToggleCompare={toggleCompare}
          />
        </div>
      </Section>

      <StationDetail station={station} pollutant={pollutant} hours={hours} />

      <Section title={`${labelOf(pollutant)} observations, past ${hours} h`} aside={<ProvenanceBadge kind="observed" />}>
        {history.status === "loading" && <LoadingState label="Loading hourly observations" />}
        {history.status === "error" && <ErrorState title="Observation history is unavailable" message={history.error.message} />}
        {history.status === "ready" && (
          <div className="space-y-4">
            <HistoryChart history={history.data} stationId={station.id} />
            {extraIds.length > 0 && <CompareChart history={history.data} />}
          </div>
        )}
      </Section>

      <Section title="Alerts on observed values">
        <AlertsPanel />
      </Section>

      <Section title="Pollution forecast" aside={<ProvenanceBadge kind="model_forecast" detail="Shown only when a forecasting model or service is configured and has fresh inputs." />}>
        <ForecastPanel />
      </Section>

      <Section title={`Meteorological context, same ${hours} h window`} aside={<ProvenanceBadge kind="weather_forecast" detail="Weather-model values for the grid cell, not station measurements." />}>
        <RecentWeather
          lat={station.lat}
          lon={station.lon}
          hours={hours}
          place={station.name}
          charts={["wind", "blh", "rain"]}
        />
      </Section>
    </>
  );
}
