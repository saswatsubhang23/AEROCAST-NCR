"use client";

import { ModelDiagnostics } from "@/components/settings/ModelDiagnostics";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { fetchModelStatus } from "@/lib/twin/api";
import { useResource } from "@/lib/weather/context";
import { getJson } from "@/lib/weather/api";
import { formatIST } from "@/lib/weather/time";

type JevStatus = { mode: string; enabled: boolean; api_key_configured: boolean; message: string; influences_answers: boolean; sent_to_service: string };

const f = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "n/a" : v.toFixed(d));

/** Reports what is actually loaded: the trained forecasting model (with its held-out scores) and the optional Jev service. */
export function ModelStatusPanel() {
  const model = useResource("model-status", 0, (s) => fetchModelStatus(s));
  const jev = useResource("jev-status", 0, (s) => getJson<JevStatus>("/api/jev/status", s));

  return (
    <div className="space-y-4">
      {model.status === "loading" && <LoadingState label="Checking the trained model" />}
      {model.status === "error" && <ErrorState title="Model status unavailable" message={model.error.message} />}
      {model.status === "ready" && !model.data.available && (
        <div className="rounded-lg border border-line bg-surface p-4 text-sm" role="status">
          <p className="flex items-center gap-2 font-medium">
            Trained forecasting model <ProvenanceBadge kind="unavailable" />
          </p>
          <p className="mt-1 text-muted">{model.data.reason}</p>
        </div>
      )}
      {model.status === "ready" && model.data.available && (
        <div className="rounded-lg border border-line bg-surface p-4 text-sm">
          <p className="flex flex-wrap items-center gap-2 font-medium">
            Trained forecasting model <ProvenanceBadge kind="model_forecast" />
            <span className="font-mono text-xs text-muted">run {model.data.run_id}</span>
          </p>
          <p className="mt-1 text-xs text-muted">
            Created {model.data.created_at ? formatIST(model.data.created_at) : "unknown"}. Training data: {model.data.dataset_provenance}. {model.data.caveat}
          </p>
          <div className="mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Held-out scores per pollutant and horizon, scrollable">
            <table className="w-full min-w-120 text-left text-sm">
              <caption className="sr-only">Held-out scores of each trained pollutant and horizon</caption>
              <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
                <tr>
                  {["Pollutant", "Horizon", "Model", "Test MAE", "Persistence MAE", "Test RMSE", "R²", "Test samples"].map((h) => (
                    <th key={h} scope="col" className="px-3 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {model.data.targets.map((t) => (
                  <tr key={`${t.pollutant}-${t.horizon_hours}`}>
                    <td className="px-3 py-1.5">{t.pollutant}</td>
                    <td className="px-3 py-1.5">+{t.horizon_hours} h</td>
                    <td className="px-3 py-1.5">{t.model}</td>
                    <td className="px-3 py-1.5 font-mono tabular-nums">{f(t.test?.mae)} {t.unit}</td>
                    <td className="px-3 py-1.5 font-mono tabular-nums">{f(t.persistence_test?.mae)}</td>
                    <td className="px-3 py-1.5 font-mono tabular-nums">{f(t.test?.rmse)}</td>
                    <td className="px-3 py-1.5 font-mono tabular-nums">{f(t.test?.r2, 3)}</td>
                    <td className="px-3 py-1.5 font-mono tabular-nums">{t.test?.n.toLocaleString() ?? "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">Scores are on a held-out later period. Full comparison: {model.data.report}.</p>
        </div>
      )}

      {model.status === "ready" && model.data.available && model.data.targets.length > 0 && <ModelDiagnostics model={model.data} />}

      {jev.status === "ready" && (
        <div className="rounded-lg border border-line bg-surface p-4 text-sm">
          <p className="font-medium">Jev decision support (optional)</p>
          <p className="mt-1 text-muted">
            {jev.data.message} Mode: <span className="font-mono">{jev.data.mode}</span>. API key {jev.data.api_key_configured ? "present" : "not set"}. It {jev.data.influences_answers ? "can" : "cannot"} change answers.
          </p>
          <p className="mt-1 text-xs text-muted">{jev.data.sent_to_service}</p>
        </div>
      )}
    </div>
  );
}

/** One-line forecasting availability for the Overview: what exists, or why nothing does. */
export function ForecastAvailability() {
  const model = useResource("model-status-overview", 0, (s) => fetchModelStatus(s));
  if (model.status === "loading") return <LoadingState label="Checking forecasting" />;
  if (model.status === "error") return <p className="rounded-lg border border-line bg-surface p-4 text-sm text-muted">Forecast status could not be read: {model.error.message}</p>;
  const m = model.data;
  return (
    <div className="rounded-lg border border-line bg-surface p-4 text-sm" role="status">
      {m.available ? (
        <>
          <p className="flex flex-wrap items-center gap-2 font-medium">
            A trained pollutant model is loaded <ProvenanceBadge kind="model_forecast" />
          </p>
          <p className="mt-1 text-muted">
            {m.targets.length} target{m.targets.length === 1 ? "" : "s"}: {m.targets.map((t) => `${t.pollutant} +${t.horizon_hours} h`).join(", ")}. A forecast is produced only when the newest observations are fresh enough; otherwise it is reported unavailable.
          </p>
        </>
      ) : (
        <>
          <p className="flex flex-wrap items-center gap-2 font-medium">
            Pollution forecasts <ProvenanceBadge kind="unavailable" />
          </p>
          <p className="mt-1 text-muted">{m.reason}</p>
        </>
      )}
    </div>
  );
}
