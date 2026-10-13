"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { BASELINE_SCENARIO, type SimScenario, type SimulationRun } from "@/lib/twin/simulation";
import { formatIST } from "@/lib/weather/time";

export type SimMode = "transport" | "scenario" | "live";

const MODE_HELP: Record<SimMode, string> = {
  transport: "Carries the observed air at the chosen hour with the weather-model wind. No emission sources, no chemistry.",
  scenario: "The same engine with parameters you change. Hypothetical: it shows what the model does under those assumptions, not what will happen.",
  live: "Starts from the newest hour with enough observations and updates only when new observations or new wind data exist.",
};

function Slider({ label, value, min, max, step, unit, onChange }: { label: string; value: number; min: number; max: number; step: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="font-mono text-fg">{value}{unit ?? ""}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} className="accent-[var(--accent)]" />
    </label>
  );
}

/** Controls for a run: mode, length, initialisation hour and (for a scenario) every parameter that is changed, in the open. */
export function SimulationControls({ mode, onMode, hours, onHours, scenario, onScenario, initLabel, busy, onRun }: {
  mode: SimMode; onMode: (m: SimMode) => void; hours: number; onHours: (h: number) => void; scenario: SimScenario; onScenario: (s: SimScenario) => void;
  initLabel: string; busy: boolean; onRun: () => void;
}) {
  const set = (patch: Partial<SimScenario>) => onScenario({ ...scenario, ...patch });
  const modified = JSON.stringify(scenario) !== JSON.stringify(BASELINE_SCENARIO);
  return (
    <section aria-label="Simulation controls" className="space-y-3 rounded-lg border border-line bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Simulation mode
          <select value={mode} onChange={(e) => onMode(e.target.value as SimMode)} className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
            <option value="transport">Transport (baseline)</option>
            <option value="scenario">Scenario (hypothetical)</option>
            <option value="live">Live (newest observations)</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Length
          <select value={hours} onChange={(e) => onHours(Number(e.target.value))} className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
            {[12, 24, 48].map((h) => (
              <option key={h} value={h}>{h} hours</option>
            ))}
          </select>
        </label>
        <Button variant="primary" onClick={onRun} disabled={busy || (mode === "scenario" && !modified)}>
          {busy ? "Running…" : mode === "live" ? "Load live run" : "Run simulation"}
        </Button>
      </div>
      <p className="text-xs text-muted">{MODE_HELP[mode]} Initialised at: <strong className="text-fg">{initLabel}</strong>.</p>
      {mode === "scenario" && (
        <fieldset className="grid min-w-0 gap-3 rounded-md border border-line p-3 sm:grid-cols-2">
          <legend className="px-1 text-xs font-medium text-muted">Modified parameters (hypothetical)</legend>
          <Slider label="Wind speed multiplier" value={scenario.wind_scale} min={0.25} max={2} step={0.05} unit="×" onChange={(v) => set({ wind_scale: v })} />
          <Slider label="Wind direction turned clockwise" value={scenario.wind_rotation_deg} min={-90} max={90} step={5} unit="°" onChange={(v) => set({ wind_rotation_deg: v })} />
          <Slider label="Horizontal diffusivity" value={scenario.diffusivity_m2s} min={1} max={500} step={1} unit=" m²/s" onChange={(v) => set({ diffusivity_m2s: v })} />
          <Slider label="First-order loss (hypothetical removal)" value={scenario.loss_per_hour} min={0} max={0.5} step={0.01} unit=" /h" onChange={(v) => set({ loss_per_hour: v })} />
          <label className="flex flex-col gap-1 text-xs text-muted">
            Boundary-layer mixing
            <select value={scenario.mixing_mode} onChange={(e) => set({ mixing_mode: e.target.value as SimScenario["mixing_mode"] })}
              className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
              <option value="none">None (baseline)</option>
              <option value="column_dilution">Dilution when the layer deepens</option>
            </select>
          </label>
          {scenario.mixing_mode === "column_dilution" && (
            <Slider label="Air aloft as a share of surface value" value={scenario.aloft_ratio} min={0} max={1} step={0.05} onChange={(v) => set({ aloft_ratio: v })} />
          )}
          <p className="text-xs text-muted sm:col-span-2">
            There is no control for adding emission sources: the model has none, and a field from this engine never locates a source.
          </p>
        </fieldset>
      )}
    </section>
  );
}

function Fact({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-2 border-b border-line py-1 last:border-0">
      <dt className="w-40 shrink-0 text-xs text-muted">{k}</dt>
      <dd className="min-w-0 flex-1 text-xs">{children}</dd>
    </div>
  );
}

