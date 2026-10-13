"use client";

import { Icon } from "@/components/ui/Icon";
import { btnSecondary } from "@/components/ui/states";
import { useWeather } from "@/lib/weather/context";
import { formatAge, formatIST } from "@/lib/weather/time";
import type { PointForecast } from "@/lib/weather/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

export function SourcePanel({ data }: { data: PointForecast }) {
  const { refresh } = useWeather();
  const s = data.source;
  const stale = s.freshness === "stale";
  const missing = data.unavailable;

  return (
    <section aria-label="Data source" className="mb-5 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">Data source</h2>
        <div className="flex items-center gap-3">
          <span className={`inline-flex items-center gap-2 text-sm ${stale ? "text-warn" : ""}`}>
            <span className={`h-2 w-2 rounded-full ${stale ? "bg-warn" : "bg-accent"}`} aria-hidden="true" />
            {stale ? "Stale" : "Fresh"}
          </span>
          <button onClick={refresh} className={btnSecondary}>
            <Icon name="refresh" className="h-4 w-4" />
            Reload
          </button>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
        <Row label="Provider">
          <a href={s.attribution.url} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">
            {s.attribution.provider}
          </a>{" "}
          <span className="text-muted">· {s.attribution.license}</span>
        </Row>
        <Row label="Retrieved">
          {formatIST(s.retrieved_at)} <span className="text-muted">({formatAge(s.cache_age_s)})</span>
        </Row>
        <Row label="Provider data time">{s.latest_source_time ? formatIST(s.latest_source_time) : "Not reported"}</Row>
        <Row label="Forecast horizon">
          {data.coverage.hours} h, {formatIST(data.times[0])} → {formatIST(data.times[data.times.length - 1])}
        </Row>
        <Row label="Model grid cell">
          {data.location.grid_lat.toFixed(3)}°N, {data.location.grid_lon.toFixed(3)}°E
          {data.location.elevation_m !== null && ` · ${data.location.elevation_m} m`}
        </Row>
      </dl>

      <p className="mt-3 text-xs text-muted">
        Values are weather-model output for the grid cell containing the location, not station measurements.{" "}
        {s.attribution.text}.
      </p>
      {missing.length > 0 && (
        <p className="mt-2 text-sm text-warn" role="status">
          Not provided by the source for this location: {missing.join(", ")}.
        </p>
      )}
      {s.served_from_cache_after_failure && (
        <p className="mt-2 text-sm text-warn" role="status">
          The provider could not be reached; showing the most recent successful response.
        </p>
      )}
      {s.warnings.length > 0 && (
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer">Data-quality notes ({s.warnings.length})</summary>
          <ul className="mt-1 list-disc pl-5">
            {s.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
