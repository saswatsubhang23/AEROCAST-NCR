"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CouplingEffects, EvaluationSummaryPanel, FlowInspector, FlowLegend, MeteorologyChart, RunProvenance, ValidationPanel } from "@/components/flow/FlowPanels";
import { AirFlow3D } from "@/components/flow/AirFlow3DLazy";
import { FlowStage } from "@/components/flow/FlowStageLazy";
import { CAMERA_PRESETS, type CameraPreset } from "@/components/twin/scene3d/cameraPresets";
import { Button } from "@/components/ui/Button";
import { Chip, Dot, GlassPanel, Kicker, Segmented, Toggle } from "@/components/ui/Glass";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { ApiError } from "@/lib/http";
import { fetchCamsFields } from "@/lib/flow/cams";
import { fetchCoupledConfig, runCoupled, type CoupledRun, type CoupledSource, type ProcessKey } from "@/lib/flow/coupled";
import { scaleFor } from "@/lib/flow/field";
import { camsFrames, coupledFrames, nearestWithin, replayFrames, type FlowFrames } from "@/lib/flow/frames";
import { levelStackAt, surfaceStack, type LevelStack } from "@/lib/flow/levels";
import { fetchHeightmap } from "@/lib/terrain/api";
import { sampleBilinear } from "@/lib/twin/fields";
import { fetchTwinStatus, fetchTwinWindow } from "@/lib/twin/api";
import { fetchFields, type FieldsRequest, type FieldsResponse } from "@/lib/twin/fields";
import { defaultWindow } from "@/lib/twin/timeline";
import type { TwinWindow } from "@/lib/twin/types";
import { useOptional } from "@/lib/twin/useOptional";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

type Mode = "replay" | "model" | "coupled";
const SPECIES_LABEL: Record<string, string> = { pm25: "PM2.5", pm10: "PM10", no2: "NO₂", o3: "O₃", so2: "SO₂", ox_ppb: "Ox (O₃ + NO₂)", pm_coarse: "Coarse PM" };
const DENSITY = { low: 1500, normal: 3500, high: 6000 } as const;
const DEFAULT_PROCESSES: ProcessKey[] = ["deposition", "washout", "oxidation"];
const PROCESS_NAME: Record<ProcessKey, string> = {
  ventilation: "Ventilation (boundary layer × wind): lowered skill in tests", deposition: "Dry deposition and settling", washout: "Rain scavenging", oxidation: "SO₂ → sulfate in sunlight", dilution: "One-sided dilution (biases low)",
};
const DAY = 86_400_000;
const ymd = (ms: number) => new Date(ms).toISOString().slice(0, 10);

