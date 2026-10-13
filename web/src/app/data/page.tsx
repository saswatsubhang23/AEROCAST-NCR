"use client";

import { useMemo, useState } from "react";
import { Chip, Dot, Kicker, Segmented } from "@/components/ui/Glass";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fetchAvailability, type AvailabilityItem, type AvailabilityStatus } from "@/lib/data/availability";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

const STATUS: Record<AvailabilityStatus, { label: string; tone: "ok" | "warn" | "danger" | "neutral" | "accent"; dot: "ok" | "warn" | "danger" | "idle" | "accent" }> = {
  available: { label: "Available", tone: "ok", dot: "ok" },
  partial: { label: "Partial", tone: "warn", dot: "warn" },
  stale: { label: "Stale", tone: "warn", dot: "warn" },
  obtainable: { label: "Obtainable", tone: "accent", dot: "accent" },
  missing: { label: "Not available", tone: "danger", dot: "danger" },
};

type Filter = "all" | "gaps" | "missing";

function Item({ item }: { item: AvailabilityItem }) {
  const st = STATUS[item.status];
  return (
    <li className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 text-sm font-semibold leading-snug">{item.name}</h3>
        <Chip tone={st.tone} icon={<Dot tone={st.dot} />}>{st.label}</Chip>
      </div>
      <p className="mt-1.5 text-sm text-muted">{item.detail}</p>
      <dl className="mt-3 grid gap-x-4 gap-y-1.5 text-xs sm:grid-cols-[7.5rem_1fr]">
        <dt className="text-muted">Source</dt>
        <dd>{item.source}</dd>
        <dt className="text-muted">Used for</dt>
        <dd>{item.used_for}</dd>
        {item.consequence && (
          <>
            <dt className={item.status === "available" ? "text-muted" : "text-warn"}>{item.status === "available" ? "Caveat" : "What this prevents"}</dt>
            <dd>{item.consequence}</dd>
          </>
        )}
        {item.how_to_get && (
          <>
            <dt className="text-muted">How to get it</dt>
            <dd>{item.how_to_get}</dd>
          </>
        )}
      </dl>
    </li>
  );
}

export default function DataCoveragePage() {
  const res = useResource("data-availability", 0, (s) => fetchAvailability(s));
  const [filter, setFilter] = useState<Filter>("gaps");
  const groups = useMemo(() => {
    if (res.status !== "ready") return [];
    return res.data.groups
      .map((g) => ({ ...g, items: g.items.filter((i) => (filter === "all" ? true : filter === "missing" ? i.status === "missing" : i.status !== "available")) }))
      .filter((g) => g.items.length > 0);
  }, [res, filter]);

  return (
    <div className="space-y-6">
      <header>
        <Kicker>Data coverage</Kicker>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">What the application knows, and what it does not</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Every number on the maps comes from one of these sources. Where a source is missing, partial or out of date, the application says so on the page that
          would have used it and leaves the space empty; it does not fill it with synthetic values.
        </p>
      </header>

      {res.status === "loading" && <LoadingState label="Checking the sources" />}
      {res.status === "error" && <ErrorState title="Coverage could not be assessed" message={res.error.message} />}
      {res.status === "ready" && (
        <>
          <ul className="grid gap-3 sm:grid-cols-5" aria-label="Summary">
            {(["available", "partial", "stale", "obtainable", "missing"] as AvailabilityStatus[]).map((k) => (
              <li key={k} className="card p-4">
                <div className="flex items-center gap-2 text-xs text-muted"><Dot tone={STATUS[k].dot} />{STATUS[k].label}</div>
                <div className="mt-1 text-3xl font-semibold tabular">{res.data.counts[k]}</div>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              label="Show" value={filter} onChange={setFilter}
              options={[{ value: "gaps", label: "Gaps and caveats" }, { value: "missing", label: "Not available" }, { value: "all", label: "Everything" }]}
            />
            <span className="text-xs text-muted">Assessed {formatIST(res.data.generated_at)}</span>
          </div>
          {groups.map((g) => (
            <section key={g.key} aria-labelledby={`g-${g.key}`}>
              <h2 id={`g-${g.key}`} className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">{g.label}</h2>
              <ul className="grid gap-3 lg:grid-cols-2">{g.items.map((i) => <Item key={i.id} item={i} />)}</ul>
            </section>
          ))}
          <p className="rounded-lg border border-line p-3 text-sm text-muted">{res.data.principle}</p>
        </>
      )}
    </div>
  );
}
