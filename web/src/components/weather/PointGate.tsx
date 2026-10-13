"use client";

import { ErrorState, LoadingState } from "@/components/ui/states";
import { useWeather } from "@/lib/weather/context";
import type { PointForecast } from "@/lib/weather/types";

/** Shared loading / error / ready handling for anything built on the selected location's forecast. */
export function PointGate({ children }: { children: (data: PointForecast) => React.ReactNode }) {
  const { point, refresh } = useWeather();
  if (point.status === "loading") return <LoadingState label="Loading forecast" />;
  if (point.status === "error")
    return (
      <ErrorState
        title="Weather data is unavailable"
        message={`${point.error.message}${point.error.requestId ? ` (request ${point.error.requestId})` : ""}`}
        onRetry={refresh}
      />
    );
  return <>{children(point.data)}</>;
}
