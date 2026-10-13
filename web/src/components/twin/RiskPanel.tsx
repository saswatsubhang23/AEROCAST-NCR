"use client";

import { useState } from "react";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { fetchRisk, fetchThresholds } from "@/lib/twin/api";
import type { TwinPollutant } from "@/lib/twin/types";
import { useOptional } from "@/lib/twin/useOptional";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

/** Forecast lead times at or above a documented or user-defined threshold, with the limits of that comparison stated. */
export function RiskPanel({ pollutant, stationId, origin }: { pollutant: TwinPollutant; stationId: number; origin: string }) {
  const thresholds = useResource("twin-thresholds", 0, (s) => fetchThresholds(s));
  const options = thresholds.status === "ready" ? thresholds.data.thresholds.filter((t) => t.pollutant === pollutant) : [];
  const [choice, setChoice] = useState<string>("");
  const [custom, setCustom] = useState("50");
  const picked = choice || options[0]?.key || "custom";
  const customOk = picked !== "custom" || (Number(custom) > 0 && Number.isFinite(Number(custom)));
  const risk = useOptional(thresholds.status === "ready" && customOk, `risk:${pollutant}:${stationId}:${origin}:${picked}:${custom}`, (s) => fetchRisk(pollutant, stationId, origin, picked, custom, s));

  return (
    <section aria-label="Risk windows" className="space-y-3 rounded-lg border border-line bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">Risk windows</h2>
        <ProvenanceBadge kind="model_forecast" detail="Computed from the model forecast, not from observations." />
      </div>
      <label className="flex flex-col gap-1 text-xs font-medium text-muted">
        Threshold
        <select value={picked} onChange={(e) => setChoice(e.target.value)} className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
          {options.map((t) => (
            <option key={t.key} value={t.key}>
              {t.name}: {t.value} {t.unit} ({t.kind.replace("_", " ")})
            </option>
          ))}
          <option value="custom">User-defined value (not an official standard)</option>
        </select>
      </label>
      {picked === "custom" && (
        <label className="flex items-center gap-2 text-xs text-muted">
          Value (µg/m³)
          <input value={custom} onChange={(e) => setCustom(e.target.value)} inputMode="decimal" className="h-8 w-24 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg" />
        </label>
      )}
      {risk.status === "loading" && <LoadingState label="Evaluating the forecast" />}
      {risk.status === "error" && <ErrorState title="No risk windows for this hour" message={risk.error.message} />}
      {risk.status === "ready" && (
        <>
          <p className="text-xs text-muted">
            {risk.data.threshold.name}: {risk.data.threshold.value} {risk.data.threshold.unit}, averaging &quot;{risk.data.threshold.averaging}&quot;. Source: {risk.data.threshold.source}. Rule: {risk.data.duration_rule}. Model {risk.data.model_version}, forecast from {formatIST(risk.data.origin)}.
          </p>
          {risk.data.windows.length === 0 ? (
            <p className="rounded border border-line p-2">No forecast lead time reaches this threshold.</p>
          ) : (
            <ul className="space-y-1">
              {risk.data.windows.map((w) => (
                <li key={w.start} className="rounded border border-warn/40 p-2">
                  <strong>{formatIST(w.start)}</strong> to <strong>{formatIST(w.end)}</strong> (lead +{w.lead_from_hours} to +{w.lead_to_hours} h, {w.points} forecast point{w.points === 1 ? "" : "s"}); predicted {w.predicted_range[0].toFixed(1)} to {w.predicted_range[1].toFixed(1)} {risk.data.unit}; {w.likely_points} of {w.points} also reach it at the interval&apos;s lower bound.
                </li>
              ))}
            </ul>
          )}
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">
            {risk.data.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
