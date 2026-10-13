"use client";

import { btnSecondary } from "@/components/ui/states";
import type { Resource } from "@/lib/weather/context";
import type { AssistantStatus } from "@/lib/assistant/types";

/** Tells the user whether the assistant can answer, and why not. The rest of the page stays usable either way. */
export function StatusBanner({ status, onRecheck }: { status: Resource<AssistantStatus>; onRecheck: () => void }) {
  if (status.status === "loading")
    return <p role="status" className="mb-4 text-xs text-muted">Checking the language model…</p>;

  if (status.status === "error")
    return (
      <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/40 bg-danger/5 p-3 text-sm">
        <div>
          <p className="font-medium text-danger">Cannot reach the AEROCAST API</p>
          <p className="text-muted">{status.error.message} Your conversation is kept; you can read and copy it, but new questions need the API.</p>
        </div>
        <button className={btnSecondary} onClick={onRecheck}>Check again</button>
      </div>
    );

  const s = status.data;
  if (!s.available)
    return (
      <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warn/50 bg-warn/5 p-3 text-sm">
        <div>
          <p className="font-medium text-warn">The assistant is not available</p>
          <p className="text-muted">{s.message}</p>
          <p className="mt-1 text-xs text-muted">Weather and Air Quality pages still work. Set OLLAMA_BASE_URL / OLLAMA_MODEL in api/.env, then check again.</p>
        </div>
        <button className={btnSecondary} onClick={onRecheck}>Check again</button>
      </div>
    );

  return (
    <p className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
        Model {s.model}
      </span>
      <span>Answers use live data and cite their sources.</span>
      <span>{s.pollution_forecast_note}</span>
      {s.knowledge_base === "unavailable" && <span>{s.knowledge_base_note}</span>}
    </p>
  );
}
