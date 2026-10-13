"use client";

import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { layersForLens } from "@/lib/twin/layers/definitions";
import type { LayerContext } from "@/lib/twin/layers/types";
import type { SceneData } from "@/lib/twin/scene/data";
import { TERRAIN_EXAGGERATION } from "@/lib/terrain/terrain";
import { VERTICAL_EXAGGERATION } from "@/lib/twin/scene/geometry";

/** Says plainly what in the 3D scene is data, what is a model assumption and what is only a frame of reference. */
export function SceneNotes({ ctx, data, terrainState }: { ctx: LayerContext; data: SceneData; terrainState: "loading" | "ready" | "unavailable" }) {
  const unavailable = layersForLens(ctx, "scene").filter((l) => l.unavailable && (l.def.id === "blh-surface" || l.def.id === "mixed-layer-slab" || l.def.id === "forecast-point"));
  const rows: { badge: Parameters<typeof ProvenanceBadge>[0]["kind"]; text: string }[] = [];
  if (data.terrain) {
    const t = data.terrain;
    rows.push({
      badge: "reference",
      text: `Ground: real terrain, ${Math.round(t.minM)}–${Math.round(t.maxM)} m above sea level (${t.provider}, about ${t.nominalResolutionM} m resolution), under a Sentinel-2 cloudless composite from 2020 registered to the same latitude/longitude frame. The imagery is not today's view: it does not show current cloud, smoke or haze. Relief is exaggerated ×${TERRAIN_EXAGGERATION}.`,
    });
  } else if (terrainState === "unavailable") {
    rows.push({ badge: "unavailable", text: "Terrain could not be built, so the ground is drawn flat. Data layers are placed correctly in latitude and longitude, but without elevation." });
  } else {
    rows.push({ badge: "reference", text: "Loading terrain and imagery (the first request builds and caches them and can take about half a minute)." });
  }
  if (data.columns.length) rows.push({ badge: ctx.variable === "aqi" ? "derived" : "observed", text: `Columns: one per station with a value; height encodes the value (scale up to ${data.columnScaleMax.toLocaleString()} ${data.columnUnit}), not altitude.` });
  if (data.ground) rows.push({ badge: data.ground.layerId.startsWith("sim-") ? (ctx.sim?.run.mode === "scenario" ? "hypothetical" : "simulated") : data.ground.layerId.startsWith("estimate") ? "estimate" : "weather_forecast", text: `Ground colour: the active field (${data.ground.layerId.replace(/-/g, " ")}), draped on the terrain; it carries no vertical information.` });
  if (data.blh) rows.push({ badge: "weather_forecast", text: "Surface: the model's boundary-layer height, the one vertical quantity in the data." });
  if (data.wind) rows.push({ badge: "weather_forecast", text: "Particles: the model's 10 m wind, drawn 10 m above ground. No wind data exist at other altitudes, so no vertical structure is implied; this is not pollutant transport." });
  if (data.pressureLines) rows.push({ badge: "weather_forecast", text: `Lines on the ground: model sea-level pressure every ${data.pressureInterval} hPa.` });
  if (data.slab) rows.push({ badge: "illustrative", text: "Slab: ILLUSTRATIVE. It draws the model's assumption that the simulated concentration is uniform up to the boundary-layer height; it is not a measured vertical field." });
  if (data.forecast) rows.push({ badge: "model_forecast", text: "Gold ring: a point prediction for the selected station, not a field." });
  rows.push({ badge: "illustrative", text: `Heights above ground (boundary layer, wind level) are exaggerated ×${VERTICAL_EXAGGERATION} so that a few kilometres of atmosphere can be seen over 100 km of ground; the axis shows true heights. Terrain relief is exaggerated more${data.terrain ? ` (×${TERRAIN_EXAGGERATION})` : ""} because the plain here varies by only a few hundred metres.` });
  return (
    <section aria-label="What the 3D scene shows" className="rounded-lg border border-line bg-surface p-3 text-xs text-muted">
      <h2 className="mb-1 text-sm font-semibold text-fg">What is data and what is illustration</h2>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.text} className="flex flex-wrap items-start gap-2">
            <ProvenanceBadge kind={r.badge} />
            <span className="min-w-0 flex-1">{r.text}</span>
          </li>
        ))}
        {unavailable.map(({ def, unavailable: why }) => (
          <li key={def.id} className="flex flex-wrap items-start gap-2">
            <ProvenanceBadge kind="unavailable" />
            <span className="min-w-0 flex-1">
              <strong className="text-fg">{def.label}:</strong> {why}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
