"use client";

import { useMemo, useState } from "react";
import { EChart } from "@/components/charts/EChart";
import { Section } from "@/components/ui/PageHeader";
import { btnSecondary } from "@/components/ui/states";
import { summarizeReport, reportDownloadUrl } from "@/lib/reports/api";
import type { LlmSummary, Report } from "@/lib/reports/types";
import { formatIST, formatISTAxis } from "@/lib/weather/time";

// Exact ties round to even, as the server does, so a value reads the same here, in the PDF and in the Markdown.
function fixed(v: number, digits: number): string {
  const scale = 10 ** digits;
  const scaled = v * scale;
  const tie = Math.abs(scaled % 1) === 0.5;
  return tie && Math.floor(scaled) % 2 === 0 ? (Math.floor(scaled) / scale).toFixed(digits) : v.toFixed(digits);
}
const num = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "No data" : fixed(v, digits));

function Table({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full min-w-96 text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-4 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j} className="px-4 py-2 font-mono tabular-nums first:font-sans">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const Cite = ({ id }: { id: string | null }) =>
  id ? <a href={`#src-${id}`} className="ml-1 rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.75em] text-accent hover:underline" aria-label={`Source ${id}`}>{id}</a> : null;

function Note({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-line bg-surface p-4 text-sm text-muted">{children}</p>;
}

function AirChart({ r }: { r: Report }) {
  const a = r.air;
  const option = useMemo(
    () => ({
      grid: { left: 52, right: 16, top: 16, bottom: 28 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: a.times.map(formatISTAxis), axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", name: a.stats?.unit ?? "", scale: true },
      // null values stay null: a missing hour is a gap in the line, never an interpolated point.
      series: [{ type: "line", data: a.values, connectNulls: false, showSymbol: a.values.length < 60, name: a.label }],
    }),
    [a],
  );
  return <EChart option={option} height={240} ariaLabel={`${a.label} hourly observations at ${a.station?.name ?? "the station"}, ${a.stats?.observed_hours ?? 0} hours observed. Gaps are hours without data.`} />;
}

function SummaryBox({ report }: { report: Report }) {
  const [summary, setSummary] = useState<LlmSummary>(report.llm_summary);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setFailed(null);
    try {
      setSummary(await summarizeReport(report.id));
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "The summary could not be generated.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-4 text-sm">
      <ul className="list-disc space-y-1 pl-5" aria-label="Key facts">
        {report.facts_summary.map((f, i) => <li key={i}>{f}</li>)}
      </ul>
      {summary.status === "ok" && (
        <div className="border-t border-line pt-3">
          <p className="leading-relaxed">{summary.text}</p>
          <p className="mt-1 text-xs text-muted">{summary.label} Model: {summary.model}{summary.duration_ms ? `, ${(summary.duration_ms / 1000).toFixed(1)} s` : ""}.</p>
        </div>
      )}
      {(summary.status === "rejected" || summary.status === "unavailable") && <p role="status" className="border-t border-line pt-3 text-warn">{summary.reason}</p>}
      {failed && <p role="alert" className="text-danger">{failed}</p>}
      <button type="button" onClick={run} disabled={busy} className={btnSecondary}>
        {busy ? "Writing summary…" : summary.status === "ok" ? "Write the summary again" : "Add a written summary"}
      </button>
      {busy && <p className="text-xs text-muted">The local language model is writing; on a CPU-only machine this can take a minute.</p>}
    </div>
  );
}

export function ReportView({ report: r }: { report: Report }) {
  const a = r.air;
  return (
    <article className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface p-4">
        <div>
          <h2 className="text-lg font-semibold">{r.location.name}: {r.pollutant_label} and weather</h2>
          <p className="text-sm text-muted">
            {formatIST(r.period.start)} to {formatIST(r.period.end)} ({r.period.hours} h). Generated {formatIST(r.created_at)} in {(r.build_ms / 1000).toFixed(1)} s.
          </p>
        </div>
        <div className="flex gap-2">
          <a className={btnSecondary} href={reportDownloadUrl(r.id, "pdf")} download>Download PDF</a>
          <a className={btnSecondary} href={reportDownloadUrl(r.id, "markdown")} download>Download Markdown</a>
        </div>
      </div>

      <Section title="Summary"><SummaryBox report={r} /></Section>

      <Section title={`${r.pollutant_label} observations`}>
        {a.status !== "ok" || !a.stats || !a.station ? (
          <Note>Not available. {a.reason}</Note>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted">
              {a.station.name}, {a.station.distance_km} km from the city centre. {a.station.provider ?? "Unknown provider"}{a.station.owner ? `, operated by ${a.station.owner}` : ""}.<Cite id={a.source_id} />
            </p>
            <AirChart r={r} />
            <Table caption="Air-quality statistics" head={["Measure", "Value", "Time (IST)"]} rows={[
              ["Latest", `${num(a.stats.latest)} ${a.stats.unit ?? ""}`, a.stats.latest_time ? formatIST(a.stats.latest_time) : "-"],
              ["Lowest", `${num(a.stats.min)} ${a.stats.unit ?? ""}`, a.stats.min_time ? formatIST(a.stats.min_time) : "-"],
              ["Highest", `${num(a.stats.max)} ${a.stats.unit ?? ""}`, a.stats.max_time ? formatIST(a.stats.max_time) : "-"],
              ["Mean", `${num(a.stats.mean)} ${a.stats.unit ?? ""}`, "-"],
              ["Hours observed", `${a.stats.observed_hours} of ${a.stats.observed_hours + a.stats.missing_hours}`, `${a.stats.missing_hours} missing`],
              ...(a.largest_rise ? [["Largest rise", `+${num(a.largest_rise.rise)} ${a.stats.unit ?? ""} over ${a.largest_rise.span_hours} h`, `${formatIST(a.largest_rise.from_time)} to ${formatIST(a.largest_rise.to_time)}`]] : []),
              ...(a.trend ? [["Trend", `${num(a.trend.first_mean)} to ${num(a.trend.last_mean)} (${a.trend.change >= 0 ? "+" : ""}${num(a.trend.change)})`, a.trend.basis]] : []),
            ]} />
          </div>
        )}
      </Section>

      <Section title="Weather over the period">
        {r.weather.status !== "ok" ? <Note>Not available. {r.weather.reason}</Note> : (
          <div className="space-y-2">
            <Table caption="Weather-model statistics" head={["Variable", "Latest", "Min", "Max", "Mean"]} rows={[
              ...r.weather.variables.map((v) => [`${v.label} (${v.unit})`, num(v.latest), num(v.min), num(v.max), num(v.mean)]),
              ...(r.weather.rain_total_mm !== null ? [["Precipitation (mm)", "-", "-", `${num(r.weather.rain_total_mm)} total`, `${r.weather.rainy_hours} rainy h`]] : []),
            ]} />
            <p className="text-xs text-muted">Weather-model values for the grid cell, not station measurements.<Cite id={r.weather.source_id} /></p>
          </div>
        )}
      </Section>

      <Section title="Atmospheric conditions (descriptive indicators)">
        {r.atmosphere.status !== "ok" ? <Note>Not available. {r.atmosphere.reason}</Note> : (
          <Note>
            Ventilation index: latest {num(r.atmosphere.ventilation_index_latest, 0)}, mean {num(r.atmosphere.ventilation_index_mean, 0)} m²/s.{" "}
            Hours since rain: {r.atmosphere.hours_since_rain ?? "unknown"}. {r.atmosphere.hours_since_rain_note} {r.atmosphere.definition}
          </Note>
        )}
      </Section>

      {r.coinciding.status === "ok" && (
        <Section title="Weather during the largest rise">
          <Table caption="Weather that coincided with the largest rise" head={["Variable", "During the rise", "Period mean", "Relation"]}
            rows={r.coinciding.items.map((c) => [`${c.label} (${c.unit})`, num(c.during), num(c.period_mean), c.relation])} />
          <p className="mt-2 text-xs text-muted">{r.coinciding.caution}</p>
        </Section>
      )}

      <Section title="Scientific and guidance references">
        {r.references.status !== "ok" ? <Note>None cited. {r.references.reason}</Note> : (
          <ul className="space-y-2">
            {r.references.items.map((x) => (
              <li key={x.source_id} className="rounded-lg border border-line bg-surface p-4 text-sm">
                <p className="font-medium">{x.title}<Cite id={x.source_id} /></p>
                <p className="text-xs text-muted">{[x.category, x.publisher, x.location].filter(Boolean).join(" · ")}</p>
                <blockquote className="mt-2 border-l-2 border-line pl-3 text-muted">{x.excerpt}</blockquote>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Forecast">
        {r.forecast.status === "available" ? (
          <div className="space-y-2">
            <Note>{r.forecast.reason} Provider: {r.forecast.provider}, model {r.forecast.model_version}.<Cite id={r.forecast.source_id} /></Note>
            <Table caption="Forecast values from the external service" head={["Time (IST)", `Value (${r.forecast.unit})`, r.forecast.interval_level ? `${Math.round(r.forecast.interval_level * 100)}% range` : "Range"]}
              rows={r.forecast.times.map((t, i) => [formatIST(t), num(r.forecast.values[i]), r.forecast.lower.length ? `${num(r.forecast.lower[i])} to ${num(r.forecast.upper[i])}` : "-"])} />
          </div>
        ) : <Note>No forecast. {r.forecast.reason}</Note>}
      </Section>

      <Section title="Data freshness">
        <Table caption="Freshness of each data source" head={["Source", "Latest data (IST)", "Status"]}
          rows={r.freshness.map((f) => [f.label, f.latest_data_time ? formatIST(f.latest_data_time) : "-", f.status])} />
      </Section>

      <Section title="What this report cannot say">
        <ul className="list-disc space-y-1 rounded-lg border border-line bg-surface p-4 pl-9 text-sm">
          {r.limitations.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </Section>

      <Section title="Sources">
        <ol className="space-y-2">
          {r.sources.map((s) => (
            <li key={s.id} id={`src-${s.id}`} className="scroll-mt-20 rounded-lg border border-line bg-surface p-3 text-sm">
              <span className="mr-2 font-mono text-accent">{s.id}</span>{s.title}
              <p className="text-xs text-muted">{s.provider} · retrieved {formatIST(s.retrieved_at)}{s.note ? ` · ${s.note}` : ""}</p>
              {s.url && /^https?:\/\//.test(s.url) && <a href={s.url} target="_blank" rel="noreferrer noopener" className="text-xs text-accent underline hover:no-underline">{s.url}</a>}
            </li>
          ))}
        </ol>
      </Section>
    </article>
  );
}
