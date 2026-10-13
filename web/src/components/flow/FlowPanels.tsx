"use client";

import { useMemo } from "react";
import { EChart } from "@/components/charts/EChart";
import { Chip, Kicker } from "@/components/ui/Glass";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import type { CoupledRun, EvaluationSummary, ProcessKey, SpeciesValidation } from "@/lib/flow/coupled";
import { sampleVector, type Scale } from "@/lib/flow/field";
import type { FlowFrames } from "@/lib/flow/frames";
import { sampleBilinear } from "@/lib/twin/fields";
import { compassName, uvToWind } from "@/lib/twin/windVector";
import { formatIST, formatISTAxis } from "@/lib/weather/time";

// ---------------------------------------------------------------------------------------------- legend
export function FlowLegend({ scale, unit, colourBy, className }: { scale: Scale; unit: string; colourBy: "pollutant" | "wind"; className?: string }) {
  return (
    <div className={className} aria-label="Legend">
      <Kicker>{colourBy === "pollutant" ? `${scale.label} (${unit})` : "Wind speed (m/s)"}</Kicker>
      {colourBy === "pollutant" ? (
        <>
          <ul className="mt-1.5 flex overflow-hidden rounded-md border border-white/10" role="list">
            {scale.bins.map((b) => (
              <li key={b.label} className="flex-1" role="listitem">
                <span className="block h-2.5" style={{ background: b.color }} />
                <span className="block px-0.5 pt-0.5 text-center font-mono text-[10px] text-muted">{b.label}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[11px] leading-snug text-muted">{scale.basis}</p>
        </>
      ) : (
        <div className="mt-1.5 h-2.5 rounded-md" style={{ background: "linear-gradient(90deg, rgb(70,130,200), rgb(90,200,220), rgb(180,235,200), rgb(255,240,150), rgb(255,255,255))" }} />
      )}
      {colourBy === "wind" && (
        <div className="flex justify-between font-mono text-[10px] text-muted">
          <span>0</span><span>3</span><span>6</span><span>10</span><span>16+</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- point inspector
function categoryOf(scale: Scale, v: number): string {
  const b = scale.bins.find((x) => v >= x.lo && v < x.hi) ?? scale.bins[scale.bins.length - 1];
  return b.label;
}

export function FlowInspector({ frames, k, scale, picked, run }: { frames: FlowFrames; k: number; scale: Scale; picked: { lat: number; lon: number } | null; run: CoupledRun | null }) {
  const info = useMemo(() => {
    if (!picked) return null;
    const s = frames.scalarAt(k);
    const value = s ? sampleBilinear(s.grid, { lats: s.lats, lons: s.lons }, picked.lat, picked.lon) : null;
    const w = frames.windAt(k);
    const wind = w ? sampleVector(w, picked.lat, picked.lon) : null;
    let passive: number | null = null;
    if (run?.passive_focus && frames.species === run.focus) {
      const fr = run.passive_focus[Math.min(k, run.passive_focus.length - 1)];
      passive = sampleBilinear(fr, { lats: run.grid.lats, lons: run.grid.lons }, picked.lat, picked.lon);
    }
    return { value, wind: wind ? uvToWind(wind.u, wind.v) : null, passive };
  }, [frames, k, picked, run]);

  if (!picked) return <p className="text-sm text-muted">Click the map to read the air at a point.</p>;
  if (!info) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
      <dt className="text-muted">Place</dt>
      <dd className="font-mono tabular">{picked.lat.toFixed(3)}°N, {picked.lon.toFixed(3)}°E</dd>
      <dt className="text-muted">{scale.label}</dt>
      <dd className="tabular">
        {info.value === null ? <span className="text-muted">no value here (not enough stations or air of unknown origin)</span> : <><b>{info.value.toFixed(info.value >= 100 ? 0 : 1)}</b> {frames.unit} <span className="text-muted">· class {categoryOf(scale, info.value)}</span></>}
      </dd>
      {info.passive !== null && info.value !== null && (
        <>
          <dt className="text-muted">Passive transport</dt>
          <dd className="tabular">{info.passive.toFixed(1)} {frames.unit} <span className="text-muted">(coupled − passive = {(info.value - info.passive >= 0 ? "+" : "") + (info.value - info.passive).toFixed(1)})</span></dd>
        </>
      )}
      <dt className="text-muted">Wind (10 m)</dt>
      <dd className="tabular">
        {info.wind ? (info.wind.speed < 0.3 ? "calm" : <>{info.wind.speed.toFixed(1)} m/s from the {compassName(info.wind.fromDeg)} ({Math.round(info.wind.fromDeg)}°)</>) : <span className="text-muted">no wind value here</span>}
      </dd>
    </dl>
  );
}

// ---------------------------------------------------------------------------------------------- what the couplings did
const PROCESS_LABEL: Record<string, string> = {
  ventilation: "Ventilation (boundary layer × wind)", dilution: "Dilution (one-sided)", deposition: "Dry deposition / settling", washout: "Rain scavenging", oxidation: "SO₂ → sulfate",
};

export function CouplingEffects({ run }: { run: CoupledRun }) {
  const enabled = new Set(run.model.processes.filter((p) => p.enabled).map((p) => p.key as ProcessKey));
  const species = Object.keys(run.budget);
  return (
    <div className="space-y-5">
      <div>
        <Kicker>What each coupling did to the air that was known at the start</Kicker>
        <div className="mt-2 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="sr-only">Share of each species&apos; initial burden removed (positive) or added (negative) by each process</caption>
            <thead className="border-b border-line text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Process</th>
                {species.map((s) => <th key={s} scope="col" className="px-3 py-2 font-medium">{run.species[s]?.label ?? s}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(Object.keys(PROCESS_LABEL) as ProcessKey[]).map((p) => (
                <tr key={p} className={enabled.has(p) ? "" : "opacity-45"}>
                  <th scope="row" className="px-3 py-1.5 text-left font-normal">{PROCESS_LABEL[p]}{!enabled.has(p) && <span className="ml-1 text-xs text-muted">(off)</span>}</th>
                  {species.map((s) => {
                    const v = run.budget[s]?.[p] ?? 0;
                    return <td key={s} className={`px-3 py-1.5 font-mono tabular ${Math.abs(v) < 0.0005 ? "text-muted" : v < 0 ? "text-emerald-300" : ""}`}>{Math.abs(v) < 0.0005 ? "·" : `${v > 0 ? "−" : "+"}${Math.abs(v * 100).toFixed(1)}%`}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1.5 text-xs text-muted">{run.budget_note}</p>
      </div>
      <div>
        <Kicker>End of run: coupled model against plain transport (domain mean over known cells)</Kicker>
        <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(run.effect_of_couplings).map(([s, e]) => {
            const d = e.coupled_mean_end !== null && e.passive_mean_end !== null ? e.coupled_mean_end - e.passive_mean_end : null;
            return (
              <li key={s} className="rounded-lg border border-line bg-surface-2/50 p-2.5 text-sm">
                <div className="text-xs text-muted">{run.species[s]?.label ?? s}</div>
                <div className="mt-0.5 tabular">
                  {e.coupled_mean_end === null ? <span className="text-muted">unknown by the end</span> : <><b>{e.coupled_mean_end.toFixed(1)}</b> {run.species[s]?.unit} <span className="text-muted">vs {e.passive_mean_end?.toFixed(1)} passive</span></>}
                </div>
                {d !== null && <div className="text-xs text-muted tabular">{d >= 0 ? "+" : ""}{d.toFixed(1)} from the couplings</div>}
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <Kicker>The processes</Kicker>
        <ul className="mt-2 space-y-2">
          {run.model.processes.map((p) => (
            <li key={p.key} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{p.label}</span>
                <Chip tone={p.enabled ? "ok" : "neutral"}>{p.enabled ? "on" : "off"}</Chip>
                <span className="text-xs text-muted">{p.kind}</span>
              </div>
              <p className="mt-1 text-muted">{p.what}</p>
              <p className="mt-1 text-xs text-muted"><b className="text-fg">Basis.</b> {p.basis}</p>
              <p className="mt-0.5 text-xs text-muted"><b className="text-fg">Limits.</b> {p.limits}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- validation
export function ValidationPanel({ run }: { run: CoupledRun }) {
  const v = run.validation;
  if (!v.available || !v.per_species) {
    return (
      <p className="rounded-lg border border-line p-3 text-sm text-muted">
        <strong className="text-fg">Not checked against observations.</strong> {v.reason ?? "No later observations are stored for this window (a live or very recent start has none yet), so the run cannot be scored."}
      </p>
    );
  }
  const rows = Object.entries(v.per_species) as [string, SpeciesValidation][];
  return (
    <div className="space-y-3">
      <p className="rounded-lg border border-line bg-surface-2/50 p-3 text-sm">{v.verdict}</p>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <caption className="sr-only">Mean absolute error at withheld stations against later observations</caption>
          <thead className="border-b border-line text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium" scope="col">Species</th><th className="px-3 py-2 font-medium" scope="col">Coupled</th><th className="px-3 py-2 font-medium" scope="col">Passive</th>
              <th className="px-3 py-2 font-medium" scope="col">Persistence</th><th className="px-3 py-2 font-medium" scope="col">Skill vs passive</th><th className="px-3 py-2 font-medium" scope="col">Skill vs persistence</th><th className="px-3 py-2 font-medium" scope="col">n</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map(([s, d]) =>
              d.available ? (
                <tr key={s}>
                  <th scope="row" className="px-3 py-1.5 text-left font-normal">{run.species[s]?.label ?? s}</th>
                  <td className="px-3 py-1.5 font-mono tabular">{d.mae_coupled}</td>
                  <td className="px-3 py-1.5 font-mono tabular">{d.mae_passive}</td>
                  <td className="px-3 py-1.5 font-mono tabular">{d.mae_persistence}</td>
                  <td className={`px-3 py-1.5 font-mono tabular ${d.beats_passive ? "text-emerald-300" : "text-warn"}`}>{d.skill_vs_passive === null ? "–" : (d.skill_vs_passive >= 0 ? "+" : "") + d.skill_vs_passive.toFixed(2)}</td>
                  <td className={`px-3 py-1.5 font-mono tabular ${d.beats_persistence ? "text-emerald-300" : "text-warn"}`}>{d.skill_vs_persistence === null ? "–" : (d.skill_vs_persistence >= 0 ? "+" : "") + d.skill_vs_persistence.toFixed(2)}</td>
                  <td className="px-3 py-1.5 font-mono tabular text-muted">{d.n}</td>
                </tr>
              ) : (
                <tr key={s}><th scope="row" className="px-3 py-1.5 text-left font-normal">{run.species[s]?.label ?? s}</th><td colSpan={6} className="px-3 py-1.5 text-xs text-muted">{d.reason}</td></tr>
              ),
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">MAE in µg/m³ at stations withheld from the starting field, leads 1 to {run.execution.simulated_hours} h. Skill is 1 − MAE/MAE<sub>baseline</sub>: positive means closer to the observations. {v.baselines}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- meteorology
export function MeteorologyChart({ run, k, onSeek }: { run: CoupledRun; k: number; onSeek: (i: number) => void }) {
  const option = useMemo(() => {
    const t = run.valid_times.map((x) => formatISTAxis(x));
    const m = run.meteorology;
    const mark = { symbol: "none", lineStyle: { color: "#22d3ee", width: 1.5 }, label: { show: false }, data: [{ xAxis: Math.min(k, t.length - 1) }] };
    return {
      animation: false, backgroundColor: "transparent", textStyle: { color: "#9db0cc" },
      grid: { left: 52, right: 58, top: 30, bottom: 36 },
      tooltip: { trigger: "axis" },
      legend: { top: 0, textStyle: { color: "#9db0cc" } },
      xAxis: { type: "category", data: t, axisLabel: { color: "#9db0cc", hideOverlap: true } },
      yAxis: [
        { type: "value", name: "m", nameTextStyle: { color: "#9db0cc" }, axisLabel: { color: "#9db0cc" }, splitLine: { lineStyle: { color: "#22314d" } } },
        { type: "value", name: "m/s · mm/h", nameTextStyle: { color: "#9db0cc" }, axisLabel: { color: "#9db0cc" }, splitLine: { show: false } },
      ],
      series: [
        { name: "Boundary-layer height (m)", type: "line", data: m.boundary_layer_height_m, smooth: true, showSymbol: false, lineStyle: { color: "#c2589a" }, markLine: mark },
        { name: "Wind (m/s)", type: "line", yAxisIndex: 1, data: m.wind_speed_m_s, smooth: true, showSymbol: false, lineStyle: { color: "#22d3ee" } },
        { name: "Rain (mm/h)", type: "bar", yAxisIndex: 1, data: m.rain_mm_per_h, itemStyle: { color: "#5db4f5" } },
      ],
    };
  }, [run, k]);
  const sw = run.meteorology.shortwave_w_m2;
  return (
    <div>
      <EChart option={option} ariaLabel="Boundary-layer height, wind speed and rain over the run, area means" height={250} onSelectIndex={onSeek} />
      <p className="mt-1 text-xs text-muted">
        Area means of weather-model values. Peak shortwave radiation {Math.max(...sw)} W/m² (drives the SO₂ oxidation rate). Boundary-layer depth × wind sets the ventilation coupling; rain sets scavenging.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- limits and provenance
export function RunProvenance({ run }: { run: CoupledRun }) {
  const f = run.freshness;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <ProvenanceBadge kind="simulated" detail="Computed by the coupled model from the starting field and weather-model inputs." />
        {run.source === "model_forecast" && <ProvenanceBadge kind="model_forecast" detail="The starting field is the trained model's station forecasts." />}
        {run.source === "cams" && <ProvenanceBadge kind="atmospheric_model" detail="The starting field is the current CAMS model field, not measurements." />}
        {run.source === "live" && <ProvenanceBadge kind="observed" detail="The starting field is the newest live station readings." />}
        <Chip tone={f.stale ? "warn" : "ok"}>{f.stale ? "Stale start" : "Fresh start"} · {f.initial_state_age_hours.toFixed(1)} h old</Chip>
        <Chip tone="neutral">Run {run.run_id}</Chip>
      </div>
      <p className="text-muted">{f.note}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted">Starts</dt><dd>{formatIST(run.initialisation)}</dd>
        <dt className="text-muted">Covers</dt><dd>{run.execution.simulated_hours} h on a {run.grid.rows}×{run.grid.cols} grid (about {(run.grid.dx_m / 1000).toFixed(1)} km), {run.execution.status}</dd>
        <dt className="text-muted">Stations used</dt><dd>{Object.entries(run.inputs.stations.per_species).map(([k, n]) => `${k} ${n}`).join(" · ")}</dd>
        <dt className="text-muted">Weather</dt><dd>{run.inputs.meteorology.provider}, {run.inputs.meteorology.resolution}</dd>
        {run.forecast && <><dt className="text-muted">Forecast start</dt><dd>{run.forecast.note}</dd></>}
        <dt className="text-muted">Computed in</dt><dd>{(run.execution.duration_ms / 1000).toFixed(1)} s</dd>
      </dl>
      <div>
        <Kicker>Limits of this picture</Kicker>
        <ul className="mt-1.5 list-disc space-y-1 pl-5 text-muted">
          {run.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </div>
      <div>
        <Kicker>Not modelled</Kicker>
        <ul className="mt-1.5 list-disc space-y-1 pl-5 text-muted">
          {run.model.not_modelled.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- recorded hindcast over many windows
const SP_LABEL: Record<string, string> = { pm25: "PM2.5", pm10: "PM10", no2: "NO₂", o3: "O₃", so2: "SO₂" };

/** The recorded evaluation of the couplings over many historical windows: the evidence the user should weigh before trusting a single run. */
export function EvaluationSummaryPanel({ evaluation }: { evaluation: EvaluationSummary | null }) {
  if (!evaluation) {
    return <p className="rounded-lg border border-line p-3 text-sm text-muted"><strong className="text-fg">No historical evaluation has been recorded.</strong> Run <code>python -m app.twin.coupled_eval</code> to produce one.</p>;
  }
  const names = Object.keys(evaluation.configs);
  const species = Object.keys(evaluation.configs[names[0]] ?? {});
  const cell = (name: string, sp: string, base: "vs_passive" | "vs_persistence") => {
    const st = evaluation.configs[name]?.[sp]?.[base];
    if (!st || !st.n || st.median === undefined) return <span className="text-muted">n/a</span>;
    const good = st.median > 0.005;
    return <span className={good ? "text-emerald-300" : st.median < -0.005 ? "text-warn" : "text-muted"}>{(st.median >= 0 ? "+" : "") + st.median.toFixed(2)} <span className="text-muted">({Math.round((st.share_positive ?? 0) * 100)}%)</span></span>;
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        <b className="text-fg">Recorded hindcast: {evaluation.windows} historical windows of {evaluation.hours} h.</b> Each window was run with the stated defaults and scored at stations
        withheld from the starting field. Skill = 1 − MAE/MAE<sub>baseline</sub>: positive means closer to later observations than the baseline. The percentage is the share of windows with
        positive skill. Nothing was fitted to these windows.
      </p>
      {(["vs_passive", "vs_persistence"] as const).map((base) => (
        <div key={base} className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="px-3 pt-2 text-left text-xs text-muted">Median skill {base === "vs_passive" ? "against plain transport (every coupling off)" : "against persistence (hold the starting value)"}</caption>
            <thead className="border-b border-line text-xs text-muted">
              <tr><th scope="col" className="px-3 py-2 font-medium">Configuration</th>{species.map((s) => <th scope="col" key={s} className="px-3 py-2 font-medium">{SP_LABEL[s] ?? s}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {names.map((n) => (
                <tr key={n}><th scope="row" className="px-3 py-1.5 text-left font-normal">{n}</th>{species.map((s) => <td key={s} className="px-3 py-1.5 font-mono tabular">{cell(n, s, base)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p className="text-xs text-muted">
        Read this as: the couplings are physically motivated, but on these windows none of them reliably improved on plain transport, and nothing beat simply holding the starting value
        (the model has no emissions). Use the coupled picture to see how weather and chemistry change the air that is already there, not as a forecast of concentrations.
      </p>
    </div>
  );
}
