"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { ApiError } from "@/lib/http";
import {
  activateTraining, cancelTraining, fetchTrainingJob, fetchTrainingJobs, fetchTrainingStatus, rollbackModel, startTraining,
  type JobStatus, type StepStatus, type TrainingJob, type TrainingStatus,
} from "@/lib/training/api";
import { formatIST } from "@/lib/weather/time";

const POLL_MS = 3000;

type Bundle = { status: TrainingStatus; job: TrainingJob | null; history: TrainingJob[] };

async function fetchBundle(watch: string | null, signal: AbortSignal): Promise<Bundle> {
  const status = await fetchTrainingStatus(signal);
  const history = (await fetchTrainingJobs(signal)).jobs;
  const id = status.active_job?.job_id ?? watch ?? history[0]?.job_id ?? null;
  const job = id ? await fetchTrainingJob(id, 80, signal) : null;
  return { status, job, history };
}
const STEP_TONE: Record<StepStatus, string> = {
  pending: "border-line text-muted", running: "border-accent/60 text-accent", ok: "border-line text-fg", failed: "border-danger/60 text-danger",
  skipped: "border-line text-muted", cancelled: "border-warn/60 text-warn",
};
const JOB_TONE: Record<JobStatus, string> = {
  queued: "text-muted", running: "text-accent", completed: "text-fg", failed: "text-danger", cancelled: "text-warn", interrupted: "text-warn",
};

function duration(a: string | null, b: string | null, nowMs: number): string {
  if (!a) return "";
  const end = b ? new Date(b).getTime() : nowMs;
  const s = Math.max(0, Math.round((end - new Date(a).getTime()) / 1000));
  return s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
}

