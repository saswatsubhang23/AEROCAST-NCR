"use client";

import dynamic from "next/dynamic";
import { LoadingState } from "@/components/ui/states";

export const StationMap = dynamic(() => import("./StationMapPanel"), {
  ssr: false,
  loading: () => <LoadingState label="Loading map" />,
});
