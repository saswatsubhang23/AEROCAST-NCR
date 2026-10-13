"use client";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { formatAgeShort, labelOf, POLLUTANTS } from "@/lib/air/pollutants";
import type { PollutantKey, Station } from "@/lib/air/types";
import { formatIST } from "@/lib/weather/time";

export function StationTable({
  stations,
  pollutant,
  selectedId,
  compareIds,
  onSelect,
  onToggleCompare,
}: {
  stations: Station[];
  pollutant: PollutantKey;
  selectedId: number | null;
  compareIds: number[];
  onSelect: (id: number) => void;
  onToggleCompare: (id: number) => void;
}) {
  const columns: Column<Station>[] = [
    {
      key: "name",
      header: "Station",
      render: (s) => (
        <button
          onClick={() => onSelect(s.id)}
          aria-pressed={s.id === selectedId}
          className={`text-left hover:text-accent ${s.id === selectedId ? "font-semibold text-accent" : ""}`}
        >
          {s.name}
          {s.locality && <span className="block text-xs font-normal text-muted">{s.locality}</span>}
        </button>
      ),
    },
    {
      key: "latest",
      header: `Latest ${labelOf(pollutant)}`,
      render: (s) => {
        const r = s.latest[pollutant];
        if (r) return <span className="font-mono tabular-nums">{r.value} <span className="text-muted">{r.unit}</span></span>;
        if (!s.pollutants[pollutant]) return <span className="text-muted">No sensor</span>;
        return <span className="text-muted">{s.latest_status === "unavailable" ? "Could not load" : "No recent reading"}</span>;
      },
    },
    {
      key: "observed",
      header: "Observed (IST)",
      render: (s) => {
        const r = s.latest[pollutant];
        if (!r) return <span className="text-muted">—</span>;
        return (
          <span>
            {formatIST(r.observed_at)}
            <span className={`block text-xs ${r.stale ? "text-warn" : "text-muted"}`}>
              {formatAgeShort(r.age_s)}
              {r.stale && " · stale"}
            </span>
          </span>
        );
      },
    },
    {
      key: "measures",
      header: "Measures",
      render: (s) => (
        <span className="text-xs text-muted">
          {POLLUTANTS.filter((p) => s.pollutants[p.key]).map((p) => p.label).join(", ")}
        </span>
      ),
    },
    { key: "provider", header: "Provider", render: (s) => <span className="text-muted">{s.provider ?? "Unknown"}</span> },
    {
      key: "compare",
      header: "Compare",
      render: (s) => (
        <label className="flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            className="accent-accent"
            checked={s.id === selectedId || compareIds.includes(s.id)}
            disabled={s.id === selectedId}
            onChange={() => onToggleCompare(s.id)}
            aria-label={`Compare ${s.name}`}
          />
        </label>
      ),
    },
  ];

  return (
    <DataTable
      caption="Air-quality monitoring stations and their latest reading for the selected pollutant"
      columns={columns}
      rows={stations}
      rowKey={(s) => String(s.id)}
      empty={{ title: "No stations", message: "No active monitoring stations were found for Delhi-NCR." }}
    />
  );
}