export default function TrainingPage() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"start" | "activate" | "rollback" | null>(null);
  const [preset, setPreset] = useState<"standard" | "quick">("standard");
  const [refresh, setRefresh] = useState(true);
  const [pollutants, setPollutants] = useState<string[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [watch, setWatch] = useState<string | null>(null); // a job the person chose from the history

  // One bundle per refresh: status, the job being shown (the running one, the chosen one, else the newest) and the history.
  useEffect(() => {
    const ac = new AbortController();
    fetchBundle(watch, ac.signal)
      .then((b) => {
        setBundle(b);
        setError(null);
        setNow(Date.now());
      })
      .catch((e) => {
        if (!ac.signal.aborted) setError(e instanceof ApiError ? e.message : "The training status could not be loaded.");
      });
    return () => ac.abort();
  }, [version, watch]);

  const status = bundle?.status ?? null;
  const job = bundle?.job ?? null;
  const history = bundle?.history ?? [];
  const running = job?.status === "running" || job?.status === "queued";
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setVersion((v) => v + 1), POLL_MS);
    return () => clearInterval(id);
  }, [running]);
  const reload = () => setVersion((v) => v + 1);

  async function act(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await fn();
      if (done) setNotice(done);
      reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The action failed.");
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  if (error && !status) return (
    <>
      <PageHeader title="Model training" description="Train the forecasting models on this computer from the stored historical data and the newest data." />
      <ErrorState title="The training service is unavailable" message={error} onRetry={reload} />
    </>
  );
  if (!status) return (
    <>
      <PageHeader title="Model training" description="Train the forecasting models on this computer from the stored historical data and the newest data." />
      <LoadingState label="Reading the data store and the active model" />
    </>
  );

  const d = status.data;
  const activeJob = status.active_job;
  const latestObsAge = d.latest_observation ? Math.round((now - new Date(d.latest_observation).getTime()) / 3_600_000) : null;
  const result = job?.status === "completed" ? job.result : undefined;

  return (
    <>
      <PageHeader
        title="Model training"
        description="Train the forecasting models on this computer from the stored historical data and the newest data, then decide whether to use the result. Nothing here uses a language model or Claude tokens."
      />
      {notice && <p role="status" className="mb-4 rounded-lg border border-line bg-surface p-3 text-sm">{notice}</p>}
      {actionError && <div className="mb-4"><ErrorState title="That did not work" message={actionError} /></div>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Data it will use">
          <dl className="space-y-1.5 text-sm">
            <div className="flex gap-2"><dt className="w-44 shrink-0 text-muted">Newest air-quality hour</dt><dd>{d.latest_observation ? `${formatIST(d.latest_observation)}${latestObsAge !== null ? ` (${latestObsAge < 48 ? `${latestObsAge} h` : `${(latestObsAge / 24).toFixed(1)} days`} ago)` : ""}` : "none"}</dd></div>
            <div className="flex gap-2"><dt className="w-44 shrink-0 text-muted">Newest weather hour</dt><dd>{d.latest_weather ? formatIST(d.latest_weather) : "none"}</dd></div>
            <div className="flex gap-2"><dt className="w-44 shrink-0 text-muted">Feature table</dt><dd>{d.feature_set ? `${d.feature_set.rows.toLocaleString()} rows, built ${formatIST(d.feature_set.created_at)}` : "not built yet"}</dd></div>
            <div className="flex gap-2"><dt className="w-44 shrink-0 text-muted">Free disk space</dt><dd>{d.free_disk_gb !== null ? `${d.free_disk_gb} GB` : "unknown"}</dd></div>
          </dl>
          {d.error && <p className="mt-2 text-xs text-warn">{d.error}</p>}
          {!d.store_exists && <p className="mt-2 text-sm text-warn">No historical store exists yet, so there is nothing to train on.</p>}
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted">
            {status.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </Section>

        <Section title="Active model">
          {status.model.available ? (
            <div className="space-y-1.5 text-sm">
              <p><span className="font-mono">{status.model.run_id}</span>{" "}<ProvenanceBadge kind="model_forecast" /></p>
              <p className="text-muted">Trained {status.model.created_at ? formatIST(status.model.created_at) : "at an unknown time"}; {status.model.cells} pollutant/horizon models.</p>
              {status.previous_model && (
                <p className="text-xs text-muted">
                  Previous model: <span className="font-mono">{status.previous_model}</span>{" "}
                  <Button size="sm" variant="ghost" onClick={() => setConfirm("rollback")} disabled={busy || !!activeJob}>Return to it</Button>
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted">No trained model is active. {status.model.reason}</p>
          )}
        </Section>
      </div>

      <div className="mt-4">
        <Section title="Start a training run">
          {activeJob ? (
            <p className="text-sm text-muted">A job is running. It can be watched below; a new one can start when it ends.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm">
                <fieldset className="min-w-0">
                  <legend className="mb-1 text-xs font-medium text-muted">Size of the run</legend>
                  {(["standard", "quick"] as const).map((p) => (
                    <label key={p} className="mr-4 inline-flex items-center gap-1.5">
                      <input type="radio" name="preset" checked={preset === p} onChange={() => setPreset(p)} className="accent-[var(--accent)]" />
                      {p === "standard" ? "Standard (PM2.5, PM10, NO₂, O₃; four model types; hours)" : "Quick (PM2.5, two model types; minutes)"}
                    </label>
                  ))}
                </fieldset>
                <label className="inline-flex items-center gap-1.5">
                  <input type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
                  First download the newest air-quality and weather hours
                </label>
              </div>
              <fieldset className="min-w-0 text-sm">
                <legend className="mb-1 text-xs font-medium text-muted">Pollutants (leave all unticked for the preset&apos;s own list)</legend>
                {status.options.pollutants.map((p) => (
                  <label key={p} className="mr-4 inline-flex items-center gap-1.5">
                    <input type="checkbox" checked={pollutants.includes(p)} onChange={(e) => setPollutants((cur) => (e.target.checked ? [...cur, p] : cur.filter((x) => x !== p)))} className="accent-[var(--accent)]" />
                    {p === "pm25" ? "PM2.5" : p === "pm10" ? "PM10" : p === "no2" ? "NO₂" : p === "so2" ? "SO₂" : "O₃"}
                  </label>
                ))}
              </fieldset>
              <Button variant="primary" onClick={() => setConfirm("start")} disabled={busy || !d.store_exists}>
                Start training
              </Button>
            </div>
          )}
        </Section>
      </div>

      {job && (
        <div className="mt-4">
          <Section title={`Job ${job.job_id}`} aside={<span className={`text-sm font-medium ${JOB_TONE[job.status]}`}>{job.status}</span>}>
            <p className="text-xs text-muted">
              {job.options.preset} preset; {job.options.refresh_data ? "with a data refresh" : "without a data refresh"}
              {job.options.pollutants ? `; ${job.options.pollutants.join(", ")}` : ""}. Started {job.started_at ? formatIST(job.started_at) : "not yet"}
              {job.started_at ? `; ${job.finished_at ? "took" : "running for"} ${duration(job.started_at, job.finished_at, now)}` : ""}.
            </p>
            <ol className="mt-3 space-y-1.5" aria-label="Steps">
              {job.steps.map((s) => (
                <li key={s.name} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className={`rounded border px-1.5 py-0.5 text-xs ${STEP_TONE[s.status]}`}>{s.status}</span>
                  <span>{s.label}</span>
                  {s.started_at && <span className="text-xs text-muted">{duration(s.started_at, s.finished_at, now)}</span>}
                  {s.detail && <span className="text-xs text-danger">{s.detail}</span>}
                </li>
              ))}
            </ol>
            {job.error && <p role="alert" className="mt-3 rounded border border-danger/40 bg-surface-2 p-2 text-sm text-danger">{job.error}</p>}
            {running && (
              <div className="mt-3">
                <Button variant="secondary" onClick={() => act(() => cancelTraining(job.job_id), "Cancelling…")} disabled={busy}>Cancel</Button>
              </div>
            )}
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-accent">Log (last lines)</summary>
              <pre className="mt-2 max-h-72 overflow-auto rounded border border-line bg-surface-2 p-2 text-xs" tabIndex={0}>{job.log_tail || "No output yet."}</pre>
            </details>
          </Section>
        </div>
      )}

      {result && job && (
        <div className="mt-4">
          <Section title="Result: held-out scores">
            <p className="text-sm">
              {result.beat_persistence} of {result.cells_total} models were closer than simply holding the last observation on the held-out period
              {result.did_not_beat_persistence > 0 ? `; ${result.did_not_beat_persistence} were not` : ""}.
            </p>
            <div className="mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Held-out scores of the new models, scrollable">
              <table className="w-full min-w-96 text-left text-xs">
                <caption className="sr-only">Held-out error of each new model against persistence</caption>
                <thead className="border-b border-line uppercase tracking-wider text-muted">
                  <tr>{["Pollutant", "Horizon", "Model", "MAE", "Persistence MAE", "Verdict"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-medium">{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {result.cells.map((c) => (
                    <tr key={`${c.pollutant}-${c.horizon_hours}`}>
                      <td className="px-2 py-1">{c.pollutant}</td>
                      <td className="px-2 py-1">+{c.horizon_hours} h</td>
                      <td className="px-2 py-1">{c.model}</td>
                      <td className="px-2 py-1 font-mono">{c.test ? c.test.mae.toFixed(2) : "n/a"}</td>
                      <td className="px-2 py-1 font-mono">{c.persistence_test ? c.persistence_test.mae.toFixed(2) : "n/a"}</td>
                      <td className={`px-2 py-1 ${c.beats_persistence_on_test === false ? "text-warn" : ""}`}>{c.beats_persistence_on_test === null ? "n/a" : c.beats_persistence_on_test ? "better than persistence" : "not better than persistence"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.cells.some((c) => c.stratified) && (
              <details className="mt-3 rounded border border-line p-2">
                <summary className="cursor-pointer text-sm">Performance by season and by concentration range</summary>
                <p className="mt-2 text-xs text-muted">
                  Seasons use the target hour in IST. Ranges are the CPCB bands of the pollutant applied to the observed value, so they partly reflect regression to the
                  mean. A band with fewer than 30 scored rows shows no score. Skill is 1 − MAE ÷ persistence MAE; negative means worse than holding the last observation.
                </p>
                <div className="mt-2 overflow-x-auto" tabIndex={0} role="region" aria-label="Stratified held-out scores, scrollable">
                  <table className="w-full min-w-96 text-left text-xs">
                    <caption className="sr-only">Held-out error by season and concentration range</caption>
                    <thead className="border-b border-line uppercase tracking-wider text-muted">
                      <tr>{["Model", "Stratum", "n", "MAE", "Persistence MAE", "Skill"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-medium">{h}</th>)}</tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {result.cells.flatMap((c) =>
                        c.stratified
                          ? (["season", "range"] as const).flatMap((kind) =>
                              Object.entries(c.stratified![kind]).map(([name, v]) => (
                                <tr key={`${c.pollutant}-${c.horizon_hours}-${kind}-${name}`}>
                                  <td className="px-2 py-1">{c.pollutant} +{c.horizon_hours} h</td>
                                  <td className="px-2 py-1">{kind}: {name.replace("_", " ")}</td>
                                  <td className="px-2 py-1 font-mono">{v.n.toLocaleString()}</td>
                                  <td className="px-2 py-1 font-mono">{v.mae === null ? "n/a" : v.mae.toFixed(2)}</td>
                                  <td className="px-2 py-1 font-mono">{v.persistence_mae === null ? "n/a" : v.persistence_mae.toFixed(2)}</td>
                                  <td className={`px-2 py-1 font-mono ${v.skill !== null && v.skill < 0 ? "text-warn" : ""}`}>{v.skill === null ? "n/a" : v.skill.toFixed(2)}</td>
                                </tr>
                              )),
                            )
                          : [],
                      )}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
            <p className="mt-2 text-xs text-muted">
              Scores are on a later period the models never saw, measured with the same split rule each time. When the data changed since the active model was
              trained, the test period differs, so these numbers are not a like-for-like comparison with the active model&apos;s.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {job.activated ? (
                <span className="text-sm">This model is active.</span>
              ) : (
                <Button variant="primary" onClick={() => setConfirm("activate")} disabled={busy}>Use this model</Button>
              )}
              <span className="text-xs text-muted">The previous model is kept, so you can go back.</span>
            </div>
          </Section>
        </div>
      )}

      {history.length > 1 && (
        <div className="mt-4">
          <Section title="Earlier jobs">
            <ul className="space-y-1 text-sm">
              {history.map((h) => (
                <li key={h.job_id} className="flex flex-wrap items-center gap-2">
                  <button type="button" className="font-mono text-xs text-accent underline" onClick={() => setWatch(h.job_id)}>{h.job_id}</button>
                  <span className={`text-xs ${JOB_TONE[h.status]}`}>{h.status}</span>
                  {h.activated && <span className="text-xs text-muted">active model came from this job</span>}
                </li>
              ))}
            </ul>
          </Section>
        </div>
      )}

      <Dialog open={confirm === "start"} onClose={() => setConfirm(null)} title="Start training?">
        <p>
          This will {refresh ? "download the newest data, rebuild the features and " : ""}train the {preset === "standard" ? "full set of models" : "quick PM2.5 models"} on this computer.
          {preset === "standard" ? " A standard run takes hours and keeps the processor busy; the rest of the application stays usable but slower." : " A quick run takes minutes."}
        </p>
        <p className="mt-2 text-muted">It does not use Claude or any language model, and the active model is not changed until you choose to use the result.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="primary" disabled={busy} onClick={() => act(async () => {
            const j = await startTraining({ preset, refresh_data: refresh, pollutants: pollutants.length ? pollutants : undefined });
            setWatch(j.job_id);
          }, "Training started.")}>Start</Button>
        </div>
      </Dialog>
      <Dialog open={confirm === "activate"} onClose={() => setConfirm(null)} title="Use this model?">
        <p>The forecasting API will use this model from the next request. The current model stays on disk and you can return to it.</p>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" disabled={busy} onClick={() => job && act(() => activateTraining(job.job_id), "The new model is active.")}>Use this model</Button>
        </div>
      </Dialog>
      <Dialog open={confirm === "rollback"} onClose={() => setConfirm(null)} title="Return to the previous model?">
        <p>The forecasting API will go back to the model that was active before the last change.</p>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" disabled={busy} onClick={() => act(() => rollbackModel(), "Returned to the previous model.")}>Return</Button>
        </div>
      </Dialog>
    </>
  );
}
