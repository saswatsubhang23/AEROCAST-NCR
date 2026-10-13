"use client";

import dynamic from "next/dynamic";
import { LoadingState } from "@/components/ui/states";

// MapLibre and deck.gl need the browser (WebGL), so they are never rendered on the server.
export const WeatherMap = dynamic(() => import("./WeatherMapPanel"), {
  ssr: false,
  loading: () => <LoadingState label="Loading map" />,
});
