"use client";

import { Pause, Play, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { formatIST } from "@/lib/weather/time";

export const SPEEDS = [
  { label: "1×", ms: 900 },
  { label: "2×", ms: 450 },
  { label: "4×", ms: 225 },
];

export function TimelineControls({
  times,
  index,
  onIndex,
  playing,
  onPlaying,
  speed,
  onSpeed,
  onReset,
}: {
  times: string[];
  index: number;
  onIndex: (i: number) => void;
  playing: boolean;
  onPlaying: (p: boolean) => void;
  speed: number;
  onSpeed: (i: number) => void;
  onReset: () => void;
}) {
  const last = times.length - 1;
  return (
    <div className="rounded-lg border border-line bg-surface p-3" role="group" aria-label="Timeline controls">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon" aria-label="Previous hour" onClick={() => onIndex(Math.max(0, index - 1))} disabled={index <= 0}>
          <SkipBack className="h-4 w-4" aria-hidden="true" />
        </Button>
        <Button size="icon" variant="primary" aria-label={playing ? "Pause" : "Play"} aria-pressed={playing} onClick={() => onPlaying(!playing)} disabled={last <= 0}>
          {playing ? <Pause className="h-4 w-4" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
        </Button>
        <Button size="icon" aria-label="Next hour" onClick={() => onIndex(Math.min(last, index + 1))} disabled={index >= last}>
          <SkipForward className="h-4 w-4" aria-hidden="true" />
        </Button>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          Speed
          <select value={speed} onChange={(e) => onSpeed(Number(e.target.value))} className="h-8 rounded-md border border-line bg-surface-2 px-2 text-sm text-fg">
            {SPEEDS.map((s, i) => (
              <option key={s.label} value={i}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onReset}>
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Reset view
        </Button>
      </div>
      <div className="mt-3">
        <input
          type="range"
          min={0}
          max={Math.max(last, 0)}
          value={index}
          onChange={(e) => onIndex(Number(e.target.value))}
          aria-label="Time"
          aria-valuetext={times[index] ? formatIST(times[index]) : undefined}
          className="w-full accent-[var(--accent)]"
          disabled={last <= 0}
        />
        <div className="mt-1 flex justify-between font-mono text-xs text-muted">
          <span>{times[0] ? formatIST(times[0]) : ""}</span>
          <span className="text-fg">{times[index] ? formatIST(times[index]) : ""}</span>
          <span>{times[last] ? formatIST(times[last]) : ""}</span>
        </div>
      </div>
    </div>
  );
}
