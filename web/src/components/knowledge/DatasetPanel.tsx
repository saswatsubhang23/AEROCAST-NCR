"use client";

import { useState } from "react";
import { ErrorState, LoadingState, btnPrimary } from "@/components/ui/states";
import { fetchProfile, fetchRelationship } from "@/lib/kb/api";
import type { KbDocument, Relationship } from "@/lib/kb/types";
import { useResource } from "@/lib/weather/context";

const POLLUTANTS = [
  { key: "pm25", label: "PM2.5" },
  { key: "pm10", label: "PM10" },
  { key: "no2", label: "NO₂" },
  { key: "so2", label: "SO₂" },
  { key: "o3", label: "O₃" },
  { key: "co", label: "CO" },
];

const fmt = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "n/a" : v.toFixed(digits));

function Tags({ doc }: { doc: KbDocument }) {
  const meta = doc.meta;
  if (!meta) return null;
  const groups: [string, string[]][] = [
    ["Pollutants", meta.pollutants ?? []],
    ["Places", meta.places ?? []],
    ["Topics", meta.topics ?? []],
  ];
  const shown = groups.filter(([, v]) => v.length > 0);
  if (shown.length === 0) return null;
  return (
    <section aria-label="Research tags">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">What it mentions</h3>
      <dl className="space-y-1 text-xs">
        {shown.map(([label, values]) => (
          <div key={label} className="flex flex-wrap items-center gap-1.5">
            <dt className="w-20 text-muted">{label}</dt>
            {values.map((v) => (
              <dd key={v} className="rounded-full border border-line bg-surface-2 px-2 py-0.5">{v}</dd>
            ))}
          </div>
        ))}
      </dl>
      <p className="mt-1 text-xs text-muted">Found by matching words in the text; a tag says the word appears, not that the document is authoritative on it.</p>
    </section>
  );
}

