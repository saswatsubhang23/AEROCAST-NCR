import { Activity, Atom, Calculator, CircleSlash, Clock, CloudSun, Cpu, FlaskConical, Layers, Mountain, Presentation, Wind } from "lucide-react";
import { Tooltip } from "./Tooltip";
import { cn } from "@/lib/utils";

export type Provenance = "observed" | "weather_forecast" | "model_forecast" | "atmospheric_model" | "simulated" | "hypothetical" | "derived" | "estimate" | "illustrative" | "reference" | "stale" | "unavailable";

const KINDS: Record<Provenance, { label: string; hint: string; icon: typeof Activity; tone: string }> = {
  observed: { label: "Observed", hint: "A measurement reported by a monitoring station or sensor.", icon: Activity, tone: "border-accent/50 text-accent" },
  weather_forecast: { label: "Weather forecast", hint: "Output of a numerical weather model for a grid cell, not a measurement.", icon: CloudSun, tone: "border-accent-2/60 text-fg" },
  model_forecast: { label: "Model forecast", hint: "A pollutant forecast from a model trained on historical observations. Its held-out accuracy is in the model report.", icon: Cpu, tone: "border-accent-2/60 text-fg" },
  atmospheric_model: { label: "Atmospheric model", hint: "Output of a coarse-grid atmospheric-chemistry model (Open-Meteo/CAMS). Not a measurement and not AEROCAST's trained model; it can differ from station readings.", icon: Atom, tone: "border-accent-2/60 text-fg" },
  simulated: { label: "Simulated", hint: "Produced by the transport model from observed air and weather-model wind. A computed field, not a measurement and not a forecast of emissions.", icon: Wind, tone: "border-accent-2/60 text-fg" },
  hypothetical: { label: "Hypothetical", hint: "A what-if run with explicitly changed model parameters. Not a prediction of what will happen.", icon: FlaskConical, tone: "border-warn/50 text-warn" },
  derived: { label: "Derived", hint: "Calculated from real observations with a documented formula.", icon: Calculator, tone: "border-line text-muted" },
  estimate: { label: "Spatial estimate", hint: "Interpolated between stations; it is not measured at that point.", icon: Layers, tone: "border-warn/50 text-warn" },
  illustrative: { label: "Illustrative", hint: "A schematic or animation that does not show measured or modelled values.", icon: Presentation, tone: "border-warn/50 text-warn" },
  reference: { label: "Reference layer", hint: "Static background geography (terrain height or a satellite composite). It is not a live observation and not a forecast.", icon: Mountain, tone: "border-line text-muted" },
  stale: { label: "Stale", hint: "The newest data is older than the freshness limit.", icon: Clock, tone: "border-warn/50 text-warn" },
  unavailable: { label: "Unavailable", hint: "The source did not provide data. Nothing is shown in its place.", icon: CircleSlash, tone: "border-danger/50 text-danger" },
};

/** Says what kind of information a panel shows. Always text plus an icon, never colour alone. */
export function ProvenanceBadge({ kind, detail, className }: { kind: Provenance; detail?: string; className?: string }) {
  const k = KINDS[kind];
  const Icon = k.icon;
  return (
    <Tooltip text={detail ? `${k.hint} ${detail}` : k.hint}>
      <span tabIndex={0} className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium", k.tone, className)}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        {k.label}
      </span>
    </Tooltip>
  );
}
