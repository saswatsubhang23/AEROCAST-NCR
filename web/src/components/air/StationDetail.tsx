"use client";

import { Metric } from "@/components/ui/Metric";
import { Section } from "@/components/ui/PageHeader";
import { csvUrl } from "@/lib/air/api";
import { formatAgeShort, labelOf, POLLUTANTS } from "@/lib/air/pollutants";
import type { PollutantKey, Station } from "@/lib/air/types";
import { formatIST } from "@/lib/weather/time";
import { AqiCard } from "./AqiCard";

const link =
  "inline-flex h-9 items-center gap-2 rounded-md border border-line bg-surface-2 px-3.5 text-sm font-medium text-fg transition-colors hover:border-accent/60";

export function StationDetail({ station, pollutant, hours }: { station: Station; pollutant: PollutantKey; hours: number }) {
  return (
    <Section
      title={`Station: ${station.name}`}
      aside={
        station.pollutants[pollutant] ? (
          <a href={csvUrl(station.id, pollutant, hours)} download className={link}>
            Export {labelOf(pollutant)} CSV ({hours} h)
          </a>
        ) : null
      }
    >
      <p className="mb-3 text-xs text-muted">
        {station.provider ?? "Unknown provider"}
        {station.owner && ` · owner ${station.owner}`}
        {` · ${station.lat.toFixed(4)}°N, ${station.lon.toFixed(4)}°E`}
        {station.license && ` · ${station.license}`}
        {station.is_reference_monitor ? " · reference monitor" : ""}
      </p>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {POLLUTANTS.map((p) => {
          const r = station.latest[p.key];
          const hasSensor = Boolean(station.pollutants[p.key]);
          return (
            <Metric
              key={p.key}
              label={p.label}
              value={r ? r.value : null}
              unit={r?.unit}
              note={
                r
                  ? `${formatIST(r.observed_at)} · ${formatAgeShort(r.age_s)}${r.stale ? " · stale" : ""}`
                  : hasSensor
                    ? "No recent reading"
                    : "No sensor at this station"
              }
            />
          );
        })}
      </div>
      <AqiCard key={station.id} station={station} />
    </Section>
  );
}
