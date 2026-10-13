"use client";

import { LoadingState } from "@/components/ui/states";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { fetchRegimes } from "@/lib/twin/api";
import { useOptional } from "@/lib/twin/useOptional";

const f = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : v.toFixed(1));

/** Learned weather regimes and how PM2.5 differed between them on the held-out period (an association, not a cause). */
export function RegimePanel({ time, stationId }: { time: string | null; stationId: number | null }) {
  const reg = useOptional(true, `regimes:${time}`, (s) => fetchRegimes(time, s));
  if (reg.status === "idle" || reg.status === "loading") return <LoadingState label="Loading regime analysis" />;
  if (reg.status === "error")
    return (
      <div className="rounded-lg border border-line bg-surface p-4 text-sm" role="status">
        <p className="flex items-center gap-2 font-medium">
          Atmospheric regimes <ProvenanceBadge kind="unavailable" />
        </p>
        <p className="mt-1 text-muted">{reg.error.message}</p>
      </div>
    );
  const r = reg.data;
  const here = r.stations?.find((s) => s.station_id === stationId)?.regime;
  return (
    <section aria-label="Atmospheric regimes" className="space-y-2 rounded-lg border border-line bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">Atmospheric regimes</h2>
        <ProvenanceBadge kind="derived" detail={r.method} />
      </div>
      <p className="text-xs text-muted">
        {r.regimes.length} regimes learned from weather on data before {r.dev_end.slice(0, 10)}. {here !== undefined && <>Selected station at this hour: <strong className="text-fg">{r.regimes[here]?.label}</strong>. </>}
        {r.caveat}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-96 text-left text-xs">
          <caption className="sr-only">PM2.5 by weather regime, development and held-out periods</caption>
          <thead className="border-b border-line uppercase tracking-wider text-muted">
            <tr>
              {["Regime", "Dev median (n)", "Test median (n)"].map((h) => (
                <th key={h} scope="col" className="px-2 py-1 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {r.regimes.map((g) => (
              <tr key={g.index} className={g.index === here ? "bg-surface-2" : undefined}>
                <td className="px-2 py-1">{g.label}</td>
                <td className="px-2 py-1 font-mono tabular-nums">{f(g.development?.pm_median)} ({g.development?.pm_n.toLocaleString() ?? 0})</td>
                <td className="px-2 py-1 font-mono tabular-nums">{f(g.test?.pm_median)} ({g.test?.pm_n.toLocaleString() ?? 0}){r.small_test_samples.map(String).includes(String(g.index)) ? " small sample" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        {r.kruskal_wallis_test_period ? `Kruskal-Wallis across regimes on the held-out period: H = ${r.kruskal_wallis_test_period.statistic.toFixed(1)}, p ${r.kruskal_wallis_test_period.p_value < 1e-300 ? "< 1e-300 (below floating-point resolution)" : "= " + r.kruskal_wallis_test_period.p_value.toExponential(2)} (${r.kruskal_wallis_test_period.groups_tested} groups).` : "Too few held-out samples for a test."}
      </p>
    </section>
  );
}
