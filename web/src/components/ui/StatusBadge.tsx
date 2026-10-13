import type { SourceRow } from "@/lib/health";

const STYLE: Record<SourceRow["state"], { dot: string; label: string }> = {
  ok: { dot: "bg-accent", label: "Connected" },
  degraded: { dot: "bg-warn", label: "Degraded" },
  down: { dot: "bg-danger", label: "Unreachable" },
  pending: { dot: "border border-muted bg-transparent", label: "Not integrated" },
  unknown: { dot: "bg-muted", label: "Unknown" },
};

/** Status is always conveyed by text as well as colour. */
export function StatusBadge({ state }: { state: SourceRow["state"] }) {
  const s = STYLE[state];
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden="true" />
      {s.label}
    </span>
  );
}
