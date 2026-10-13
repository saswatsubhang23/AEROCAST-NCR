"use client";

import { useRef, useState } from "react";
import { EmptyState, ErrorState, LoadingState, btnPrimary } from "@/components/ui/states";
import { searchKb } from "@/lib/kb/api";
import type { KbLimits, SearchResult } from "@/lib/kb/types";
import { safeHref } from "@/lib/kb/validate";
import { ApiError } from "@/lib/weather/api";

const field = "h-9 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg placeholder:text-muted";

const MESSAGES: Record<Exclude<SearchResult["status"], "ok">, string> = {
  no_relevant_passages: "Nothing in the knowledge base is relevant enough to this question.",
  empty: "There are no searchable documents yet.",
  document_not_found: "No document matches that name.",
  unavailable: "Search is unavailable right now.",
};

export function SearchPanel({ limits, onOpen }: { limits: KbLimits; onOpen: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [topK, setTopK] = useState(5);
  const [state, setState] = useState<{ status: "idle" } | { status: "loading" } | { status: "error"; error: ApiError } | { status: "done"; result: SearchResult; query: string }>({ status: "idle" });
  const seq = useRef(0);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const query = q.trim();
    if (query.length < 2) return;
    const mine = ++seq.current;
    setState({ status: "loading" });
    try {
      const result = await searchKb(query, topK, category);
      if (mine === seq.current) setState({ status: "done", result, query });
    } catch (err) {
      if (mine === seq.current) setState({ status: "error", error: err instanceof ApiError ? err : new ApiError("Search failed.", 0) });
    }
  }

  return (
    <div>
      <form onSubmit={run} role="search" className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-3">
        <label className="flex min-w-60 flex-1 flex-col gap-1 text-xs font-medium text-muted">
          Ask a question or describe what you are looking for
          <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} placeholder="e.g. How many hours of data does a sub-index need?" className={`${field} w-full`} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Document type
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={field}>
            <option value="">All types</option>
            {Object.entries(limits.categories).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Results
          <select value={topK} onChange={(e) => setTopK(Number(e.target.value))} className={field}>
            {[3, 5, 10].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button type="submit" className={btnPrimary} disabled={q.trim().length < 2 || state.status === "loading"}>Search</button>
      </form>

      <div className="mt-3" aria-live="polite">
        {state.status === "loading" && <LoadingState label="Searching" />}
        {state.status === "error" && <ErrorState title="Search failed" message={state.error.message} />}
        {state.status === "done" && state.result.status !== "ok" && (
          <div className="space-y-2">
            <EmptyState title={MESSAGES[state.result.status]} message={state.result.reason ?? ""} />
            {state.result.available_documents.length > 0 && (
              <p className="text-xs text-muted">Available documents: {state.result.available_documents.join("; ")}</p>
            )}
          </div>
        )}
        {state.status === "done" && state.result.status === "ok" && (
          <>
            <p className="mb-2 text-xs text-muted">
              {state.result.passages.length} passage(s) for “{state.query}”. Relevance is similarity to your question; passages below{" "}
              {state.result.min_score.toFixed(2)} are hidden. Check that a passage really answers it.
            </p>
            <ul className="space-y-3">
              {state.result.passages.map((p, i) => {
                const href = safeHref(p.source_url);
                return (
                  <li key={`${p.document_id}-${i}`} className="rounded-lg border border-line bg-surface p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                      <p>
                        <button className="text-sm font-medium hover:text-accent" onClick={() => onOpen(p.document_id)}>{p.title}</button>
                        <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-muted">{p.category_label}</span>
                        {p.location && <span className="ml-2 text-muted">{p.location}</span>}
                      </p>
                      <span className="font-mono text-muted" title="Cosine similarity">relevance {(p.score * 100).toFixed(0)}%</span>
                    </div>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{p.text}</p>
                    <p className="mt-2 text-xs text-muted">
                      {p.publisher ?? "Publisher not given"}
                      {p.licence && ` · ${p.licence}`}
                      {href && <> · <a href={href} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">source</a></>}
                    </p>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
