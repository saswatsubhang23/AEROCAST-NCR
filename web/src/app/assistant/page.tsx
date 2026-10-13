"use client";

import { useEffect, useRef, useState } from "react";
import { Composer } from "@/components/assistant/Composer";
import { Message } from "@/components/assistant/Message";
import { StatusBanner } from "@/components/assistant/StatusBanner";
import { Dialog } from "@/components/ui/Dialog";
import { PageHeader } from "@/components/ui/PageHeader";
import { btnPrimary, btnSecondary } from "@/components/ui/states";
import { fetchAssistantStatus } from "@/lib/assistant/api";
import { suggestionsFor } from "@/lib/assistant/suggestions";
import { useChat } from "@/lib/assistant/useChat";
import { useLocation } from "@/lib/location";
import { useResource } from "@/lib/weather/context";

export default function AssistantPage() {
  const { location } = useLocation();
  const [version, setVersion] = useState(0);
  const status = useResource("assistant-status", version, (s) => fetchAssistantStatus(s));
  const { messages, streaming, statusText, send, retry, stop, clear } = useChat(location.id);
  const [confirmClear, setConfirmClear] = useState(false);

  // Keep the newest text in view while it streams, unless the reader has scrolled up.
  const list = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = list.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, statusText]);

  const available = status.status === "ready" && status.data.available;
  const reason =
    status.status === "loading" ? "Checking the language model…"
    : status.status === "error" ? "The AEROCAST API cannot be reached."
    : status.data.available ? null
    : (status.data.message ?? "The language model is not available.");

  return (
    <>
      <PageHeader
        title="AI Assistant"
        description="Ask about weather and air quality. Answers are written from data retrieved at the moment you ask, and cite their sources."
        actions={
          <button className={btnSecondary} onClick={() => setConfirmClear(true)} disabled={messages.length === 0}>
            New conversation
          </button>
        }
      />
      <StatusBanner status={status} onRecheck={() => setVersion((v) => v + 1)} />

      <section aria-label="Conversation" className="rounded-lg border border-line bg-surface">
        <div
          ref={list}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          role="log"
          aria-live="off"
          aria-label="Messages"
          className="max-h-[60vh] min-h-72 overflow-y-auto p-4"
        >
          {messages.length === 0 ? (
            <div>
              <p className="text-sm font-medium">Try asking</p>
              <p className="mt-1 text-xs text-muted">
                Questions use {location.name} as context when you do not name a city. Change it in the top bar.
              </p>
              <ul className="mt-3 flex flex-col gap-2">
                {suggestionsFor(location.name, status.status === "ready" && status.data.knowledge_base === "ready").map((q) => (
                  <li key={q}>
                    <button
                      onClick={() => send(q)}
                      disabled={!available || streaming}
                      className="w-full rounded-md border border-line bg-surface-2 px-3 py-2 text-left text-sm transition-colors hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
              {status.status === "ready" && status.data.knowledge_base === "unavailable" && (
                <p className="mt-4 text-xs text-muted">Knowledge-base questions need indexed documents. Add some on the Knowledge Base page.</p>
              )}
            </div>
          ) : (
            <ul className="space-y-4">
              {messages.map((m, i) => (
                <Message
                  key={m.id}
                  message={m}
                  streaming={streaming && i === messages.length - 1}
                  statusText={statusText}
                  onRetry={retry}
                />
              ))}
            </ul>
          )}
        </div>
        <p className="sr-only" role="status" aria-live="polite">{streaming ? "The assistant is answering" : ""}</p>
        <Composer disabled={!available} disabledReason={reason} streaming={streaming} onSend={send} onStop={stop} />
      </section>

      <Dialog open={confirmClear} onClose={() => setConfirmClear(false)} title="Start a new conversation?">
        <p className="text-muted">This clears the conversation stored in this browser.</p>
        <div className="mt-4">
          <button
            className={btnPrimary}
            onClick={() => {
              clear();
              setConfirmClear(false);
            }}
          >
            Clear conversation
          </button>
        </div>
      </Dialog>
    </>
  );
}
