"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FieldInspector } from "@/components/twin/FieldInspector";
import { CAMERA_PRESETS, Scene3D, type CameraPreset } from "@/components/twin/scene3d/Scene3DLazy";
import { SceneNotes } from "@/components/twin/scene3d/SceneNotes";
import { LayerPanel, LegendPanel } from "@/components/twin/LayerPanel";
import { RegimePanel } from "@/components/twin/RegimePanel";
import { RiskPanel } from "@/components/twin/RiskPanel";
import { SimulationInspector } from "@/components/twin/SimulationInspector";
import { RunSummary, SimulationControls, type SimMode } from "@/components/twin/SimulationPanel";
import { StationCharts, type BacktestState } from "@/components/twin/StationCharts";
import { SPEEDS, TimelineControls } from "@/components/twin/TimelineControls";
import { TwinMap } from "@/components/twin/TwinMapLazy";
import { Button } from "@/components/ui/Button";
import { FilterBar, SelectField } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Tooltip } from "@/components/ui/Tooltip";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { ApiError } from "@/lib/http";
import { fetchHeightmap } from "@/lib/terrain/api";
import { fetchBacktest, fetchTwinEstimate, fetchTwinStatus, fetchTwinWindow } from "@/lib/twin/api";
import { framesFromBacktest } from "@/lib/twin/contract";
import { fetchFields, nearestIndex, type FieldsRequest } from "@/lib/twin/fields";
import { buildSceneData } from "@/lib/twin/scene/data";
import { buildLayers, legendsFor, scalesFor, windFor } from "@/lib/twin/layers/definitions";
import type { LayerContext } from "@/lib/twin/layers/types";
import { BASELINE_SCENARIO, fetchEstimateValidation, fetchLiveSimulation, runSimulation, type EstimateValidation, type SimScenario, type SimulationRun } from "@/lib/twin/simulation";
import { twinStore, useTwinState, type TwinDisplay, type TwinLens } from "@/lib/twin/store";
import { defaultWindow, observedCount, stepIndex } from "@/lib/twin/timeline";
import type { TwinEstimate, TwinMode, TwinPollutant, TwinStatus } from "@/lib/twin/types";
import { useOptional, type Optional } from "@/lib/twin/useOptional";
import { TWIN_VARIABLES, variableLabel } from "@/lib/twin/variables";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

const MODE_HELP: Record<TwinMode, string> = {
  observed: "Hourly station observations, as reported. Missing hours are shown as hollow rings.",
  weather: "Weather-model wind at each station point. It shows air movement, not where pollution goes.",
  estimate: "An interpolation between stations (inverse-distance weighting) with its measured leave-one-out error.",
  forecast: "A trained model's forecast for the selected station from the chosen hour, next to later observations.",
  transport: "Not available: no validated pollutant-transport model exists.",
};

const LENS_HELP: Record<TwinLens, string> = {
  stations: "Station observations, spatial estimates and the model forecasts.",
  atmosphere: "Weather-model fields: precipitation, pressure, wind and more.",
  simulation: "Observed air carried by the model wind; scenarios; live.",
};

const WINDOWS = [
  { hours: 72, label: "72 hours" },
  { hours: 168, label: "7 days" },
];

export default function TwinPage() {
  const status = useResource("twin-status", 0, (s) => fetchTwinStatus(s));
  return (
    <>
      <PageHeader
        title="Digital Twin"
        description="Stored station observations, weather-model fields, simulations and the trained model's forecasts on one timeline. A replay of data as ingested, not a live feed."
      />
      {status.status === "loading" && <LoadingState label="Opening the historical store" />}
      {status.status === "error" && (
        <ErrorState
          title={status.error.code === "twin_data_unavailable" ? "No historical data is available" : "The workspace could not be opened"}
          message={status.error.message}
        />
      )}
      {status.status === "ready" && (status.data.pollutants.length === 0 ? <EmptyState title="The store has no usable observations" message="Run the historical pipeline first." /> : <Workspace status={status.data} />)}
    </>
  );
}