function RelationshipResult({ r }: { r: Relationship }) {
  const h = r.heldout_check;
  return (
    <div className="mt-3 space-y-3 text-xs" aria-live="polite">
      <p className="text-muted">
        {r.column} against observed {POLLUTANTS.find((p) => p.key === r.pollutant)?.label ?? r.pollutant}
        {r.zone ? ` in ${r.zone}` : " across all stations"} · {r.resolution} values · {r.overlap_start} to {r.overlap_end}
      </p>
      <table className="w-full text-left">
        <caption className="mb-1 text-left font-medium">Correlation by lag (the series leads pollution by this many steps)</caption>
        <thead className="text-muted">
          <tr><th className="py-1 pr-2">Lag</th><th className="pr-2">Pairs</th><th className="pr-2">Pearson r</th><th className="pr-2">Spearman</th><th>95% interval</th></tr>
        </thead>
        <tbody>
          {r.correlations.map((c) => (
            <tr key={c.lag} className={c.lag === r.best_lag_by_abs_pearson ? "font-semibold" : undefined}>
              <td className="py-0.5 pr-2">{c.lag}</td>
              <td className="pr-2">{c.n}</td>
              <td className="pr-2">{fmt(c.pearson)}</td>
              <td className="pr-2">{fmt(c.spearman)}</td>
              <td>{c.ci95 ? `${fmt(c.ci95[0])} to ${fmt(c.ci95[1])}` : "n/a"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="rounded-md border border-line bg-bg/40 p-2">
        <p className="font-medium">Held-out check (chronological 70/30)</p>
        {h.status === "ok" && h.test_mae ? (
          <>
            <p className="mt-1">
              Lag {h.chosen_lag_steps} chosen on the training part only; {h.test_steps} test steps. Mean absolute error:
              persistence {fmt(h.test_mae.persistence)}, yesterday-only model {fmt(h.test_mae.yesterday_only_model)}, with this series{" "}
              {fmt(h.test_mae.with_series)}.
            </p>
            <p className="mt-1">{h.verdict}</p>
            {h.assumption && <p className="mt-1 text-muted">{h.assumption}</p>}
          </>
        ) : (
          <p className="mt-1 text-muted">{h.note ?? "Not run."}</p>
        )}
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-muted">
        {r.caveats.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <p className="text-muted">{r.not_applied}</p>
    </div>
  );
}

function Relationship({ doc, numeric }: { doc: KbDocument; numeric: string[] }) {
  const [column, setColumn] = useState(numeric[0] ?? "");
  const [pollutant, setPollutant] = useState("pm25");
  const [zone, setZone] = useState("");
  const [ahead, setAhead] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Relationship | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await fetchRelationship(doc.id, column, pollutant, zone.trim() || undefined, ahead));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "The test could not be run.");
    } finally {
      setBusy(false);
    }
  }

  if (numeric.length === 0) return <p className="text-xs text-muted">This table has no numeric column to test.</p>;
  const field = "h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg";
  return (
    <section aria-label="Relationship to measured pollution">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">Relationship to measured pollution</h3>
      <p className="mb-2 text-xs text-muted">
        Aligns one column with the network mean of real station observations and tests whether it would have helped a one-step forecast.
        A screening test: it does not change or retrain the forecasting model.
      </p>
      <form onSubmit={run} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted">Column
          <select className={field} value={column} onChange={(e) => setColumn(e.target.value)}>
            {numeric.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">Pollutant
          <select className={field} value={pollutant} onChange={(e) => setPollutant(e.target.value)}>
            {POLLUTANTS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">Zone (optional)
          <input className={field} value={zone} onChange={(e) => setZone(e.target.value)} placeholder="e.g. Delhi" maxLength={40} />
        </label>
        <label className="flex items-center gap-2 pb-2 text-xs text-muted">
          <input type="checkbox" checked={ahead} onChange={(e) => setAhead(e.target.checked)} />
          Known in advance (a weather forecast or a calendar)
        </label>
        <button type="submit" className={btnPrimary} disabled={busy || !column}>{busy ? "Running…" : "Run test"}</button>
      </form>
      {error && <p role="alert" className="mt-2 rounded-md border border-danger/40 bg-danger/5 p-2 text-xs text-danger">{error}</p>}
      {result && <RelationshipResult r={result} />}
    </section>
  );
}

function Profile({ doc }: { doc: KbDocument }) {
  const res = useResource(`kb-profile:${doc.id}`, 0, (s) => fetchProfile(doc.id, s));
  if (res.status === "loading") return <LoadingState label="Reading the table profile" />;
  if (res.status === "error") return <ErrorState title="The table profile could not be loaded" message={res.error.message} />;
  const p = res.data;
  const numeric = p.columns.filter((c) => c.type === "integer" || c.type === "real").map((c) => c.name);
  return (
    <>
      <section aria-label="Table profile">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">Table profile</h3>
        <p className="mb-2 text-xs text-muted">
          {p.rows.toLocaleString()} rows · {p.columns.length} columns
          {p.time_column && ` · time column "${p.time_column}", ${p.resolution ?? "unknown resolution"}, ${p.time_start} to ${p.time_end} (UTC)`}
          {p.timezone_assumed && ` · times without an offset read as ${p.timezone_assumed}`}
        </p>
        <div className="max-h-56 overflow-auto rounded-md border border-line">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface text-muted">
              <tr><th className="p-1.5">Column</th><th className="p-1.5">Type</th><th className="p-1.5">Missing</th><th className="p-1.5">Range or examples</th></tr>
            </thead>
            <tbody>
              {p.columns.map((c) => (
                <tr key={c.sql} className="border-t border-line">
                  <td className="p-1.5 font-medium">{c.name}</td>
                  <td className="p-1.5">{c.type}</td>
                  <td className="p-1.5">{c.nulls}</td>
                  <td className="p-1.5 text-muted">
                    {c.min !== undefined && c.min !== null ? `${c.min} to ${c.max}${c.mean !== undefined ? ` (mean ${c.mean})` : ""}` : (c.examples ?? []).join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-xs text-muted">The assistant computes averages, counts and groups over this table with the query tool; units are not inferred.</p>
      </section>
      {p.time_column ? <Relationship doc={doc} numeric={numeric} /> : (
        <p className="text-xs text-muted">No column could be read as a date or time, so this table cannot be compared with observations.</p>
      )}
    </>
  );
}

export function DatasetPanel({ doc }: { doc: KbDocument }) {
  return (
    <div className="space-y-4">
      <Tags doc={doc} />
      {doc.kind === "csv" && doc.status === "ready" && <Profile doc={doc} />}
    </div>
  );
}
