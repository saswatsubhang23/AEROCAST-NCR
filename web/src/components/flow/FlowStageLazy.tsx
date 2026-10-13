"use client";

import dynamic from "next/dynamic";

// MapLibre and deck.gl touch `window`; they load on the client only.
export const FlowStage = dynamic(() => import("./FlowStage"), {
  ssr: false,
  loading: () => <div className="grid h-[min(72vh,640px)] min-h-[380px] place-items-center rounded-xl border border-line bg-surface text-sm text-muted">Loading the map…</div>,
});
