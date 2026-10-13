"use client";

import dynamic from "next/dynamic";

// three.js and React Three Fiber need WebGL and are large: loaded in the browser, and only when the 3D view is opened.
export const AirFlow3D = dynamic(() => import("./AirFlow3D"), {
  ssr: false,
  loading: () => <div className="grid h-[min(72vh,640px)] min-h-[380px] place-items-center rounded-xl border border-line bg-surface text-sm text-muted">Loading the 3D scene…</div>,
});
