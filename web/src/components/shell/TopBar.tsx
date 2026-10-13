"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { deriveSources, useHealth } from "@/lib/health";
import { useLocation } from "@/lib/location";
import { LOCATIONS } from "@/lib/locations";

function SourceStatus() {
  const { state } = useHealth();
  const rows = deriveSources(state).filter((r) => r.state !== "pending");
  const down = rows.filter((r) => r.state === "down").length;
  const degraded = rows.filter((r) => r.state === "degraded").length;

  let dot = "bg-accent";
  let text = "All services connected";
  if (state.status === "loading") {
    dot = "bg-muted";
    text = "Checking services";
  } else if (state.status === "offline") {
    dot = "bg-danger";
    text = "API unreachable";
  } else if (down) {
    dot = "bg-danger";
    text = `${down} check${down > 1 ? "s" : ""} failing`;
  } else if (degraded) {
    dot = "bg-warn";
    text = `${degraded} warning${degraded > 1 ? "s" : ""}`;
  }

  return (
    <Tooltip text="Open Settings & Data Sources for details" align="end">
      <Link
        href="/settings"
        className="flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm hover:border-accent/60"
      >
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />
        <span className="hidden sm:inline">{text}</span>
        <span className="sr-only sm:hidden">{text}</span>
      </Link>
    </Tooltip>
  );
}

export function TopBar({ onMenu, menuOpen }: { onMenu: () => void; menuOpen: boolean }) {
  const { location, setLocationId } = useLocation();
  return (
    <div className="flex h-14 items-center gap-3 border-b border-line bg-bg px-4 lg:px-6">
      <button
        onClick={onMenu}
        aria-label="Open navigation"
        aria-expanded={menuOpen}
        className="rounded-md p-1.5 text-muted hover:text-fg lg:hidden"
      >
        <Icon name="menu" />
      </button>
      <label className="flex items-center gap-2 text-sm">
        <Icon name="pin" className="h-4 w-4 text-muted" />
        <span className="sr-only">Location</span>
        <select
          value={location.id}
          onChange={(e) => setLocationId(e.target.value)}
          className="h-9 rounded-md border border-line bg-surface px-2.5 text-sm"
        >
          {LOCATIONS.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      <div className="ml-auto flex items-center gap-2">
        <Tooltip text="Which data the application has, and which it does not" align="end">
          <Link href="/data" className="flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm text-muted hover:border-accent/60 hover:text-fg">
            <Icon name="database" className="h-4 w-4" />
            <span className="hidden md:inline">Data coverage</span>
            <span className="sr-only md:hidden">Data coverage</span>
          </Link>
        </Tooltip>
        <SourceStatus />
      </div>
    </div>
  );
}
