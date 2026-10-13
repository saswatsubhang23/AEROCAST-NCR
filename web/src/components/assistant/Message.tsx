"use client";

import { useState } from "react";
import { describeTool } from "@/lib/assistant/reducer";
import type { ChatMessage } from "@/lib/assistant/types";
import { formatIST } from "@/lib/weather/time";
import { Markdown } from "./Markdown";
import { Sources } from "./Sources";

const small = "inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 text-xs text-fg transition-colors hover:border-accent/60";

/** The answer plus its citations as plain text, for pasting into a report or an email. */
export function copyText(m: ChatMessage): string {
  const src = (m.sources ?? []).map((s) => `[${s.id}] ${s.title} (${s.provider}, retrieved ${formatIST(s.retrieved_at)})`);
  return src.length ? `${m.content.trim()}\n\nSources:\n${src.join("\n")}` : m.content.trim();
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

function CopyButton({ message }: { message: ChatMessage }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      className={small}
      onClick={async () => {
        setState((await copyToClipboard(copyText(message))) ? "copied" : "failed");
        setTimeout(() => setState("idle"), 2000);
      }}
      aria-label="Copy response"
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}
    </button>
  );
}

export function Message({
  message, streaming, statusText, onRetry,
}: { message: ChatMessage; streaming: boolean; statusText: string | null; onRetry: () => void }) {
  if (message.role === "user") {
    return (
      <li className="flex justify-end">
        <div className="max-w-[85%]">
          <p className="whitespace-pre-wrap rounded-lg bg-accent-2/25 px-3.5 py-2.5 text-sm">{message.content}</p>
          <p className="mt-1 text-right text-xs text-muted">{formatIST(message.createdAt)}</p>
        </div>
      </li>
    );
  }

  const d = message.done;
  const failedTools = (message.tools ?? []).filter((t) => !t.ok);
  const waiting = streaming && !message.content && !message.error;

  return (
    <li className="flex">
      <article className="w-full max-w-[95%] rounded-lg border border-line bg-surface p-4" aria-label="Assistant answer">
        {(message.tools?.length ?? 0) > 0 && (
          <ul className="mb-3 flex flex-wrap gap-1.5" aria-label="Data retrieved for this answer">
            {message.tools!.map((t, i) => (
              <li key={i} className={`rounded-full border px-2 py-0.5 text-xs ${t.ok ? "border-line text-muted" : "border-warn/50 text-warn"}`}>
                {t.ok ? "Retrieved" : "Could not retrieve"}: {describeTool(t.name, t.args)}
              </li>
            ))}
          </ul>
        )}

        {waiting && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted">
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden="true" />
            {statusText ?? "Working…"}
          </p>
        )}

        {message.content && (
          <Markdown text={message.content} messageId={message.id} sourceIds={(message.sources ?? []).map((s) => s.id)} />
        )}
        {streaming && message.content && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-middle" aria-hidden="true" />}

        {message.error && (
          <div role="alert" className="mt-2 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
            <p className="font-medium text-danger">
              {message.error.code === "model_missing" || message.error.code === "llm_unavailable" || message.error.code === "model_no_tools"
                ? "The assistant is not available"
                : "The answer could not be completed"}
            </p>
            <p className="mt-1 text-muted">{message.error.message}</p>
            <button className={`${small} mt-2`} onClick={onRetry}>Try again</button>
          </div>
        )}
        {message.stopped && (
          <p className="mt-2 text-xs text-muted">
            Stopped. <button className="text-accent hover:underline" onClick={onRetry}>Ask again</button>
          </p>
        )}

        {d && d.answered_without_data && (
          <p role="note" className="mt-3 rounded-md border border-warn/40 bg-warn/5 p-2 text-xs text-warn">
            No data was retrieved for this answer. Treat any figures in it as unverified.
          </p>
        )}
        {d && !d.answered_without_data && d.ungrounded_numbers.length > 0 && (
          <p role="note" className="mt-3 rounded-md border border-warn/40 bg-warn/5 p-2 text-xs text-warn">
            Some figures here ({d.ungrounded_numbers.join(", ")}) were not found in the retrieved data. Check them against the sources.
          </p>
        )}
        {d && d.uncited && !d.answered_without_data && (message.sources?.length ?? 0) > 0 && (
          <p role="note" className="mt-3 rounded-md border border-warn/40 bg-warn/5 p-2 text-xs text-warn">
            This answer does not cite any of the sources retrieved for it. Compare it with the sources below before relying on it.
          </p>
        )}
        {d && (d.unknown_citations?.length ?? 0) > 0 && (
          <p role="note" className="mt-3 rounded-md border border-warn/40 bg-warn/5 p-2 text-xs text-warn">
            This answer cites {d.unknown_citations!.map((c) => `[${c}]`).join(", ")}, which does not match any source that was retrieved. Do not rely on those citations.
          </p>
        )}
        {failedTools.length > 0 && (
          <ul role="note" className="mt-3 list-disc rounded-md border border-line bg-bg/40 p-2 pl-6 text-xs text-muted">
            {failedTools.map((t, i) => (
              <li key={i}>{describeTool(t.name, t.args)}: {t.error}</li>
            ))}
          </ul>
        )}

        <Sources messageId={message.id} sources={message.sources ?? []} />

        {message.content && !streaming && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span>
              {formatIST(d?.finished_at ?? message.createdAt)}
              {d && ` · ${d.model} · ${(d.duration_ms / 1000).toFixed(1)} s`}
            </span>
            <CopyButton message={message} />
          </div>
        )}
      </article>
    </li>
  );
}

