"use client";

import { useState } from "react";
import { ErrorState, LoadingState, btnSecondary } from "@/components/ui/states";
import { jsonBody, request } from "@/lib/http";
import { useLocation } from "@/lib/location";
import { useResource } from "@/lib/weather/context";
import { getJson } from "@/lib/weather/api";
import { formatIST } from "@/lib/weather/time";

type Status = { configured: boolean; available: boolean | null; provider: string | null; message: string };
type Spatial = { kind: "station" | "point" | "grid"; station_name?: string | null; distance_km?: number | null; resolution_km?: number | null };
type Freshness = { input_age_hours?: number | null; max_age_hours?: number | null; status: "fresh" | "stale" | "unknown" };
type Series = {
  pollutant: string; unit: string; times: string[]; values: number[]; intervals: { level: number; lower: number[]; upper: number[] }[];
  /** Contract v2 blocks; absent when the provider does not send them. */
  spatial?: Spatial | null; freshness?: Freshness | null; quality_flags?: string[];
};
type Result = { provider: string; notice: string; forecast: { model_version: string; horizon_hours: number; forecasts: Series[] } };

/**
 * Shows whether an external forecasting service is connected. With none configured it says "unavailable" and offers nothing
 * else: AEROCAST never produces a forecast itself. With one configured, values appear only as the provider returned them.
 */
export function ForecastPanel() {
  const { location } = useLocation();
  const status = useResource("forecast-status", 0, (s) => getJson<Status>("/api/forecast/status", s));
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status.status === "loading") return <LoadingState label="Checking for a forecasting service" />;
  if (status.status === "error") return <ErrorState title="Forecast status unavailable" message={status.error.message} />;
  const st = status.data;
  if (!st.configured)
    return <p role="status" className="rounded-lg border border-line bg-surface p-4 text-sm text-muted"><strong className="text-fg">Pollution forecasts: unavailable.</strong> {st.message}</p>;

  async function requestForecast() {
    setBusy(true);
    setError(null);
    try {
      const body = await request<Result>("/api/forecast", { ...jsonBody("POST", { location_id: location.id, horizon_hours: 24, pollutants: ["pm25"] }), timeoutMs: 90_000 });
      setResult(body);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : "The forecast request failed.");
    } finally {
      setBusy(false);
    }
  }

  const f = result?.forecast.forecasts[0];
  return (
    <div className="space-y-3 text-sm">
      <p className="rounded-lg border border-line bg-surface p-4 text-muted">
        An external forecasting service ({st.provider}) is connected{st.available === false ? ", but it did not answer its last health check" : ""}. Its output is shown exactly as returned and is not produced by AEROCAST.
      </p>
      <button type="button" className={btnSecondary} onClick={requestForecast} disabled={busy}>{busy ? "Requesting…" : `Request 24 h PM2.5 forecast for ${location.name}`}</button>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {result && f && (
        <div className="space-y-2">
        <ScopeNote series={f} />
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-96 text-left">
            <caption className="px-4 pt-3 text-left text-xs text-muted">{result.notice} Model {result.forecast.model_version}.</caption>
            <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
              <tr><th scope="col" className="px-4 py-2 font-medium">Time (IST)</th><th scope="col" className="px-4 py-2 font-medium">PM2.5 ({f.unit})</th><th scope="col" className="px-4 py-2 font-medium">Range</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {f.times.map((t, i) => (
                <tr key={t}>
                  <td className="px-4 py-1.5">{formatIST(t)}</td>
                  <td className="px-4 py-1.5 font-mono tabular-nums">{f.values[i].toFixed(1)}</td>
                  <td className="px-4 py-1.5 font-mono tabular-nums">{f.intervals[0] ? `${f.intervals[0].lower[i].toFixed(1)} to ${f.intervals[0].upper[i].toFixed(1)} (${Math.round(f.intervals[0].level * 100)}%)` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </div>
      )}
    </div>
  );
}

const FLAG_TEXT: Record<string, string> = {
  "interval:empirical_validation_residuals": "The range is an empirical validation-residual band, not a guarantee.",
  "interval:none": "No uncertainty range was provided.",
  "weather_inputs:archive_values_from_store": "Weather inputs are stored archive values, not a live weather forecast.",
};

function flagText(flag: string): string {
  if (flag.startsWith("weak_horizon:")) return `The model did not beat the persistence baseline at ${flag.slice("weak_horizon:".length)} on its held-out period.`;
  return FLAG_TEXT[flag] ?? flag;
}

/** What the forecast is about and how fresh its inputs were, exactly as the provider stated (contract v2). */
function ScopeNote({ series }: { series: Series }) {
  const { spatial, freshness, quality_flags: flags } = series;
  if (!spatial && !freshness && !(flags && flags.length)) return null;
  const where = !spatial ? null : spatial.kind === "station"
    ? `A point forecast for one monitoring station${spatial.station_name ? ` (${spatial.station_name}${spatial.distance_km != null ? `, ${spatial.distance_km.toFixed(1)} km from the selected place` : ""})` : ""}, not a city-wide field.`
    : spatial.kind === "grid" ? `A gridded forecast at ${spatial.resolution_km} km resolution.` : "A forecast for a single point.";
  const age = !freshness ? null : freshness.input_age_hours != null
    ? `Newest input ${freshness.input_age_hours.toFixed(1)} h old${freshness.max_age_hours ? ` (limit ${freshness.max_age_hours} h)` : ""}: ${freshness.status}.`
    : `Input freshness: ${freshness.status}.`;
  return (
    <ul className="list-disc space-y-0.5 rounded-lg border border-line bg-surface p-3 pl-7 text-xs text-muted" aria-label="What this forecast covers">
      {where && <li>{where}</li>}
      {age && <li className={freshness?.status === "stale" ? "text-warn" : undefined}>{age}</li>}
      {(flags ?? []).map((f) => <li key={f}>{flagText(f)}</li>)}
    </ul>
  );
}