function Workspace({ status }: { status: TwinStatus }) {
  // ---- shared state: the same store the 3D scene reads and writes
  const lens = useTwinState((s) => s.lens);
  const display = useTwinState((s) => s.display);
  const selectedTime = useTwinState((s) => s.selectedTime);
  const playing = useTwinState((s) => s.playing);
  const speedIndex = useTwinState((s) => s.speedIndex);
  const variable = useTwinState((s) => s.variable);
  const location = useTwinState((s) => s.location);
  const layerSettings = useTwinState((s) => s.layers);

  // ---- state that belongs to this page only
  const [hours, setHours] = useState(72);
  const [mode, setMode] = useState<TwinMode>("observed");
  const [timeMode, setTimeMode] = useState<"forecast" | "historical">("forecast");
  const [loadedAt] = useState(() => Date.now()); // fixed at mount: render stays pure
  const [histStart, setHistStart] = useState(() => new Date(loadedAt - 6 * 86400_000).toISOString().slice(0, 10));
  const [resetToken, setResetToken] = useState(0);
  const [preset, setPreset] = useState<CameraPreset>("oblique");
  const [presetToken, setPresetToken] = useState(0);
  const [simMode, setSimMode] = useState<SimMode>("transport");
  const [simHours, setSimHours] = useState(24);
  const [simScenario, setSimScenario] = useState<SimScenario>(BASELINE_SCENARIO);
  const [simRun, setSimRun] = useState<SimulationRun | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);
  const [simNote, setSimNote] = useState<string | null>(null);

  // The variable must be one the store of observations can serve; fall back to PM2.5 or the first available one.
  const pollutant: TwinPollutant = status.pollutants.includes(variable) ? variable : status.pollutants.includes("pm25") ? "pm25" : status.pollutants[0];
  const isAqi = pollutant === "aqi";
  const effectiveMode: TwinMode = isAqi && (mode === "estimate" || mode === "forecast") ? "observed" : mode;

  const range = useMemo(() => defaultWindow(status.periods[pollutant]?.dense_to ?? status.to, hours), [status.periods, status.to, pollutant, hours]);
  const win = useResource(`twin-window:${pollutant}:${range.from}:${range.to}`, 0, (s) => fetchTwinWindow(pollutant, range.from, range.to, s));
  const w = win.status === "ready" ? win.data : null;
  const count = w?.times.length ?? 0;
  const i = selectedTime && w ? nearestIndex(w.times, selectedTime) : Math.max(count - 1, 0);

  // Atmospheric fields: only requested while the Atmosphere lens is open; a superseded request is aborted by useOptional.
  const fieldsReq: FieldsRequest = useMemo(() => {
    if (timeMode === "forecast") return { mode: "forecast" };
    const end = new Date(new Date(histStart + "T00:00:00Z").getTime() + 2 * 86400_000).toISOString().slice(0, 10);
    return { mode: "historical", start: histStart, end };
  }, [timeMode, histStart]);
  const fieldsKey = fieldsReq.mode === "forecast" ? "forecast" : `hist:${fieldsReq.start}:${fieldsReq.end}`;
  const fieldsRes = useOptional(lens === "atmosphere", `fields:${fieldsKey}`, (sig) => fetchFields(fieldsReq, sig));
  const fields = fieldsRes.status === "ready" ? fieldsRes.data : null;
  const fi = fields ? (selectedTime ? nearestIndex(fields.times, selectedTime) : (fields.now_index ?? Math.max(fields.times.length - 1, 0))) : 0;

  const simTimes = simRun?.valid_times;
  const si = simRun && selectedTime ? nearestIndex(simRun.valid_times, selectedTime) : 0;

  // Default selection: the station with the most observed hours, unless one was picked.
  const selectedId = useMemo(() => {
    if (location?.stationId != null) return location.stationId;
    if (!w || w.stations.length === 0) return null;
    // the station with the most observed hours inside the displayed window (a station with a long history may have none here)
    const counts: number[] = w.values.map((row) => row.filter((v) => v !== null).length);
    let best = 0;
    counts.forEach((c, ki) => {
      if (c > counts[best]) best = ki;
    });
    return w.stations[best].station_id;
  }, [location, w]);
  const k = w ? w.stations.findIndex((s) => s.station_id === selectedId) : -1;

  // ---- playback along the active lens's own time axis
  const activeTimes = useMemo(() => (lens === "simulation" ? (simTimes ?? []) : lens === "atmosphere" ? (fields?.times ?? []) : (w?.times ?? [])), [lens, fields, w, simTimes]);
  const activeIndex = lens === "simulation" ? si : lens === "atmosphere" ? fi : i;
  useEffect(() => {
    if (!playing || activeTimes.length === 0) return;
    const t = setInterval(() => {
      const cur = twinStore.getState().selectedTime;
      const at = cur ? nearestIndex(activeTimes, cur) : activeIndex;
      const next = stepIndex(at, 1, activeTimes.length);
      twinStore.setTime(activeTimes[next]);
      if (next >= activeTimes.length - 1) twinStore.setPlaying(false);
    }, SPEEDS[speedIndex].ms);
    return () => clearInterval(t);
  }, [playing, speedIndex, activeTimes, activeIndex]);

  // Estimates and forecasts are only requested for the hour the timeline rests on (debounced while scrubbing or playing).
  const [settled, setSettled] = useState(i);
  useEffect(() => {
    const t = setTimeout(() => setSettled(i), 250);
    return () => clearTimeout(t);
  }, [i]);
  const settledTime = w?.times[Math.min(settled, count - 1)] ?? null;
  const estimate = useOptional(lens === "stations" && effectiveMode === "estimate" && !isAqi && !!settledTime, `est:${pollutant}:${settledTime}`, (s) => fetchTwinEstimate(pollutant, settledTime as string, s));
  const backtest = useOptional(lens === "stations" && effectiveMode === "forecast" && !isAqi && !!settledTime && selectedId !== null, `bt:${pollutant}:${selectedId}:${settledTime}`, (s) => fetchBacktest(pollutant, selectedId as number, settledTime as string, s));
  const backtestState: BacktestState = backtest.status === "idle" ? { status: "idle" } : backtest.status === "loading" ? { status: "loading" } : backtest.status === "error" ? { status: "error", error: backtest.error } : { status: "ready", data: backtest.data };

  // ---- simulation runs
  const initHour = w ? w.times[i] : null;
  const runNow = useCallback(async () => {
    if (!initHour || pollutant === "aqi") return;
    setSimBusy(true);
    setSimError(null);
    setSimNote(null);
    try {
      const run = simMode === "live"
        ? await fetchLiveSimulation(pollutant, simHours)
        : await runSimulation({ mode: simMode, pollutant, hours: simHours, init_time: initHour, scenario: simMode === "scenario" ? simScenario : undefined });
      setSimRun(run);
      twinStore.setTime(run.valid_times[0]);
      twinStore.setPlaying(false);
    } catch (e) {
      setSimRun(null);
      setSimError(e instanceof ApiError ? e.message : "The simulation could not be run.");
    } finally {
      setSimBusy(false);
    }
  }, [initHour, simMode, pollutant, simHours, simScenario]);

  // Live mode: ask again every five minutes. The server returns the same run id until the observations or the wind data change, so the
  // map is only touched when something new actually exists.
  useEffect(() => {
    if (lens !== "simulation" || simMode !== "live" || !simRun?.live || pollutant === "aqi") return;
    const ac = new AbortController();
    const id = setInterval(() => {
      fetchLiveSimulation(pollutant, simHours, ac.signal)
        .then((run) => {
          setSimRun((cur) => {
            if (cur && cur.run_id === run.run_id) return cur;
            setSimNote(`Updated at ${new Date().toLocaleTimeString()}: new observations or wind data produced a new run.`);
            return run;
          });
        })
        .catch(() => undefined);
    }, 300_000);
    return () => {
      clearInterval(id);
      ac.abort();
    };
  }, [lens, simMode, simRun?.live, pollutant, simHours]);

  // ---- the layer registry turns state into drawable layers, legends and the wind field
  const instant = lens === "simulation" ? (simRun?.valid_times[si] ?? null) : lens === "atmosphere" ? (fields?.times[fi] ?? null) : (w?.times[i] ?? null);
  const ctx: LayerContext = useMemo(
    () => ({
      lens, mode: effectiveMode, variable: pollutant, time: instant, location, now: loadedAt,
      stations: w ? { window: w, index: i } : null,
      estimate: estimate.status === "ready" ? estimate.data : null,
      fields: fields ? { data: fields, index: fi } : null,
      sim: simRun ? { run: simRun, index: si } : null,
      forecast: backtest.status === "ready" ? framesFromBacktest(backtest.data) : null,
    }),
    [lens, effectiveMode, pollutant, instant, location, loadedAt, w, i, estimate, fields, fi, simRun, si, backtest],
  );
  const scales = useMemo(() => scalesFor(ctx), [ctx]);
  const layers = useMemo(() => buildLayers(ctx, layerSettings, scales), [ctx, layerSettings, scales]);
  const wind = useMemo(() => windFor(ctx, layerSettings, "map"), [ctx, layerSettings]);
  const surface = display === "map" ? "map" : display === "scene3d" ? "scene" : undefined; // compare shows both, so every layer is listed
  const legends = useMemo(() => legendsFor(ctx, layerSettings, scales, surface), [ctx, layerSettings, scales, surface]);
  // Real terrain for the 3D scene: requested only when a 3D display is open, fetched once per page life. If it cannot be built the scene
  // is drawn on flat ground and says so (nothing is substituted).
  const terrainRes = useOptional(display !== "map", "terrain", () => fetchHeightmap());
  const terrain = terrainRes.status === "ready" ? terrainRes.data : null;
  const terrainState = terrainRes.status === "ready" ? "ready" : terrainRes.status === "error" ? "unavailable" : "loading";
  const sceneData = useMemo(() => (display === "map" ? null : buildSceneData(ctx, layerSettings, scales, terrain)), [display, ctx, layerSettings, scales, terrain]);

  const tooltipFor = useCallback(
    (object: unknown) => {
      const o = object as { station_id?: number; name?: string; zone?: string | null; agency?: string | null };
      if (!w || typeof o.station_id !== "number") return null;
      const kk = w.stations.findIndex((s) => s.station_id === o.station_id);
      const v = kk >= 0 ? w.values[kk]?.[i] ?? null : null;
      return `<div style="font-weight:600">${o.name ?? ""}</div><div style="color:#9db0cc">${o.zone ?? ""}${o.agency ? ` · ${o.agency}` : ""}</div>
        <div style="margin-top:4px">${variableLabel(w.pollutant)}: ${v === null ? "no usable observation at this hour" : `<b>${v.toFixed(isAqi ? 0 : 1)} ${w.unit}</b>`}</div>
        <div>${formatIST(w.times[i])}</div><div style="color:#9db0cc;margin-top:4px">Click to select</div>`;
    },
    [w, i, isAqi],
  );

  const pickStation = useCallback(
    (id: number) => {
      const s = w?.stations.find((x) => x.station_id === id);
      if (s && lens === "stations") twinStore.setLocation({ lat: s.lat, lon: s.lon, stationId: id });
    },
    [w, lens],
  );
  const pickPoint = useCallback((p: { lat: number; lon: number }) => {
    if (twinStore.getState().lens !== "stations") twinStore.setLocation({ ...p, stationId: null });
  }, []);

  const pickSceneStation = useCallback((id: number | string, lat: number, lon: number) => {
    twinStore.setLocation({ lat, lon, stationId: typeof id === "number" ? id : null });
  }, []);
  const pickScenePoint = useCallback((lat: number, lon: number) => twinStore.setLocation({ lat, lon, stationId: null }), []);

  const changeVariable = (v: string) => {
    twinStore.setVariable(v as TwinPollutant);
    twinStore.setTime(null);
    twinStore.setLocation(null);
    setSimRun(null);
  };

  const badgeKind = lens === "simulation" ? (simRun ? (simRun.mode === "scenario" ? "hypothetical" : "simulated") : "unavailable")
    : lens === "atmosphere" ? (fields ? "weather_forecast" : "unavailable")
    : isAqi ? "derived" : effectiveMode === "estimate" ? "estimate" : effectiveMode === "weather" ? "weather_forecast" : "observed";

  const showTimeline = lens === "stations" || (lens === "atmosphere" && !!fields) || (lens === "simulation" && !!simRun);
  const point = location && location.stationId === null ? { lat: location.lat, lon: location.lon } : location ? { lat: location.lat, lon: location.lon } : null;

  return (
    <>
      <FilterBar>
        <div className="flex flex-col gap-1 text-xs font-medium text-muted">
          View
          <Tabs value={lens} onValueChange={(v) => twinStore.setLens(v as TwinLens)}>
            <TabsList aria-label="Map view">
              <TabsTrigger value="stations">Stations</TabsTrigger>
              <TabsTrigger value="atmosphere">Atmosphere</TabsTrigger>
              <TabsTrigger value="simulation">Simulation</TabsTrigger>
            </TabsList>
            {(Object.keys(LENS_HELP) as TwinLens[]).map((l) => (
              <TabsContent key={l} value={l} className="mt-1 max-w-48 text-xs font-normal text-muted">
                {LENS_HELP[l]}
              </TabsContent>
            ))}
          </Tabs>
        </div>
        <div className="flex flex-col gap-1 text-xs font-medium text-muted">
          Display
          <Tabs value={display} onValueChange={(v) => twinStore.setDisplay(v as TwinDisplay)}>
            <TabsList aria-label="Display">
              <TabsTrigger value="map">Map</TabsTrigger>
              <TabsTrigger value="scene3d">3D</TabsTrigger>
              <TabsTrigger value="compare">Compare</TabsTrigger>
            </TabsList>
            <TabsContent value="map" className="mt-1 max-w-48 text-xs font-normal text-muted">The geographic map.</TabsContent>
            <TabsContent value="scene3d" className="mt-1 max-w-48 text-xs font-normal text-muted">The 3D scene with an altitude axis.</TabsContent>
            <TabsContent value="compare" className="mt-1 max-w-48 text-xs font-normal text-muted">Map and 3D side by side, one shared state.</TabsContent>
          </Tabs>
        </div>
        {lens === "atmosphere" && (
          <>
            <SelectField label="Time mode" value={timeMode} onChange={(v) => { setTimeMode(v as "forecast" | "historical"); twinStore.setPlaying(false); }}
              options={[{ value: "forecast", label: "Recent and forecast" }, { value: "historical", label: "Historical (archive)" }]} />
            {timeMode === "historical" && (
              <label className="flex flex-col gap-1 text-xs font-medium text-muted">
                First day (3 days shown)
                <input type="date" value={histStart} max={new Date(loadedAt - 86400_000 * 3).toISOString().slice(0, 10)} onChange={(e) => e.target.value && setHistStart(e.target.value)}
                  className="h-9 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg" />
              </label>
            )}
          </>
        )}
        <SelectField label="Variable" value={pollutant} onChange={changeVariable} options={TWIN_VARIABLES.filter((p) => status.pollutants.includes(p.key)).map((p) => ({ value: p.key, label: p.label }))} />
        <SelectField label="Replay window" value={String(hours)} onChange={(v) => { setHours(Number(v)); twinStore.setTime(null); twinStore.setPlaying(false); }} options={WINDOWS.map((x) => ({ value: String(x.hours), label: x.label }))} />
        {lens === "stations" && (
          <div className="flex flex-col gap-1 text-xs font-medium text-muted">
            Layer
            <Tabs value={effectiveMode} onValueChange={(v) => setMode(v as TwinMode)}>
              <TabsList aria-label="Map layer">
                <TabsTrigger value="observed">Observations</TabsTrigger>
                <TabsTrigger value="weather">Weather wind</TabsTrigger>
                <Tooltip text={isAqi ? "AQI is a derived index, not a concentration, so it is not interpolated." : "Interpolation between stations."}>
                  <TabsTrigger value="estimate" disabled={isAqi}>Spatial estimate</TabsTrigger>
                </Tooltip>
                <Tooltip text={isAqi ? "The trained model forecasts concentrations, not the AQI." : "A trained model's forecast for one station."}>
                  <TabsTrigger value="forecast" disabled={isAqi}>Model forecast</TabsTrigger>
                </Tooltip>
                <Tooltip text="Not available here. Transport is a separate, labelled simulation in the Simulation view.">
                  <TabsTrigger value="transport" disabled>Transport</TabsTrigger>
                </Tooltip>
              </TabsList>
              {(Object.keys(MODE_HELP) as TwinMode[]).map((m) => (
                <TabsContent key={m} value={m} className="mt-1 max-w-xl text-xs font-normal text-muted">
                  {MODE_HELP[m]}
                </TabsContent>
              ))}
            </Tabs>
          </div>
        )}
      </FilterBar>

      <details className="mb-4 rounded-lg border border-line bg-surface px-3 py-2 text-xs text-muted">
        <summary className="cursor-pointer list-none">
          <span className="font-medium text-fg">Stored data</span> · {formatIST(status.from)} to {formatIST(status.to)} · {status.stations} stations <span className="text-accent">· details</span>
        </summary>
        <p className="mt-2">{status.data_note} Weather rows: {status.weather.rows.toLocaleString()}.</p>
      </details>

      {win.status === "loading" && <LoadingState label="Loading hourly observations" />}
      {win.status === "error" && <ErrorState title="Observations could not be loaded" message={win.error.message} />}
      {w && w.stations.length === 0 && <EmptyState title="No station has observations of this variable" message="Choose another variable." />}
      {w && w.stations.length > 0 && (
        <div className="space-y-4">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-3">
              <div className={display === "compare" ? "grid grid-cols-[minmax(0,1fr)] gap-3 xl:grid-cols-2" : ""}>
                {display !== "scene3d" && (
                <TwinMap
                  layers={layers} wind={wind} resetToken={resetToken} onMapClick={pickPoint} onPickStation={pickStation} tooltipFor={tooltipFor}
                  badge={<ProvenanceBadge kind={badgeKind} />} timeLabel={instant ? formatIST(instant) : ""}
                  ariaLabel={lens === "simulation" ? "Map of Delhi-NCR with a simulated concentration field for the selected hour" : lens === "atmosphere" ? "Map of Delhi-NCR with weather-model fields for the selected hour" : "Map of monitoring stations in Delhi-NCR for the selected hour"}
                />
                )}
                {display !== "map" && sceneData && (
                  <Scene3D
                    data={sceneData} selected={location} preset={preset} presetToken={presetToken} onPickStation={pickSceneStation} onPickPoint={pickScenePoint}
                    badge={<ProvenanceBadge kind={badgeKind} />} timeLabel={instant ? formatIST(instant) : ""}
                    ariaLabel={`3D scene of Delhi-NCR for ${instant ? formatIST(instant) : "no selected time"}: ${variableLabel(pollutant)}, ${sceneData.columns.length} station columns, ${sceneData.blh ? "boundary-layer surface, " : ""}${sceneData.wind ? "10 m wind particles, " : ""}altitude exaggerated ${12} times`}
                    presets={
                      <div role="group" aria-label="Camera presets" className="flex flex-wrap gap-1">
                        {(Object.keys(CAMERA_PRESETS) as CameraPreset[]).map((k2) => (
                          <button
                            key={k2} type="button" aria-pressed={preset === k2}
                            onClick={() => { setPreset(k2); setPresetToken((x) => x + 1); }}
                            className={`rounded px-2 py-1 text-xs ${preset === k2 ? "bg-accent text-bg" : "bg-surface-2 text-fg hover:bg-line"}`}
                          >
                            {CAMERA_PRESETS[k2].label}
                          </button>
                        ))}
                      </div>
                    }
                    notes={<SceneNotes ctx={ctx} data={sceneData} terrainState={terrainState} />}
                  />
                )}
              </div>
              {lens === "simulation" && (
                <>
                  {isAqi ? (
                    <p className="rounded-lg border border-line bg-surface p-3 text-sm text-muted">
                      The AQI is a derived index, not a concentration, so it cannot be transported. Choose a pollutant to run a simulation.
                    </p>
                  ) : (
                    <SimulationControls mode={simMode} onMode={(m) => { setSimMode(m); setSimRun(null); setSimError(null); }} hours={simHours} onHours={setSimHours}
                      scenario={simScenario} onScenario={setSimScenario} busy={simBusy} onRun={runNow}
                      initLabel={simMode === "live" ? "the newest hour with enough observations" : initHour ? formatIST(initHour) + " (the hour selected on the Stations timeline)" : "no hour selected"} />
                  )}
                  {simBusy && <LoadingState label="Running the simulation (the first run fetches wind data and can take up to half a minute)" />}
                  {simError && <ErrorState title="The simulation could not be run" message={simError} />}
                  {simNote && <p role="status" className="rounded border border-line bg-surface p-2 text-xs text-muted">{simNote}</p>}
                  {!simRun && !simBusy && !simError && !isAqi && <p className="rounded-lg border border-line bg-surface p-3 text-sm text-muted">No run yet. Choose a mode and press Run. Until then the map shows no simulated field and none is invented.</p>}
                </>
              )}
              {lens === "atmosphere" && fieldsRes.status === "loading" && <LoadingState label="Loading atmospheric fields (a first request can take several seconds)" />}
              {lens === "atmosphere" && fieldsRes.status === "error" && <ErrorState title="Atmospheric fields are unavailable" message={fieldsRes.error.message} />}
              {showTimeline && (
                <TimelineControls
                  times={activeTimes} index={activeIndex} onIndex={(n) => { twinStore.setTime(activeTimes[n]); twinStore.setPlaying(false); }} playing={playing}
                  onPlaying={(p) => { if (p && activeIndex >= activeTimes.length - 1) twinStore.setTime(activeTimes[0]); twinStore.setPlaying(p); }}
                  speed={speedIndex} onSpeed={(n) => twinStore.setSpeed(n)} onReset={() => setResetToken((x) => x + 1)}
                />
              )}
              <LegendPanel legends={legends} />
              {lens === "atmosphere" && fields && (
                <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">
                  <li role="status">
                    {formatIST(fields.times[fi])}
                    {fields.now_index !== null && ` · ${fi > fields.now_index ? `${fi - fields.now_index} h ahead of now (forecast)` : fi === fields.now_index ? "now (latest model hour)" : `${fields.now_index - fi} h ago (model analysis)`}`}
                    {" · "}retrieved {formatIST(fields.source.retrieved_at)}
                    {loadedAt - new Date(fields.source.retrieved_at).getTime() > 3 * 3600_000 && " · stale: older than 3 hours"}
                  </li>
                  {fields.notes.map((n) => <li key={n}>{n}</li>)}
                  <li>Maximum distance between a requested lattice point and the model cell it was served from: {fields.source.max_distance_from_requested_point_km ?? "unknown"} km.</li>
                  {timeMode === "historical" && <li>The archive trails real time by a few days, so the newest days are only in the recent-and-forecast mode.</li>}
                </ul>
              )}
              {lens === "simulation" && simRun && (
                <>
                  <p role="status" className={`rounded-lg border p-3 text-xs ${simRun.known_fraction[si] < 0.2 ? "border-warn/40 text-warn" : "border-line text-muted"}`}>
                    {formatIST(simRun.valid_times[si])} · {(simRun.known_fraction[si] * 100).toFixed(0)}% of the area still holds air that was observed at the start.
                    {simRun.known_fraction[si] < 0.2 && " The rest is air that has entered since then: the model has no information about it, so it is left clear rather than filled in."}
                  </p>
                  <RunSummary run={simRun} index={si} />
                </>
              )}
              {lens === "simulation" && !isAqi && <EstimateValidationCard pollutant={pollutant} to={status.periods[pollutant]?.dense_to ?? status.to} />}
              <LayerPanel ctx={ctx} surface={surface} />
              {lens === "stations" && (
                <p className="text-xs text-muted" role="status">
                  {observedCount(w, i)} of {w.stations.length} stations have {isAqi ? "an AQI" : "an observation"} at {formatIST(w.times[i])}.
                </p>
              )}
              {lens === "stations" && effectiveMode === "estimate" && <EstimateNote est={estimate} />}
              {lens === "stations" && effectiveMode === "forecast" && (
                <p className="rounded-lg border border-line bg-surface p-3 text-xs text-muted">
                  The model forecasts one station at a time (the selected one) from the hour on the timeline, using only data available then. There is no map-wide pollutant forecast.
                </p>
              )}
            </div>
            <div className="min-w-0 rounded-lg border border-line bg-surface p-4">
              {lens === "simulation" ? (
                simRun ? <SimulationInspector run={simRun} index={si} point={point} onSeek={(n) => { twinStore.setTime(simRun.valid_times[n]); twinStore.setPlaying(false); }} />
                  : <p className="text-sm text-muted">Run a simulation to inspect it.</p>
              ) : lens === "atmosphere" ? (
                fields ? <FieldInspector fields={fields} index={fi} point={point} onSeek={(n) => { twinStore.setTime(fields.times[n]); twinStore.setPlaying(false); }} /> : <p className="text-sm text-muted">Waiting for the atmospheric fields.</p>
              ) : k >= 0 ? <StationCharts w={w} k={k} index={i} mode={effectiveMode} backtest={backtestState} /> : <p className="text-sm text-muted">Select a station on the map.</p>}
            </div>
            {lens === "stations" && effectiveMode === "forecast" && !isAqi && selectedId !== null && settledTime && (
              <div className="lg:col-start-2"><RiskPanel pollutant={pollutant as Exclude<TwinPollutant, "aqi">} stationId={selectedId} origin={settledTime} /></div>
            )}
            {lens === "stations" && settledTime && <div className="lg:col-start-2"><RegimePanel time={settledTime} stationId={selectedId} /></div>}
          </div>
          <details className="rounded-lg border border-line bg-surface px-4 py-3">
            <summary className="cursor-pointer list-none text-sm font-medium">Where each layer&apos;s data comes from <span className="text-xs font-normal text-accent">· details</span></summary>
            <ul className="mt-3 space-y-1 text-sm text-muted">
              <li><ProvenanceBadge kind="observed" /> {w.provenance.observations}.</li>
              {w.weather && <li className="mt-1"><ProvenanceBadge kind="weather_forecast" /> {w.weather.provenance.source}. {w.weather.provenance.wind_convention}.</li>}
              <li className="mt-1"><ProvenanceBadge kind="estimate" /> Inverse-distance weighting of the observations at the selected hour; its error is shown beside the map.</li>
              <li className="mt-1"><ProvenanceBadge kind="model_forecast" /> Output of the trained model for one station; see the model status in Settings.</li>
              <li className="mt-1"><ProvenanceBadge kind="weather_forecast" /> Atmosphere view: Open-Meteo model output on a lattice of points (forecast API for recent and coming hours, archive API for past days); never station measurements.</li>
              <li className="mt-1"><ProvenanceBadge kind="simulated" /> Simulation view: observed air carried by that wind; scenarios are labelled hypothetical.</li>
            </ul>
          </details>
        </div>
      )}
    </>
  );
}

