"use client";

import { useState } from "react";
import { ErrorState, LoadingState, btnPrimary, btnSecondary } from "@/components/ui/states";
import { useNotify } from "@/components/ui/Notifications";
import { POLLUTANTS } from "@/lib/air/pollutants";
import type { PollutantKey } from "@/lib/air/types";
import { createRule, deleteRule, OPERATOR_TEXT, setRuleEnabled } from "@/lib/alerts/api";
import type { AlertState, AlertStatus } from "@/lib/alerts/types";
import { useAlerts } from "@/lib/alerts/useAlerts";
import { LOCATIONS } from "@/lib/locations";
import { ApiError } from "@/lib/weather/api";
import { formatIST } from "@/lib/weather/time";

const STATE_TEXT: Record<AlertState, { label: string; cls: string }> = {
  triggered: { label: "Triggered", cls: "border-danger/50 text-danger" },
  not_triggered: { label: "Not triggered", cls: "border-line text-muted" },
  no_data: { label: "No data", cls: "border-line text-muted" },
  stale: { label: "Stale data", cls: "border-warn/50 text-warn" },
  unit_mismatch: { label: "Unit differs", cls: "border-warn/50 text-warn" },
  unavailable: { label: "Source unavailable", cls: "border-warn/50 text-warn" },
  disabled: { label: "Off", cls: "border-line text-muted" },
};

export function StateChip({ state }: { state: AlertState }) {
  const s = STATE_TEXT[state];
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-xs font-medium ${s.cls}`}>{s.label}</span>;
}

const field = "h-9 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg";

export function AlertsPanel() {
  const { state, reload } = useAlerts();
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [location, setLocation] = useState("delhi");
  const [pollutant, setPollutant] = useState<PollutantKey>("pm25");
  const [operator, setOperator] = useState<"gt" | "gte">("gte");
  const [threshold, setThreshold] = useState("");
  const [unit, setUnit] = useState("µg/m³");
  const [name, setName] = useState("");

  async function act(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    try {
      await fn();
      if (done) notify(done);
      await reload();
    } catch (e) {
      notify(e instanceof ApiError ? e.message : "That did not work.", "error");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = Number(threshold);
    if (!Number.isFinite(value) || value <= 0) return notify("Enter a threshold greater than zero.", "error");
    void act(async () => {
      await createRule({ location_id: location, pollutant, operator, threshold: value, unit, name: name.trim() || undefined });
      setThreshold("");
      setName("");
    }, "Alert rule added.");
  }

  if (state.status === "loading") return <LoadingState label="Loading alert rules" />;
  if (state.status === "error") return <ErrorState title="Alerts are unavailable" message={state.error.message} onRetry={reload} />;
  const { data } = state;

  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-line bg-surface p-3 text-sm text-muted">{data.note}</p>
      {!data.source_available && <p role="status" className="rounded-lg border border-warn/40 bg-warn/5 p-3 text-sm text-warn">{data.source_message}</p>}

      <form onSubmit={submit} aria-label="New alert rule" className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">Location
          <select className={field} value={location} onChange={(e) => setLocation(e.target.value)}>
            {LOCATIONS.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">Measurement
          <select className={field} value={pollutant} onChange={(e) => setPollutant(e.target.value as PollutantKey)}>
            {POLLUTANTS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">Condition
          <select className={field} value={operator} onChange={(e) => setOperator(e.target.value as "gt" | "gte")}>
            <option value="gte">at or above</option>
            <option value="gt">above</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">Threshold
          <input className={`${field} w-28`} inputMode="decimal" value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="e.g. 60" required />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">Unit
          <select className={field} value={unit} onChange={(e) => setUnit(e.target.value)}>
            {data.units.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">Name (optional)
          <input className={`${field} w-44`} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button type="submit" className={btnPrimary} disabled={busy || data.statuses.length >= data.max_rules}>Add rule</button>
      </form>

      {data.statuses.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-muted">No alert rules yet. Add one to be told when a measured value crosses a threshold you choose.</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {data.statuses.map((s) => <Row key={s.rule.id} s={s} busy={busy} act={act} />)}
        </ul>
      )}
    </div>
  );
}

function Row({ s, busy, act }: { s: AlertStatus; busy: boolean; act: (fn: () => Promise<unknown>, done?: string) => Promise<void> }) {
  const r = s.rule;
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 p-4 text-sm">
      <div className="min-w-0 space-y-1">
        <p className="flex flex-wrap items-center gap-2 font-medium">{r.name} <StateChip state={s.status} /></p>
        <p className="text-muted">{r.location_name} · {r.measurement} {OPERATOR_TEXT[r.operator]} {r.threshold} {r.unit}</p>
        <p>{s.message}</p>
        {s.observation && (
          <p className="text-xs text-muted">
            Observed {s.observation.value} {s.observation.unit} at {s.observation.station} ({s.observation.distance_km.toFixed(1)} km), {formatIST(s.observation.observed_at)}. Source: {s.source.provider}.
          </p>
        )}
        <p className="text-xs text-muted">{s.threshold_note} Checked {formatIST(s.evaluated_at)}.</p>
      </div>
      <div className="flex gap-2">
        <button type="button" className={btnSecondary} disabled={busy} aria-label={`${r.enabled ? "Turn off" : "Turn on"} ${r.name}`}
          onClick={() => void act(() => setRuleEnabled(r.id, !r.enabled))}>{r.enabled ? "Turn off" : "Turn on"}</button>
        <button type="button" className={btnSecondary} disabled={busy} aria-label={`Delete ${r.name}`}
          onClick={() => void act(() => deleteRule(r.id), "Alert rule deleted.")}>Delete</button>
      </div>
    </li>
  );
}
