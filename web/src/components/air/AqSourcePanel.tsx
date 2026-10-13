"use client";

import { Icon } from "@/components/ui/Icon";
import { btnSecondary } from "@/components/ui/states";
import type { StationsResponse } from "@/lib/air/types";
import { formatAge, formatIST } from "@/lib/weather/time";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

export function AqSourcePanel({ data, onReload }: { data: StationsResponse; onReload: () => void }) {
  const { source, stations, warnings } = data;
  const times = stations.flatMap((s) => Object.values(s.latest).map((r) => r.observed_at));
  const newest = times.length ? times.reduce((a, b) => (a > b ? a : b)) : null;
  const readings = stations.flatMap((s) => Object.values(s.latest));
  const stale = readings.filter((r) => r.stale).length;

  return (
    <section aria-label="Data source" className="mb-5 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">Data source</h2>
        <div className="flex items-center gap-3">
          {readings.length > 0 && (
            <span className={`inline-flex items-center gap-2 text-sm ${stale ? "text-warn" : ""}`}>
              <span className={`h-2 w-2 rounded-full ${stale ? "bg-warn" : "bg-accent"}`} aria-hidden="true" />
              {stale ? `${stale} of ${readings.length} readings stale` : "All readings recent"}
            </span>
          )}
          <button onClick={onReload} className={btnSecondary}>
            <Icon name="refresh" className="h-4 w-4" />
            Reload
          </button>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
        <Row label="Provider">
          <a href={source.url} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">
            {source.provider}
          </a>
          <span className="text-muted"> · {source.reference_only ? "reference monitors only" : "all sensor types"}</span>
        </Row>
        <Row label="Retrieved">
          {formatIST(source.retrieved_at)} <span className="text-muted">({formatAge(source.cache_age_s)})</span>
        </Row>
        <Row label="Newest observation">{newest ? formatIST(newest) : "None"}</Row>
        <Row label="Stations">{stations.length}</Row>
      </dl>
      <p className="mt-3 text-xs text-muted">{source.attribution}</p>
      {warnings.length > 0 && (
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer">Station-list notes ({warnings.length})</summary>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      <details className="mt-2 text-xs text-muted">
        <summary className="cursor-pointer">Limitations of this data</summary>
        <ul className="mt-1 list-disc pl-5">
          {source.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
