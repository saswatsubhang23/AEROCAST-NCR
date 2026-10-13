"use client";

import { MapLegend } from "@/components/ui/MapLegend";
import { ProvenanceBadge, type Provenance } from "@/components/ui/ProvenanceBadge";
import { layerSetting, layersForLens, statusOf } from "@/lib/twin/layers/definitions";
import { ageText } from "@/lib/twin/layers/staleness";
import type { LayerContext, LegendSpec, Surface } from "@/lib/twin/layers/types";
import { twinStore, useTwinState, type DataStatus } from "@/lib/twin/store";
import { formatIST } from "@/lib/weather/time";

/** The badge each data status shows, everywhere: map badge, layer rows, legends. */
export const STATUS_BADGE: Record<DataStatus, Provenance> = {
  observation: "observed",
  derived: "derived",
  interpolation: "estimate",
  model: "weather_forecast",
  forecast: "model_forecast",
  simulation: "simulated",
  scenario: "hypothetical",
};

/** Every layer of the active lens, from the registry: visibility, opacity, what kind of data it is, and why it is unavailable when it is. */
export function LayerPanel({ ctx, surface }: { ctx: LayerContext; surface?: Surface }) {
  const settings = useTwinState((s) => s.layers);
  const entries = layersForLens(ctx, surface).filter((e) => e.def.id !== "inspect-point");
  const ORDER = ["Observations", "Estimates", "Weather model", "Simulation"];
  const groups = [...new Set(entries.map((e) => e.def.group))].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b));
  const exclusive = entries.filter((e) => e.def.exclusive);
  const firstVisibleExclusive = exclusive.find((e) => layerSetting(e.def, settings).visible && !e.unavailable)?.def.id;

  return (
    <section aria-label="Layers" className="rounded-lg border border-line bg-surface p-3">
      <h2 className="mb-1 text-sm font-semibold">Layers</h2>
      {groups.map((group) => (
        <fieldset key={group} className="min-w-0 border-b border-line py-1.5 last:border-0">
          <legend className="text-xs font-medium uppercase tracking-wider text-muted">{group}</legend>
          {entries.filter((e) => e.def.group === group).map(({ def, unavailable }) => {
            const set = layerSetting(def, settings);
            const isExclusive = !!def.exclusive;
            const checked = isExclusive ? def.id === firstVisibleExclusive : set.visible && !unavailable;
            return (
              <div key={def.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1">
                <label className="flex min-w-48 items-center gap-2 text-sm">
                  <input
                    type={isExclusive ? "radio" : "checkbox"}
                    name={isExclusive ? def.exclusive : undefined}
                    checked={checked}
                    disabled={!!unavailable}
                    onChange={(e) => {
                      if (isExclusive) {
                        for (const o of exclusive) twinStore.setLayer(o.def.id, { visible: o.def.id === def.id }, { visible: o.def.defaultVisible, opacity: o.def.defaultOpacity });
                      } else twinStore.setLayer(def.id, { visible: e.target.checked }, { visible: def.defaultVisible, opacity: def.defaultOpacity });
                    }}
                    className="h-4 w-4 accent-[var(--accent)]"
                  />
                  <span>{def.label}</span>
                </label>
                <ProvenanceBadge kind={STATUS_BADGE[statusOf(def, ctx)]} />
                {def.opacity && (
                  <label className="ml-auto flex items-center gap-1.5 text-xs text-muted">
                    Opacity
                    <input
                      type="range" min={20} max={100} step={5} value={Math.round(set.opacity * 100)} disabled={!checked} aria-label={`${def.label} opacity`}
                      onChange={(e) => twinStore.setLayer(def.id, { opacity: Number(e.target.value) / 100 }, { visible: def.defaultVisible, opacity: def.defaultOpacity })}
                      className="w-24 accent-[var(--accent)]"
                    />
                  </label>
                )}
                <p className="basis-full text-xs text-muted">{unavailable ?? def.help}</p>
              </div>
            );
          })}
        </fieldset>
      ))}
    </section>
  );
}

/** One legend per drawn layer: title, unit, classes, the instant its values describe, how old that is, and the kind of data. */
export function LegendPanel({ legends }: { legends: LegendSpec[] }) {
  if (legends.length === 0) return <p className="rounded-lg border border-line bg-surface p-3 text-xs text-muted">No layer with a scale is drawn at the moment.</p>;
  return (
    <section aria-label="Legends" className="space-y-2">
      {legends.map((l) => (
        <div key={l.layerId}>
          <MapLegend title={l.title} unit={l.unit} items={l.items} />
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <ProvenanceBadge kind={STATUS_BADGE[l.status]} />
            {l.stale && <ProvenanceBadge kind="stale" detail="The data are older than the freshness limit for this kind of layer." />}
            {l.sourceTime ? (
              <span>
                Source time {formatIST(l.sourceTime)} ({ageText(l.ageHours)})
              </span>
            ) : (
              <span>Source time unknown</span>
            )}
          </p>
          {l.note && <p className="text-xs text-muted">{l.note}</p>}
        </div>
      ))}
    </section>
  );
}

