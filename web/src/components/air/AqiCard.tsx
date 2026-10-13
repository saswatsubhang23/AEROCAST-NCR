"use client";

import { useState } from "react";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fetchAqi } from "@/lib/air/api";
import { categoryColor, labelOf } from "@/lib/air/pollutants";
import type { AqiPollutant, Station } from "@/lib/air/types";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

const COLUMNS: Column<AqiPollutant>[] = [
  { key: "p", header: "Pollutant", render: (r) => <span className={r.used ? "" : "text-muted"}>{labelOf(r.pollutant)}</span> },
  {
    key: "avg",
    header: "Average used",
    render: (r) =>
      r.average === null ? <span className="text-muted">—</span> : (
        <span className="font-mono tabular-nums">
          {r.average} <span className="text-muted">{r.unit} · {r.averaging}</span>
        </span>
      ),
  },
  { key: "hours", header: "Valid hours", render: (r) => r.valid_hours },
  {
    key: "sub",
    header: "Sub-index",
    render: (r) =>
      r.used ? (
        <span>
          <span className="font-mono tabular-nums">{r.lower_bound_only ? `≥ ${r.sub_index}` : r.sub_index}</span>
          <span className="ml-2 inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="h-2 w-2 rounded-full" style={{ background: categoryColor(r.category) }} aria-hidden="true" />
            {r.category}
          </span>
          {r.note && <span className="block text-xs text-muted">{r.note}</span>}
        </span>
      ) : (
        <span className="text-xs text-muted">Not used: {r.reason}</span>
      ),
  },
];

/** AQI for one station, computed on the server with the CPCB method. It is always labelled as computed. */
export function AqiCard({ station }: { station: Station }) {
  const [version, setVersion] = useState(0);
  const res = useResource(`aqi:${station.id}`, version, (s) => fetchAqi(station.id, s));

  if (res.status === "loading") return <LoadingState label="Computing AQI from hourly observations" />;
  if (res.status === "error")
    return <ErrorState title="AQI could not be computed" message={res.error.message} onRetry={() => setVersion((v) => v + 1)} />;

  const a = res.data;
  const available = a.status === "available" && a.aqi !== null;
  return (
    <section aria-label="Air Quality Index" className="rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Air Quality Index (computed)</h3>
          {available ? (
            <p className="mt-2 flex items-baseline gap-3">
              <span className="font-mono text-4xl font-semibold tabular-nums">
                {a.lower_bound_only ? `≥ ${a.aqi}` : a.aqi}
              </span>
              <span className="inline-flex items-center gap-2 text-sm">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(a.category) }} aria-hidden="true" />
                {a.category}
              </span>
            </p>
          ) : (
            <p className="mt-2 text-lg font-medium">AQI not available</p>
          )}
          <p className="mt-1 max-w-xl text-sm text-muted">
            {available
              ? `Driven by ${labelOf(a.dominant ?? "")}. `
              : `${a.reason ?? "Insufficient data."} `}
            Pollutant concentrations below are measurements; this index is a separate calculated value.
          </p>
        </div>
        <div className="text-right text-xs text-muted">
          {a.as_of && (
            <p className={a.stale ? "text-warn" : ""}>
              As of {formatIST(a.as_of)}
              {a.stale && " · stale"}
            </p>
          )}
        </div>
      </div>

      <p className="mt-3 text-xs text-muted">{a.label}</p>

      {a.pollutants.length > 0 && (
        <div className="mt-3">
          <DataTable
            caption="Sub-index for each pollutant"
            columns={COLUMNS}
            rows={a.pollutants}
            rowKey={(r) => r.pollutant}
            empty={{ title: "No pollutants", message: "This station reported no usable pollutant data." }}
          />
        </div>
      )}
      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer">How this is calculated, and assumptions</summary>
        <ul className="mt-1 list-disc pl-5">
          <li>
            Method: CPCB National AQI. Each pollutant gets a sub-index from its 24-hour average (8-hour for CO and O₃);
            the AQI is the worst sub-index. At least 3 pollutants are required, including PM2.5 or PM10.
          </li>
          {a.assumptions.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
