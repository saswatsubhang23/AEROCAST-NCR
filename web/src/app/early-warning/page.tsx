"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { ApiError } from "@/lib/http";
import { fetchEarlyWarning, type EarlyWarning, type WarningLevel, type WarningStation } from "@/lib/twin/earlyWarning";
import { fetchThresholds, fetchTwinStatus } from "@/lib/twin/api";
import type { RiskThreshold, TwinStatus } from "@/lib/twin/types";
import { formatIST } from "@/lib/weather/time";

const LEVEL_LABEL: Record<WarningLevel, string> = { likely: "Likely above threshold", possible: "Possibly above threshold", none: "Below threshold" };
const LEVEL_TONE: Record<WarningLevel, string> = { likely: "border-danger/60 text-danger", possible: "border-warn/60 text-warn", none: "border-line text-muted" };

function Spark({ s, threshold }: { s: WarningStation; threshold: number }) {
  const W = 120;
  const H = 32;
  const pts = s.series;
  if (pts.length < 2) return null;
  const vals = pts.flatMap((p) => [p.predicted, p.lower ?? p.predicted, p.upper ?? p.predicted, threshold]);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const x = (i: number) => (i / (pts.length - 1)) * (W - 4) + 2;
  const y = (v: number) => H - 3 - ((v - lo) / Math.max(hi - lo, 1e-9)) * (H - 6);
  const band = pts.every((p) => p.lower !== null && p.upper !== null)
    ? `${pts.map((p, i) => `${x(i)},${y(p.upper as number)}`).join(" ")} ${pts.map((_, i) => `${x(pts.length - 1 - i)},${y(pts[pts.length - 1 - i].lower as number)}`).join(" ")}`
    : null;
  return (
    <svg width={W} height={H} role="img" aria-label={`Forecast from +${pts[0].lead_hours} to +${pts[pts.length - 1].lead_hours} hours against the threshold`} className="block">
      {band && <polygon points={band} className="fill-accent/15" />}
      <line x1={0} x2={W} y1={y(threshold)} y2={y(threshold)} className="stroke-warn" strokeDasharray="3 3" strokeWidth={1} />
      <polyline points={pts.map((p, i) => `${x(i)},${y(p.predicted)}`).join(" ")} fill="none" className="stroke-accent" strokeWidth={1.5} />
    </svg>
  );
}

/** "YYYY-MM-DDTHH:mm" read as India Standard Time (UTC+5:30), as everywhere else in the app, to a UTC hour. */
function toUtcIso(istLocal: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(istLocal);
  if (!m) return null;
  const ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) - 5.5 * 3600_000;
  return new Date(Math.floor(ms / 3600_000) * 3600_000).toISOString().replace(".000Z", "Z");
}

function toIstLocal(iso: string): string {
  return new Date(new Date(iso).getTime() + 5.5 * 3600_000).toISOString().slice(0, 16);
}

