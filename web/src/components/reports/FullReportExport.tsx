"use client";

import { useRef, useState } from "react";
import { Kicker } from "@/components/ui/Glass";
import { btnPrimary, btnSecondary } from "@/components/ui/states";
import { buildExport, type ExportFormat, type ExportOptions } from "@/lib/reports/api";

type Phase = { status: "idle" } | { status: "building"; format: ExportFormat; since: number } | { status: "done"; format: ExportFormat; filename: string; size: number } | { status: "error"; message: string };

const INCLUDES = [
  "Station and weather time series, with gaps shown as gaps",
  "Wind and modelled-air map of Delhi-NCR with the stations on it",
  "Station ranking, forecast and how well each model performed",
  "What data exists and what does not",
  "Sources, freshness, limitations and the written reports",
];

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function FullReportExport({ options }: { options: Omit<ExportOptions, "articles"> }) {
  const [articles, setArticles] = useState(true);
  const [phase, setPhase] = useState<Phase>({ status: "idle" });
  const abort = useRef<AbortController | null>(null);
  const building = phase.status === "building";

  async function run(format: ExportFormat) {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    setPhase({ status: "building", format, since: Date.now() });
    try {
      const { blob, filename } = await buildExport(format, { ...options, articles }, ac.signal);
      if (ac.signal.aborted) return;
      saveBlob(blob, filename);
      setPhase({ status: "done", format, filename, size: blob.size });
    } catch (e) {
      if (ac.signal.aborted) return;
      setPhase({ status: "error", message: e instanceof Error ? e.message : "The report could not be built." });
    }
  }

  return (
    <section aria-labelledby="full-report" className="card my-6 p-5">
      <Kicker>Full report</Kicker>
      <h2 id="full-report" className="mt-1 text-xl font-semibold tracking-tight">Everything in one file</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Builds a single document for the place, period and pollutant chosen above, from live data. The HTML opens offline and prints cleanly; the PDF is the same content.
      </p>
      <ul className="mt-3 grid gap-x-6 gap-y-1 text-sm text-muted sm:grid-cols-2">
        {INCLUDES.map((t) => (
          <li key={t} className="flex gap-2"><span aria-hidden="true" className="text-accent">+</span>{t}</li>
        ))}
      </ul>
      <label className="mt-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={articles} onChange={(e) => setArticles(e.target.checked)} disabled={building} />
        Include the written reports (adds about 15 pages)
      </label>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className={btnPrimary} disabled={building} onClick={() => run("pdf")}>Download PDF</button>
        <button type="button" className={btnSecondary} disabled={building} onClick={() => run("html")}>Download HTML</button>
        {building && (
          <button type="button" className="text-sm text-muted underline" onClick={() => { abort.current?.abort(); setPhase({ status: "idle" }); }}>Cancel</button>
        )}
      </div>
      <p role="status" aria-live="polite" className="mt-3 min-h-5 text-sm text-muted">
        {phase.status === "building" && `Building the ${phase.format.toUpperCase()} from live weather, air-quality and model data. The first one after a restart can take up to two minutes; the next is quick.`}
        {phase.status === "done" && `Saved ${phase.filename} (${(phase.size / 1024).toFixed(0)} KB).`}
        {phase.status === "error" && <span className="text-danger">{phase.message}</span>}
      </p>
    </section>
  );
}