/** Everything a run says about itself: initialisation, validity, extent, inputs and their freshness, model, status, limits, and the check against observations. */
export function RunSummary({ run, index }: { run: SimulationRun; index: number }) {
  const [more, setMore] = useState(false);
  const f = run.freshness;
  const v = run.validation;
  const known = run.known_fraction[Math.min(index, run.known_fraction.length - 1)];
  return (
    <section aria-label="Simulation run" className="space-y-3 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Run {run.run_id.slice(0, 8)}</h2>
        <ProvenanceBadge kind={run.mode === "scenario" ? "hypothetical" : "simulated"} />
        {f.status === "stale" && <ProvenanceBadge kind="stale" detail={f.note} />}
        {run.live && <span className="rounded border border-line px-1.5 py-0.5 text-xs text-muted">live</span>}
        <span className={`rounded border px-1.5 py-0.5 text-xs ${run.execution.status === "completed" ? "border-line text-muted" : "border-warn/50 text-warn"}`}>{run.execution.status}</span>
      </div>
      {f.status === "stale" && <p role="status" className="rounded border border-warn/40 bg-surface-2 p-2 text-xs text-warn">{f.note}</p>}
      {run.scenario && <p className="rounded border border-warn/40 bg-surface-2 p-2 text-xs text-warn">{run.scenario.statement} Changed: {Object.entries(run.scenario.changed).map(([k, x]) => `${k} = ${x}`).join(", ")}.</p>}
      <dl>
        <Fact k="Initialised">{formatIST(run.initialisation)}</Fact>
        <Fact k="Valid">{formatIST(run.valid_times[0])} to {formatIST(run.valid_times[run.valid_times.length - 1])} ({run.execution.simulated_hours} h{run.execution.status === "limited" ? `, limited from ${run.execution.requested_hours} h by the wind data` : ""})</Fact>
        <Fact k="Extent">{run.extent.south}–{run.extent.north}°N, {run.extent.west}–{run.extent.east}°E</Fact>
        <Fact k="Grid">{run.grid.rows} × {run.grid.cols} cells, about {(run.grid.dx_m / 1000).toFixed(1)} km</Fact>
        <Fact k="Initial observations">
          {run.inputs.observations.n_stations} stations at {formatIST(run.inputs.observations.time)}, {f.observation_age_hours} h old; an estimate exists in {run.inputs.observations.cells_with_initial_estimate} of {run.inputs.observations.cells_total} cells
        </Fact>
        <Fact k="Wind">{run.inputs.wind.provider} ({run.inputs.wind.mode}); retrieved {formatIST(run.inputs.wind.retrieved_at)}; {run.inputs.wind.frames} hourly frames; {run.inputs.wind.space_interpolation}</Fact>
        <Fact k="Model">{run.model.name} {run.model.version}; {run.model.scheme}</Fact>
        <Fact k="Known at this hour">{(known * 100).toFixed(0)}% of cells have a value; the rest have no information, not zero</Fact>
        <Fact k="Execution">{run.execution.duration_ms} ms, {run.execution.engine_steps} steps of {run.execution.dt_seconds_min}–{run.execution.dt_seconds_max} s, Courant ≤ {run.execution.max_courant_number}; deterministic (same inputs give the same run id and arrays)</Fact>
        {run.initial_estimate_error && (
          <Fact k="Initial estimate error">
            leave-one-out MAE {run.initial_estimate_error.mae}, RMSE {run.initial_estimate_error.rmse}, bias {run.initial_estimate_error.bias} {run.unit} over {run.initial_estimate_error.n} of {run.initial_estimate_error.stations_total} stations
          </Fact>
        )}
      </dl>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Checked against observations</h3>
        {!v.available ? (
          <p className="mt-1 text-xs text-muted">{v.reason}</p>
        ) : (
          <div className="mt-1 space-y-2 text-xs">
            <p className={v.verdict?.includes("did NOT") ? "text-warn" : "text-muted"}>{v.verdict}</p>
            {[["All stations", v.all_stations], ["Withheld stations (out of sample)", v.withheld_stations]].map(([label, set]) => {
              const sc = set as typeof v.all_stations;
              return sc?.summary ? (
                <p key={label as string} className="text-muted">
                  <strong className="text-fg">{label as string}:</strong> MAE {sc.summary.mae} vs holding the first observation {sc.summary.persistence_mae} {run.unit} ({sc.summary.leads}, {sc.summary.n} comparisons, skill {sc.summary.skill_vs_persistence ?? "n/a"})
                  {sc.stations_withheld ? `; ${sc.stations_withheld} stations left out of the initial field` : ""}.
                </p>
              ) : null;
            })}
          </div>
        )}
      </div>
      <div>
        <button type="button" onClick={() => setMore(!more)} aria-expanded={more} className="text-xs text-accent underline">
          {more ? "Hide" : "Show"} limitations and uncertainty
        </button>
        {more && (
          <div className="mt-2 space-y-2 text-xs text-muted">
            <p><strong className="text-fg">Uncertainty.</strong> {run.uncertainty.kind}. {run.uncertainty.note}</p>
            <ul className="list-disc space-y-1 pl-5">{run.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            <p>{run.forecast_provider.role}</p>
          </div>
        )}
      </div>
    </section>
  );
}