export default function EarlyWarningPage() {
  const [twin, setTwin] = useState<TwinStatus | null>(null);
  const [thresholds, setThresholds] = useState<RiskThreshold[]>([]);
  const [pollutant, setPollutant] = useState<"pm25" | "pm10">("pm25");
  const [threshold, setThreshold] = useState("naaqs_pm25_24h");
  const [value, setValue] = useState("100");
  const [minConsecutive, setMinConsecutive] = useState(1);
  const [originLocal, setOriginLocal] = useState("");
  const [result, setResult] = useState<EarlyWarning | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([fetchTwinStatus(ac.signal), fetchThresholds(ac.signal)])
      .then(([t, th]) => {
        setTwin(t);
        setThresholds(th.thresholds);
        setOriginLocal(toIstLocal(t.periods.pm25?.dense_to ?? t.to));
      })
      .catch((e) => {
        if (!ac.signal.aborted) setSetupError(e instanceof ApiError ? e.message : "The historical store could not be read.");
      });
    return () => ac.abort();
  }, []);

  const options = useMemo(() => thresholds.filter((t) => t.pollutant === pollutant), [thresholds, pollutant]);
  // The chosen preset may belong to the other pollutant; fall back to this pollutant's first preset without syncing state in an effect.
  const activeThreshold = threshold === "custom" || options.some((o) => o.key === threshold) ? threshold : (options[0]?.key ?? "custom");

  async function run() {
    const origin = toUtcIso(originLocal);
    if (!origin) {
      setError("Choose a valid origin time.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setResult(await fetchEarlyWarning({ pollutant, origin, threshold: activeThreshold, value, minConsecutive }));
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e.message : "The early-warning overview could not be produced.");
    } finally {
      setLoading(false);
    }
  }

  if (setupError) return <ErrorState title="Early warning is unavailable" message={setupError} />;
  if (!twin) return <LoadingState label="Reading the historical store" />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Early Warning"
        description="Which monitoring stations the trained model expects to reach a pollutant threshold in the next hours, from one forecast origin. A back-test on stored data unless the origin is recent."
        actions={<ProvenanceBadge kind="model_forecast" />}
      />
      <Section title="Choose origin and threshold">
        <form
          className="flex flex-wrap items-end gap-3 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            void run();
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">Pollutant</span>
            <select className="rounded border border-line bg-surface px-2 py-1.5" value={pollutant} onChange={(e) => setPollutant(e.target.value as "pm25" | "pm10")}>
              <option value="pm25">PM2.5</option>
              <option value="pm10">PM10</option>
            </select>
          </label>
          <label className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted">Threshold</span>
            <select className="max-w-full rounded border border-line bg-surface px-2 py-1.5" value={activeThreshold} onChange={(e) => setThreshold(e.target.value)}>
              {options.map((o) => (
                <option key={o.key} value={o.key}>{o.name} ({o.value} {o.unit})</option>
              ))}
              <option value="custom">My own value</option>
            </select>
          </label>
          {activeThreshold === "custom" && (
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted">Value (µg/m³)</span>
              <input className="w-24 rounded border border-line bg-surface px-2 py-1.5" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">Forecast origin (IST)</span>
            <input type="datetime-local" className="rounded border border-line bg-surface px-2 py-1.5" value={originLocal} onChange={(e) => setOriginLocal(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">Consecutive lead times</span>
            <select className="rounded border border-line bg-surface px-2 py-1.5" value={minConsecutive} onChange={(e) => setMinConsecutive(+e.target.value)}>
              {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <Button type="submit" variant="primary" disabled={loading}>{loading ? "Forecasting stations…" : "Show warnings"}</Button>
        </form>
        <p className="mt-2 text-xs text-muted">
          Newest hour with observations in the store: {formatIST(twin.periods[pollutant]?.dense_to ?? twin.to)}. The live feed lags and the CPCB archive ends in
          2025, so newer origins usually have no data and are refused rather than guessed.
        </p>
      </Section>

      {loading && <LoadingState label="Running the model for every reporting station" />}
      {error && !loading && <ErrorState title="No overview" message={error} onRetry={() => void run()} />}
      {!result && !loading && !error && <EmptyState title="Nothing shown yet" message="Choose an origin and a threshold, then press Show warnings." />}

      {result && !loading && (
        <>
          {result.stale && (
            <div role="status" className="mb-4 rounded border border-warn/50 bg-warn/5 p-3 text-sm">
              <strong className="font-medium text-warn">Replay, not a current warning.</strong>{" "}
              This origin is {result.data_age_hours < 48 ? `${Math.round(result.data_age_hours)} hours` : `${Math.round(result.data_age_hours / 24)} days`} old.
              The model was applied to stored data from {formatIST(result.origin)}; what happened afterwards is already known.
            </div>
          )}
          <Section title={`${result.stations.length} stations at ${formatIST(result.origin)}`}>
            <div className="mb-3 flex flex-wrap gap-2 text-xs">
              {(["likely", "possible", "none"] as const).map((k) => (
                <span key={k} className={`rounded border px-2 py-1 ${LEVEL_TONE[k]}`}>{result.counts[k]} {LEVEL_LABEL[k].toLowerCase()}</span>
              ))}
              <span className="rounded border border-line px-2 py-1 text-muted">
                {result.threshold.name}: {result.threshold.value} {result.threshold.unit} ({result.threshold.kind.replace("_", " ")})
              </span>
            </div>
            <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Stations ranked by forecast risk, scrollable">
              <table className="w-full min-w-xl text-left text-xs">
                <caption className="sr-only">Stations ranked by forecast risk against the threshold</caption>
                <thead className="border-b border-line uppercase tracking-wider text-muted">
                  <tr>{["Station", "Level", "First at/above", "Peak forecast", "Forecast vs threshold"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-medium">{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {result.stations.map((s) => (
                    <tr key={s.station_id}>
                      <th scope="row" className="px-2 py-1.5 font-normal">{s.name}</th>
                      <td className="px-2 py-1.5"><span className={`rounded border px-1.5 py-0.5 ${LEVEL_TONE[s.level]}`}>{LEVEL_LABEL[s.level]}</span></td>
                      <td className="px-2 py-1.5 font-mono">{s.first_lead_hours === null ? "—" : `+${s.first_lead_hours} h`}</td>
                      <td className="px-2 py-1.5 font-mono">{s.peak_predicted === null ? "—" : `${s.peak_predicted.toFixed(0)} at +${s.peak_lead_hours} h`}</td>
                      <td className="px-2 py-1.5"><Spark s={s} threshold={result.threshold.value} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted">Dashed line: threshold. Band: the model&apos;s empirical prediction interval where one exists. Only lead times the model was trained for are plotted.</p>
          </Section>

          <Section title="How certain is this?">
            <p className="text-sm">{result.uncertainty}</p>
            {result.weak_horizons.length > 0 && (
              <p className="mt-2 rounded border border-warn/50 bg-warn/5 p-2 text-sm">
                On its held-out period the model did not beat simply repeating the last observation at {result.weak_horizons.map((h) => `+${h} h`).join(", ")}.
                Treat those lead times with extra caution.
              </p>
            )}
            <ul className="mt-2 list-disc pl-5 text-xs text-muted">
              {result.caveats.map((c) => <li key={c}>{c}</li>)}
            </ul>
          </Section>

          {result.importance && (
            <Section title="What the model leaned on">
              <p className="text-xs text-muted">{result.importance_note}</p>
              <ol className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                {result.importance.slice(0, 8).map((i) => (
                  <li key={i.feature} className="flex justify-between gap-2 rounded border border-line px-2 py-1">
                    <code className="min-w-0 break-all">{i.feature}</code>
                    <span className="font-mono">{(i.importance * 100).toFixed(1)}%</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {result.skipped.length > 0 && (
            <Section title="Stations not forecast">
              <ul className="text-xs text-muted">
                {result.skipped.map((s) => <li key={s.station_id}>{s.name}: {s.reason}</li>)}
              </ul>
            </Section>
          )}
          <p className="text-xs text-muted">Model {result.model_version ?? "unknown"}. {result.threshold.source}.</p>
        </>
      )}
    </div>
  );
}