export default function FlowPage() {
  const status = useResource("twin-status", 0, (s) => fetchTwinStatus(s));
  const coupledConfig = useResource("coupled-config", 0, (s) => fetchCoupledConfig(s));
  const [loadedAt] = useState(() => Date.now());

  const [mode, setMode] = useState<Mode>("replay");
  const [liveVersion, setLiveVersion] = useState(0);
  const [view, setView] = useState<"2d" | "3d">("2d");
  const [preset, setPreset] = useState<CameraPreset>("oblique");
  const [presetToken, setPresetToken] = useState(0);
  const [species, setSpecies] = useState("pm25");
  const [colourBy, setColourBy] = useState<"pollutant" | "wind">("pollutant");
  const [density, setDensity] = useState<keyof typeof DENSITY>("normal");
  const [concOpacity, setConcOpacity] = useState(0.45);
  const [showStations, setShowStations] = useState(true);
  const [paused, setPaused] = useState(false);
  const [resetToken, setResetToken] = useState(0);
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null);

  // coupled run
  const [startFrom, setStartFrom] = useState<CoupledSource>("cams");
  const [lead, setLead] = useState(6);
  const [hours, setHours] = useState(24);
  const [processes, setProcesses] = useState<ProcessKey[]>(DEFAULT_PROCESSES);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [run, setRun] = useState<CoupledRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [lastRunAt, setLastRunAt] = useState<number | null>(null);
  const [initOverride, setInitOverride] = useState<string | null>(null);

  // ---- replay data: stored observations plus the weather-model wind of the same hours
  const replaySpecies = species === "ox_ppb" || species === "pm_coarse" ? "pm25" : species;
  const period = status.status === "ready" ? status.data.periods[replaySpecies] : undefined;
  const range = useMemo(() => (period ? defaultWindow(period.dense_to ?? period.to, 72) : null), [period]);
  const win = useOptional(mode === "replay" && !!range, `flow-win:${replaySpecies}:${range?.to}`, (s) => fetchTwinWindow(replaySpecies as never, range!.from, range!.to, s));
  const winData: TwinWindow | null = win.status === "ready" ? win.data : null;
  const fieldsReq: FieldsRequest | null = useMemo(() => {
    if (!winData) return null;
    const end = new Date(winData.to).getTime();
    const start = new Date(winData.from).getTime();
    const levels = view === "3d";
    if (loadedAt - end > 3 * DAY) return { mode: "historical", start: ymd(start), end: ymd(end), levels };
    return { mode: "forecast", pastDays: Math.ceil((loadedAt - start) / DAY) + 1, levels };
  }, [winData, loadedAt, view]);
  const fieldsKey = fieldsReq ? (fieldsReq.mode === "forecast" ? `f:${fieldsReq.pastDays}:${view}` : `h:${fieldsReq.start}:${fieldsReq.end}:${view}`) : "none";
  const fieldsRes = useOptional(!!fieldsReq, `flow-fields:${fieldsKey}`, (s) => fetchFields(fieldsReq as FieldsRequest, s));
  const fields = fieldsRes.status === "ready" ? fieldsRes.data : null;

  // ---- live model: CAMS fields and the weather-model wind, refreshed on a timer
  const camsRes = useOptional(mode === "model", `flow-cams:${liveVersion}`, (s) => fetchCamsFields(6, 36, s));
  const cams = camsRes.status === "ready" ? camsRes.data : null;
  const liveFieldsRes = useOptional(mode === "model", `flow-live-fields:${liveVersion}:${view}`, (s) => fetchFields({ mode: "forecast", pastDays: 1, levels: view === "3d" }, s));
  const liveFields = liveFieldsRes.status === "ready" ? liveFieldsRes.data : null;
  useEffect(() => {
    if (mode !== "model") return;
    const t = setInterval(() => setLiveVersion((v) => v + 1), 10 * 60_000);
    return () => clearInterval(t);
  }, [mode]);

  // coupled runs start near the present (live, CAMS) or in the stored past; level winds are fetched for the present when the 3D view needs them
  const coupledLevels = useOptional(view === "3d" && mode === "coupled", `flow-coupled-levels:${liveVersion}`, (s) => fetchFields({ mode: "forecast", pastDays: 2, levels: true }, s));
  const terrainRes = useOptional(view === "3d", "flow-terrain", () => fetchHeightmap());
  const terrain = terrainRes.status === "ready" ? terrainRes.data : null;

  // ---- frames: one shape for all kinds of data
  const frames: FlowFrames | null = useMemo(() => {
    if (mode === "replay") return winData ? replayFrames(winData, fields, replaySpecies) : null;
    if (mode === "model") return cams ? camsFrames(cams, liveFields, species === "ox_ppb" || species === "pm_coarse" ? "pm25" : species) : null;
    return run ? coupledFrames(run, species) : null;
  }, [mode, winData, fields, replaySpecies, cams, liveFields, run, species]);
  const framesKey = frames ? `${frames.kind}:${frames.species}:${frames.times[0]}:${frames.times.length}:${run?.run_id ?? ""}` : "";
  const defaultK = frames ? (frames.kind === "replay" ? frames.times.length - 1 : frames.kind === "model" ? (cams?.now_index ?? 0) : 0) : 0;
  const [kSel, setKSel] = useState<{ key: string; k: number } | null>(null);
  const k = frames ? Math.min(kSel && kSel.key === framesKey ? kSel.k : defaultK, frames.times.length - 1) : 0;
  const setK = useCallback((n: number) => setKSel({ key: framesKey, k: n }), [framesKey]);

  // ---- playback
  const kRef = useRef(k);
  useEffect(() => {
    kRef.current = k;
  });
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing || !frames || frames.times.length < 2) return;
    const t = setInterval(() => {
      const next = kRef.current + 1;
      if (next >= frames.times.length) {
        setPlaying(false);
        return;
      }
      setKSel({ key: framesKey, k: next });
    }, 700);
    return () => clearInterval(t);
  }, [playing, frames, framesKey]);

  // ---- coupled runs
  const doRun = useCallback(
    async (from: CoupledSource, quiet = false) => {
      if (!quiet) setBusy(true);
      setRunError(null);
      try {
        const body = {
          source: from, hours, processes, focus: species === "ox_ppb" ? "pm25" : species,
          validate_against_observations: from === "observations" || from === "model_forecast",
          ...(from === "model_forecast" ? { lead_hours: lead } : {}),
          ...(from === "observations" && initOverride ? { init_time: initOverride } : {}),
        };
        const r = await runCoupled(body);
        setRun(r);
        setLastRunAt(Date.now());
        setMode("coupled");
        setPlaying(false);
      } catch (e) {
        if (!quiet) setRun(null);
        setRunError(e instanceof ApiError ? e.message : "The run could not be completed.");
      } finally {
        setBusy(false);
      }
    },
    [hours, processes, species, lead, initOverride],
  );
  const runLive = run?.source === "live" || run?.source === "cams";
  useEffect(() => {
    if (mode !== "coupled" || !runLive || !autoRefresh) return;
    const from: CoupledSource = run?.source === "cams" ? "cams" : "live";
    const t = setInterval(() => void doRun(from, true), 10 * 60_000);
    return () => clearInterval(t);
  }, [mode, runLive, autoRefresh, doRun, run?.source]);

  // ---- 3D inputs: the wind at every available height for this hour, and the mixed-layer depth
  const windFields: FieldsResponse | null = mode === "replay" ? fields : mode === "model" ? liveFields : coupledLevels.status === "ready" ? coupledLevels.data : null;
  const windIdx = frames && windFields ? nearestWithin(windFields.times, frames.times[k], 90 * 60_000) : -1;
  const stack: LevelStack | null = useMemo(() => {
    if (view !== "3d" || !frames) return null;
    if (windFields && windIdx >= 0) {
      const st = levelStackAt(windFields, windIdx);
      if (st) return st;
    }
    const w = frames.windAt(k);
    return w ? surfaceStack(w) : null;
  }, [view, frames, windFields, windIdx, k]);
  const blh = useMemo(() => {
    if (view !== "3d") return null;
    if (windFields && windIdx >= 0) {
      const g = windFields.variables.boundary_layer_height?.values[windIdx];
      if (g) return { grid: g, lats: windFields.grid.lats, lons: windFields.grid.lons };
    }
    if (run && mode === "coupled") {
      const g = run.wind.boundary_layer_height_m?.[Math.min(k, run.wind.boundary_layer_height_m.length - 1)];
      if (g) return { grid: g, lats: run.wind.lats, lons: run.wind.lons };
    }
    return null;
  }, [view, windFields, windIdx, run, mode, k]);
  const blhAt = useCallback((lat: number, lon: number) => (blh ? sampleBilinear(blh.grid, { lats: blh.lats, lons: blh.lons }, lat, lon) : null), [blh]);
  const blhMean = useMemo(() => {
    if (!blh) return null;
    const v = blh.grid.flat().filter((x): x is number => x !== null);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  }, [blh]);

  const speciesOptions = useMemo(() => {
    const available = mode === "coupled" && run ? Object.keys(run.species).filter((s) => s !== "pm_coarse") : mode === "model" ? ["pm25", "pm10", "no2", "o3", "so2", "co", "dust"] : ["pm25", "pm10", "no2", "o3", "so2"];
    return available.map((s) => ({ value: s, label: SPECIES_LABEL[s] ?? s }));
  }, [mode, run]);
  const shownSpecies = frames?.species ?? species;
  const scale = scaleFor(shownSpecies);

  const ageHours = mode === "replay" && winData ? (loadedAt - new Date(winData.to).getTime()) / 3_600_000 : mode === "model" ? 0 : run ? run.freshness.initial_state_age_hours : null;
  const live = mode === "model" || (mode === "coupled" && (run?.source === "live" || run?.source === "cams") && !run.freshness.stale);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <Kicker>Air flow</Kicker>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Air moving over Delhi-NCR</h1>
          <p className="mt-1 text-sm text-muted">
            Wind carries the particles; colour is the concentration of the air they are in. Nothing is drawn where there is no value.{" "}
            <Link href="/report?a=air-quality-in-delhi-ncr" className="text-accent hover:underline">How to read this</Link>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone={live ? "ok" : ageHours !== null && ageHours > 6 ? "warn" : "neutral"} icon={<Dot tone={live ? "ok" : ageHours !== null && ageHours > 6 ? "warn" : "idle"} />}>
            {mode === "replay" ? "Replay of stored observations" : mode === "model" ? "Live atmospheric model (CAMS), updated hourly" : run?.source === "live" ? (live ? "Live readings" : "Live feed is stale") : run?.source === "cams" ? "Started from the live CAMS field" : run?.source === "model_forecast" ? "Trained-model forecast" : "Stored hour"}
          </Chip>
          {mode === "model" && cams && <Chip tone="neutral" title="When the model fields were last fetched">fetched {new Date(cams.source.retrieved_at).toLocaleTimeString()}</Chip>}
          {mode !== "model" && ageHours !== null && <Chip tone={ageHours > 6 ? "warn" : "neutral"}>{ageHours < 1 ? "under 1 h old" : `${ageHours < 48 ? ageHours.toFixed(0) + " h" : (ageHours / 24).toFixed(1) + " days"} old`}</Chip>}
          <Link href="/data" className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-accent/60 hover:text-fg">Data gaps</Link>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_21rem]">
        {/* ---------------------------------------------------------------- stage */}
        <div className="min-w-0 space-y-3">
          {frames && (
            <div className="flex flex-wrap items-center gap-2">
              <Segmented label="View" size="sm" value={view} onChange={setView} options={[{ value: "2d", label: "2D map" }, { value: "3d", label: "3D terrain" }]} />
              {view === "3d" && (
                <div role="group" aria-label="Camera presets" className="flex flex-wrap gap-1">
                  {(Object.keys(CAMERA_PRESETS) as CameraPreset[]).map((c) => (
                    <button key={c} type="button" aria-pressed={preset === c} onClick={() => { setPreset(c); setPresetToken((x) => x + 1); }}
                      className={`rounded-md px-2.5 py-1 text-xs ${preset === c ? "bg-accent text-bg" : "bg-surface-2 text-fg hover:bg-line"}`}>{CAMERA_PRESETS[c].label}</button>
                  ))}
                </div>
              )}
              {view === "3d" && terrainRes.status === "error" && <span className="text-xs text-warn">Terrain could not be built; the ground is flat.</span>}
            </div>
          )}
          {frames && view === "3d" ? (
            <AirFlow3D
              terrain={terrain} stack={stack} scalar={frames.scalarAt(k) ? { ...frames.scalarAt(k)!, scale } : null} blhAt={blhAt} blhMean={blhMean} colourBy={colourBy}
              count={Math.round(DENSITY[density] * 0.6)} paused={paused} concentrationOpacity={concOpacity} preset={preset} presetToken={presetToken}
              onPick={(lat, lon) => setPicked({ lat, lon })}
            />
          ) : frames ? (
            <FlowStage
              frames={frames} k={k} scale={scale} colourBy={colourBy} particles={DENSITY[density]} concentrationOpacity={concOpacity} flowOpacity={0.95} paused={paused}
              showStations={showStations && frames.kind === "replay"} secondsPerFrame={140} resetToken={resetToken} onPick={setPicked} picked={picked}
              corner={
                <>
                  <GlassPanel className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 px-3 py-1.5 text-xs">
                    <ProvenanceBadge kind={mode === "replay" ? "estimate" : mode === "model" ? "atmospheric_model" : "simulated"} />
                    <span className="font-mono tabular">{formatIST(frames.times[k])}</span>
                  </GlassPanel>
                  <GlassPanel className="pointer-events-none absolute bottom-3 right-3 hidden w-64 p-3 sm:block">
                    <FlowLegend scale={scale} unit={frames.unit} colourBy={colourBy} />
                  </GlassPanel>
                </>
              }
            />
          ) : mode === "model" ? (
            camsRes.status === "error" ? <ErrorState title="The live model field is unavailable" message={camsRes.error.message} /> : <LoadingState label="Fetching the current model fields" />
          ) : mode === "replay" ? (
            status.status === "loading" || win.status === "loading" || win.status === "idle" ? (
              <LoadingState label="Opening the stored observations" />
            ) : (
              <ErrorState title="No stored observations to replay" message={status.status === "error" ? status.error.message : win.status === "error" ? win.error.message : "The store has no data for this pollutant."} />
            )
          ) : busy ? (
            <LoadingState label="Running the coupled model (20 to 60 s; a trained-model start can take a few minutes the first time)" />
          ) : (
            <div className="grid h-[min(72vh,640px)] min-h-[380px] place-items-center rounded-xl border border-dashed border-line p-6 text-center">
              <div className="max-w-md">
                <p className="text-lg font-medium">No run yet</p>
                <p className="mt-1 text-sm text-muted">Choose where the air starts from and press Run. Until then nothing is drawn, and no field is invented.</p>
              </div>
            </div>
          )}
          {runError && <ErrorState title="The coupled model could not run" message={runError} />}
          {mode === "replay" && winData && fieldsRes.status === "error" && <p role="status" className="rounded-lg border border-warn/40 p-3 text-sm text-warn">The weather-model wind could not be loaded, so the air is shown without flow. {fieldsRes.error.message}</p>}
          {frames && frames.windMissing > 0 && mode === "replay" && <p role="status" className="text-xs text-muted">{frames.windMissing} of {frames.times.length} hours have no weather-model wind in the loaded window; those hours show no flow.</p>}

          {frames && (
            <GlassPanel className="p-3" role="group" aria-label="Timeline">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant={playing ? "secondary" : "primary"} aria-pressed={playing} onClick={() => { if (!playing && k >= frames.times.length - 1) setK(0); setPlaying(!playing); }} disabled={frames.times.length < 2}>
                  {playing ? "Pause" : "Play hours"}
                </Button>
                <Button size="sm" variant="secondary" aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? "Resume flow" : "Freeze flow"}</Button>
                <Button size="sm" variant="ghost" onClick={() => setResetToken((x) => x + 1)}>Reset view</Button>
                <span className="ml-auto font-mono text-xs text-muted tabular">{formatIST(frames.times[k])}</span>
              </div>
              <input
                type="range" min={0} max={Math.max(frames.times.length - 1, 0)} value={k} onChange={(e) => { setPlaying(false); setK(Number(e.target.value)); }}
                aria-label="Hour" aria-valuetext={formatIST(frames.times[k])} className="mt-2 w-full accent-[var(--accent)]" disabled={frames.times.length < 2}
              />
              <div className="flex justify-between font-mono text-[11px] text-muted"><span>{formatIST(frames.times[0])}</span><span>{formatIST(frames.times[frames.times.length - 1])}</span></div>
            </GlassPanel>
          )}
        </div>

        {/* ---------------------------------------------------------------- controls */}
        <aside className="min-w-0 space-y-4" aria-label="Controls">
          <section className="card space-y-3 p-4">
            <Kicker>Where the air comes from</Kicker>
            <Segmented
              label="Data source" value={mode} onChange={(m) => { setMode(m); setPlaying(false); }}
              options={[
                { value: "replay", label: "Stored replay", hint: "Station observations from the store, hour by hour" },
                { value: "model", label: "Live model", hint: "The CAMS atmospheric-chemistry model, updated hourly" },
                { value: "coupled", label: "Coupled model", hint: "Carried and changed by weather and chemistry" },
              ]}
            />
            {mode === "model" ? (
              <p className="text-xs leading-relaxed text-muted">CAMS model, hourly, refreshed every 10 minutes. The only current source (stations lag by days), but a model, not a measurement.</p>
            ) : mode === "replay" ? (
              <p className="text-xs leading-relaxed text-muted">72 h of stored station observations{period ? `, newest ${formatIST(period.dense_to ?? period.to)}` : ""}, with the model wind of each hour.</p>
            ) : (
              <div className="space-y-3">
                <Segmented
                  label="Start from" size="sm" value={startFrom} onChange={setStartFrom}
                  options={[
                    { value: "cams", label: "Live model", hint: "The current CAMS model field (hourly, no gaps)" },
                    { value: "live", label: "Live stations", hint: "Newest OpenAQ readings, with their ages (the feed often lags by days)" },
                    { value: "model_forecast", label: "Trained model", hint: "The trained model's station forecasts" },
                    { value: "observations", label: "Stored hour", hint: "The newest well-covered hour in the store" },
                  ]}
                />
                {startFrom === "model_forecast" && (
                  <label className="flex items-center gap-2 text-xs text-muted">
                    Forecast lead
                    <select value={lead} onChange={(e) => setLead(Number(e.target.value))} className="h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
                      {[1, 6, 24].map((h) => <option key={h} value={h}>+{h} h</option>)}
                    </select>
                  </label>
                )}
                <label className="flex items-center gap-2 text-xs text-muted">
                  Run for
                  <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
                    {[12, 24, 36].map((h) => <option key={h} value={h}>{h} hours</option>)}
                  </select>
                </label>
                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs text-muted">Couplings</legend>
                  {(["ventilation", "deposition", "washout", "oxidation", "dilution"] as ProcessKey[]).map((p) => (
                    <Toggle key={p} label={PROCESS_NAME[p]} checked={processes.includes(p)} onChange={(on) => setProcesses(on ? [...processes, p] : processes.filter((x) => x !== p))} />
                  ))}
                </fieldset>
                <Button variant="primary" className="w-full" onClick={() => void doRun(startFrom)} disabled={busy}>{busy ? "Running…" : run ? "Run again" : "Run the coupled model"}</Button>
                {(startFrom === "live" || startFrom === "cams") && <Toggle label="Refresh every 10 minutes" checked={autoRefresh} onChange={setAutoRefresh} hint="A new run is requested when the live readings or the weather data change" />}
                {lastRunAt && <p className="text-[11px] text-muted">Last run {new Date(lastRunAt).toLocaleTimeString()}.</p>}
              </div>
            )}
            {mode === "replay" && (
              <div className="space-y-2 border-t border-line pt-3">
                <p className="text-xs text-muted">Carry this air forward:</p>
                <Button size="sm" className="w-full" onClick={() => { setStartFrom("observations"); setInitOverride(frames ? frames.times[k] : null); void doRun("observations"); }} disabled={busy || !frames}>
                  {busy ? "Running…" : "Run the coupled model from this hour"}
                </Button>
              </div>
            )}
          </section>

          <section className="card space-y-3 p-4">
            <Kicker>What you see</Kicker>
            <label className="block text-xs text-muted">
              Species
              <select value={species} onChange={(e) => setSpecies(e.target.value)} className="mt-1 h-9 w-full rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
                {speciesOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <Segmented label="Colour the flow by" size="sm" value={colourBy} onChange={setColourBy} options={[{ value: "pollutant", label: "Concentration" }, { value: "wind", label: "Wind speed" }]} />
            <Segmented label="Particles" size="sm" value={density} onChange={setDensity} options={[{ value: "low", label: "Few" }, { value: "normal", label: "Normal" }, { value: "high", label: "Dense" }]} />
            <label className="block text-xs text-muted">
              Concentration field {Math.round(concOpacity * 100)}%
              <input type="range" min={0} max={0.9} step={0.05} value={concOpacity} onChange={(e) => setConcOpacity(Number(e.target.value))} className="mt-1 w-full accent-[var(--accent)]" />
            </label>
            <Toggle label="Station markers (stored replay only)" checked={showStations} onChange={setShowStations} />
          </section>

          <section className="card space-y-2 p-4">
            <Kicker>Air at the point you click</Kicker>
            {frames ? <FlowInspector frames={frames} k={k} scale={scale} picked={picked} run={mode === "coupled" ? run : null} /> : <p className="text-sm text-muted">Nothing to inspect yet.</p>}
          </section>
        </aside>
      </div>

      {/* ---------------------------------------------------------------- explanation */}
      {frames && (
        <details className="card group px-4 py-3 text-sm">
          <summary className="cursor-pointer list-none text-muted hover:text-fg">
            <span className="font-medium text-fg">How this field was made</span> <span className="text-xs">· click to read</span>
          </summary>
          <p className="mt-2 text-muted">{frames.fieldMethod}</p>
        </details>
      )}
      {mode === "coupled" && run && (
        <p role="note" className="flex flex-wrap items-center gap-2 text-sm">
          <Chip tone="warn">Not validated as a forecast</Chip>
          <span className="text-muted">No emissions in the model; see “Track record” below.</span>
        </p>
      )}
      {mode === "coupled" && run && (
        <Tabs defaultValue="effects" className="card p-4">
          <TabsList aria-label="Coupled run details">
            <TabsTrigger value="effects">What the couplings did</TabsTrigger>
            <TabsTrigger value="validation">This run vs observations</TabsTrigger>
            <TabsTrigger value="evidence">Track record</TabsTrigger>
            <TabsTrigger value="met">Weather</TabsTrigger>
            <TabsTrigger value="about">Data and limits</TabsTrigger>
          </TabsList>
          <TabsContent value="effects" className="pt-4"><CouplingEffects run={run} /></TabsContent>
          <TabsContent value="validation" className="pt-4"><ValidationPanel run={run} /></TabsContent>
          <TabsContent value="evidence" className="pt-4"><EvaluationSummaryPanel evaluation={coupledConfig.status === "ready" ? coupledConfig.data.evaluation : null} /></TabsContent>
          <TabsContent value="met" className="pt-4"><MeteorologyChart run={run} k={k} onSeek={(i) => { setPlaying(false); setK(i); }} /></TabsContent>
          <TabsContent value="about" className="pt-4"><RunProvenance run={run} /></TabsContent>
        </Tabs>
      )}
    </div>
  );
}
