"use client";

import dynamic from "next/dynamic";
import { LoadingState } from "@/components/ui/states";

// MapLibre and deck.gl need WebGL, so they are loaded in the browser only and only when this route is opened.
export const TwinMap = dynamic(() => import("./TwinMap"), {
  ssr: false,
  loading: () => <LoadingState label="Loading map" />,
});
