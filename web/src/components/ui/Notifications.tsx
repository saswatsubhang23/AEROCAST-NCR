"use client";

import { createContext, useCallback, useContext, useState } from "react";

type Kind = "info" | "warn" | "error";
type Toast = { id: number; kind: Kind; message: string };
const Ctx = createContext<((message: string, kind?: Kind) => void) | null>(null);

const border: Record<Kind, string> = {
  info: "border-accent/50",
  warn: "border-warn/60",
  error: "border-danger/60",
};

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));
  const notify = useCallback((message: string, kind: Kind = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  return (
    <Ctx.Provider value={notify}>
      {children}
      <div
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`flex items-start justify-between gap-3 rounded-lg border bg-surface-2 p-3 text-sm shadow-lg ${border[t.kind]}`}
          >
            <p>{t.message}</p>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification" className="text-muted hover:text-fg">
              ✕
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useNotify() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useNotify outside NotificationProvider");
  return ctx;
}
