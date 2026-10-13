"use client";

import { useWeather } from "@/lib/weather/context";
import { formatIST, formatUTC } from "@/lib/weather/time";
import type { PointForecast } from "@/lib/weather/types";
import { btnSecondary } from "@/components/ui/states";

/** The single time control for the page. Its range is exactly the coverage the provider returned. */
export function Timeline({ data }: { data: PointForecast }) {
  const { selected, setSelected } = useWeather();
  const last = data.times.length - 1;
  const iso = data.times[selected];
  const offset = selected === 0 ? "current hour" : `+${selected} h`;

  return (
    <div className="sticky top-14 z-10 mb-5 rounded-lg border border-line bg-bg/95 p-3 backdrop-blur-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-muted">Selected time</p>
          <p className="font-mono text-sm font-semibold tabular-nums">
            {formatIST(iso)} <span className="font-normal text-muted">({formatUTC(iso)}, {offset})</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className={btnSecondary} onClick={() => setSelected(selected - 1)} disabled={selected <= 0} aria-label="−1 h, previous hour">
            −1 h
          </button>
          <button className={btnSecondary} onClick={() => setSelected(selected + 1)} disabled={selected >= last} aria-label="+1 h, next hour">
            +1 h
          </button>
          <button className={btnSecondary} onClick={() => setSelected(0)} disabled={selected === 0}>
            Now
          </button>
        </div>
      </div>
      <input
        type="range"
        min={0}
        max={last}
        step={1}
        value={selected}
        onChange={(e) => setSelected(Number(e.target.value))}
        aria-label="Forecast hour"
        aria-valuetext={`${formatIST(iso)}, ${offset}`}
        className="mt-3 w-full accent-accent"
      />
      <div className="flex justify-between text-xs text-muted">
        <span>{formatIST(data.times[0])}</span>
        <span>
          Horizon: {data.coverage.hours} h
          {data.coverage.hours < data.coverage.max_hours && ` (provider covers less than ${data.coverage.max_hours} h)`}
        </span>
        <span>{formatIST(data.times[last])}</span>
      </div>
    </div>
  );
}