function EstimateNote({ est }: { est: Optional<TwinEstimate> }) {
  if (est.status === "loading" || est.status === "idle") return <LoadingState label="Estimating between stations" />;
  if (est.status === "error") return <ErrorState title="No spatial estimate for this hour" message={est.error.message} />;
  const e = est.data;
  return (
    <div className="rounded-lg border border-line bg-surface p-3 text-xs text-muted">
      <p>
        <strong className="text-fg">Spatial estimate.</strong> {e.method.name} (power {e.method.power}, radius {e.method.radius_km} km, at least {e.method.min_stations} stations); cells with fewer are left empty. {e.provenance.caveat}
      </p>
      <p className="mt-1">
        {e.leave_one_out
          ? `Leave-one-out check at this hour (each station predicted from the others): mean absolute error ${e.leave_one_out.mae.toFixed(1)} ${e.unit}, RMSE ${e.leave_one_out.rmse.toFixed(1)}, bias ${e.leave_one_out.bias.toFixed(1)}, over ${e.leave_one_out.n} of ${e.leave_one_out.stations_total} stations.`
          : "Too few stations for a leave-one-out error at this hour."}
      </p>
    </div>
  );
}

function EstimateValidationCard({ pollutant, to }: { pollutant: TwinPollutant; to: string }) {
  const [state, setState] = useState<{ status: "idle" | "loading" | "ready" | "error"; data?: EstimateValidation; message?: string }>({ status: "idle" });
  async function run() {
    setState({ status: "loading" });
    const end = new Date(to);
    const from = new Date(end.getTime() - 100 * 86400_000).toISOString().replace(/\.\d+Z$/, "Z");
    try {
      const data = await fetchEstimateValidation(pollutant, from, end.toISOString().replace(/\.\d+Z$/, "Z"));
      setState({ status: "ready", data });
    } catch (e) {
      setState({ status: "error", message: e instanceof ApiError ? e.message : "The check could not be run." });
    }
  }
  const d = state.data;
  return (
    <section aria-label="Spatial estimate check" className="rounded-lg border border-line bg-surface p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Spatial estimate check</h2>
        <ProvenanceBadge kind="estimate" />
        <Button size="sm" variant="secondary" onClick={run} disabled={state.status === "loading"}>
          {state.status === "loading" ? "Checking…" : "Check against withheld stations (last 100 days)"}
        </Button>
      </div>
      <p className="mt-1 text-muted">Each station is withheld in turn and predicted from the others by the same interpolation that starts every run, then compared with a plain mean of the other stations.</p>
      {state.status === "error" && <p role="alert" className="mt-1 text-danger">{state.message}</p>}
      {d && (
        <p className={`mt-2 ${d.beats_baseline ? "text-muted" : "text-warn"}`}>
          {d.hours_used} hours, {d.predictions.toLocaleString()} predictions: interpolation MAE {d.idw.mae} (RMSE {d.idw.rmse}, bias {d.idw.bias}) against {d.baseline_mean_of_other_stations.mae} for the mean of the other stations {d.unit};
          skill {d.skill_vs_mean ?? "n/a"}. {d.beats_baseline ? "The interpolation is closer than the mean." : "The interpolation is NOT closer than a plain mean: between-station differences here are mostly local, so the map adds little beyond the average."}
        </p>
      )}
    </section>
  );
}
