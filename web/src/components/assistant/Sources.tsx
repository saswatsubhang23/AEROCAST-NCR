"use client";

import Link from "next/link";
import type { SourceRef } from "@/lib/assistant/types";
import { formatIST } from "@/lib/weather/time";

const KIND: Record<SourceRef["kind"], string> = {
  weather_observation: "Weather (model)",
  weather_forecast: "Weather forecast (model)",
  air_quality: "Air-quality observations",
  knowledge_base: "Knowledge-base passage",
  report: "Generated report",
  pollution_forecast: "Pollution forecast (trained model)",
};

export function Sources({ messageId, sources }: { messageId: string; sources: SourceRef[] }) {
  if (sources.length === 0) return null;
  return (
    <details open className="mt-3 rounded-md border border-line bg-bg/40">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted">Sources ({sources.length})</summary>
      <ul className="divide-y divide-line border-t border-line">
        {sources.map((s) => (
          <li key={s.id} id={`src-${messageId}-${s.id}`} className="scroll-mt-24 px-3 py-2 text-xs target:bg-surface-2">
            <p>
              <span className="mr-2 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-accent">{s.id}</span>
              <span className="font-medium text-fg">{s.title}</span>
            </p>
            <p className="mt-1 text-muted">
              {KIND[s.kind]} ·{" "}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">{s.provider}</a>
              ) : (
                s.provider
              )}
              {s.period_start && s.period_end && ` · covers ${formatIST(s.period_start)} to ${formatIST(s.period_end)}`}
              {` · retrieved ${formatIST(s.retrieved_at)}`}
            </p>
            {s.kind === "knowledge_base" && (
              <>
                <p className="mt-1">
                  {s.category && <span className="mr-2 rounded bg-surface-2 px-1.5 py-0.5 text-fg">{s.category}</span>}
                  {s.reference && <span className="text-muted">{s.reference}</span>}
                  {s.document_id && (
                    <Link href={`/knowledge?doc=${s.document_id}`} className="ml-2 text-accent underline hover:no-underline">Open document</Link>
                  )}
                </p>
                {s.excerpt && (
                  <blockquote className="mt-1 border-l-2 border-line pl-2 text-muted">
                    <span className="sr-only">Retrieved passage: </span>“{s.excerpt}”
                  </blockquote>
                )}
              </>
            )}
            {s.note && <p className="mt-0.5 text-muted">{s.note}</p>}
          </li>
        ))}
      </ul>
    </details>
  );
}
