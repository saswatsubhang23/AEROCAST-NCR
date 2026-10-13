"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { StateChip } from "@/components/air/AlertsPanel";
import { Button } from "@/components/ui/Button";
import { Chip, Dot, Kicker } from "@/components/ui/Glass";
import { Icon } from "@/components/ui/Icon";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingState } from "@/components/ui/states";
import { useAlerts } from "@/lib/alerts/useAlerts";
import { fetchCamsFields } from "@/lib/flow/cams";
import { colourAtValue, scaleFor } from "@/lib/flow/field";
import { fetchAvailability } from "@/lib/data/availability";
import { deriveSources, useHealth } from "@/lib/health";
import { useLocation } from "@/lib/location";
import { fetchModelStatus, fetchTwinStatus } from "@/lib/twin/api";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

const FEATURES = [
  { href: "/flow", icon: "flow", title: "Air flow", text: "Watch air move over the region in 2D and 3D, coloured by concentration. Replay stored observations, follow the live model, or run the coupled model." },
  { href: "/twin", icon: "twin", title: "Digital twin", text: "Station observations, spatial estimates, weather-model fields, simulations and scenarios on one shared timeline." },
  { href: "/early-warning", icon: "alert", title: "Early warning", text: "Every station ranked by the trained model's forecast against a threshold, with the uncertainty stated." },
  { href: "/data", icon: "database", title: "Data coverage", text: "What the application has, what it only partly has, and what it does not have, with the consequence of each gap." },
  { href: "/report", icon: "article", title: "Report", text: "The reasoning, the evidence and the limits behind the pages, written as articles." },
] as const;

function Stat({ label, children, note, badge }: { label: string; children: React.ReactNode; note?: React.ReactNode; badge?: React.ReactNode }) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between gap-2">
        <Kicker>{label}</Kicker>
        {badge}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular">{children}</div>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}

export default function OverviewPage() {
  const { location } = useLocation();
  const { state } = useHealth();
  const sources = deriveSources(state);
  const alerts = useAlerts();
  const cams = useResource("overview-cams", 0, (s) => fetchCamsFields(0, 6, s));
  const twin = useResource("twin-status", 0, (s) => fetchTwinStatus(s));
  const model = useResource("overview-model", 0, (s) => fetchModelStatus(s));
  const avail = useResource("overview-availability", 0, (s) => fetchAvailability(s));

  const air = useMemo(() => {
    if (cams.status !== "ready" || cams.data.now_index === null) return null;
    const v = cams.data.variables.pm25;
    const frame = v?.values[cams.data.now_index];
    if (!frame) return null;
    const all = frame.flat().filter((x): x is number => x !== null);
    if (!all.length) return null;
    const mean = all.reduce((a, b) => a + b, 0) / all.length;
    const scale = scaleFor("pm25");
    const cls = scale.bins.find((b) => mean >= b.lo && mean < b.hi) ?? scale.bins[scale.bins.length - 1];
    return { mean, min: Math.min(...all), max: Math.max(...all), cls, time: cams.data.times[cams.data.now_index], rgb: colourAtValue(scale, mean) };
  }, [cams]);

  const newest = twin.status === "ready" ? twin.data.periods.pm25?.dense_to ?? twin.data.periods.pm25?.to ?? null : null;
  const [now] = useState(() => Date.now()); // fixed at mount: render stays pure
  const stationAgeH = newest ? (now - new Date(newest).getTime()) / 3_600_000 : null;

  return (
    <div className="space-y-6">
      <section className="card relative overflow-hidden p-6 sm:p-8" aria-labelledby="hero-title">
        <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-accent/10 blur-3xl" aria-hidden="true" />
        <Kicker>{location.name} · Delhi-NCR</Kicker>
        <h1 id="hero-title" className="mt-2 max-w-2xl text-3xl font-semibold leading-tight tracking-tight">
          {air ? (
            <>
              The model has PM2.5 around <span style={{ color: air.rgb ? `rgb(${air.rgb.map(Math.round).join(",")})` : undefined }}>{Math.round(air.mean)} µg/m³</span> over the region right now
            </>
          ) : cams.status === "loading" ? (
            "Reading the current air…"
          ) : (
            "Delhi-NCR weather and air-quality intelligence"
          )}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          {air
            ? `That is the area mean of the CAMS atmospheric model (range ${Math.round(air.min)} to ${Math.round(air.max)}, class ${air.cls.label}), ${formatIST(air.time)}. It is a model, not a measurement, and its cells are about 44 km across.`
            : "Weather-model fields, station observations and a trained forecasting model, with every number labelled by where it came from."}
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <Button variant="primary" asChild><Link href="/flow">Open the air flow</Link></Button>
          <Button asChild><Link href="/twin">Digital twin</Link></Button>
          <Button variant="ghost" asChild><Link href="/data">What data is missing</Link></Button>
        </div>
      </section>

      <section aria-label="Status" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Air now (model)" badge={<ProvenanceBadge kind="atmospheric_model" />} note={air ? `Updated hourly · ${formatIST(air.time)}` : undefined}>
          {air ? <>{Math.round(air.mean)} <span className="text-sm font-normal text-muted">µg/m³ PM2.5</span></> : <span className="text-base font-normal text-muted">{cams.status === "loading" ? "Loading" : "Unavailable"}</span>}
        </Stat>
        <Stat label="Station feed" badge={stationAgeH !== null ? <Chip tone={stationAgeH > 6 ? "warn" : "ok"} icon={<Dot tone={stationAgeH > 6 ? "warn" : "ok"} />}>{stationAgeH > 6 ? "Stale" : "Fresh"}</Chip> : undefined}
          note={newest ? `Newest well-covered hour ${formatIST(newest)}` : twin.status === "error" ? twin.error.message : undefined}>
          {stationAgeH === null ? <span className="text-base font-normal text-muted">{twin.status === "loading" ? "Loading" : "No store"}</span> : stationAgeH < 48 ? <>{Math.round(stationAgeH)} <span className="text-sm font-normal text-muted">h old</span></> : <>{(stationAgeH / 24).toFixed(1)} <span className="text-sm font-normal text-muted">days old</span></>}
        </Stat>
        <Stat label="Trained model" badge={<ProvenanceBadge kind="model_forecast" />}
          note={model.status === "ready" && model.data.available ? `Run ${model.data.run_id} · ${model.data.targets.filter((t) => t.test && t.persistence_test && t.test.mae < t.persistence_test.mae).length} of ${model.data.targets.length} targets beat persistence on held-out data` : model.status === "ready" ? model.data.reason : undefined}>
          {model.status === "ready" && model.data.available ? <>{model.data.targets.length} <span className="text-sm font-normal text-muted">targets</span></> : <span className="text-base font-normal text-muted">{model.status === "loading" ? "Loading" : "Not available"}</span>}
        </Stat>
        <Stat label="Data gaps" note="Data the application does not have, or only partly has" badge={avail.status === "ready" && avail.data.counts.missing > 0 ? <Link href="/data" className="text-xs text-accent hover:underline">See all</Link> : undefined}>
          {avail.status === "ready" ? <>{avail.data.counts.missing + avail.data.counts.partial + avail.data.counts.stale + avail.data.counts.obtainable} <span className="text-sm font-normal text-muted">of {Object.values(avail.data.counts).reduce((a, b) => a + b, 0)} sources</span></> : <span className="text-base font-normal text-muted">{avail.status === "loading" ? "Loading" : "Unknown"}</span>}
        </Stat>
      </section>

      <section aria-label="Where to go" className="grid gap-3 sm:grid-cols-2">
        {FEATURES.map((f) => (
          <Link key={f.href} href={f.href} className="card group flex gap-4 p-4 transition-colors hover:border-accent/60">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-2 text-accent"><Icon name={f.icon} className="h-5 w-5" /></span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold group-hover:text-accent">{f.title}</span>
              <span className="mt-0.5 block text-sm text-muted">{f.text}</span>
            </span>
          </Link>
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="alerts-h">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="alerts-h" className="text-xs font-semibold uppercase tracking-wider text-muted">Alerts</h2>
            <Link href="/air-quality" className="text-sm text-accent hover:underline">Manage</Link>
          </div>
          {alerts.state.status === "loading" && <LoadingState label="Checking alert rules" />}
          {alerts.state.status === "error" && <p className="card p-4 text-sm text-muted">Alerts could not be checked: {alerts.state.error.message}</p>}
          {alerts.state.status === "ready" &&
            (alerts.state.data.statuses.length === 0 ? (
              <p className="card p-4 text-sm text-muted">No alert rules are set. Thresholds are yours to define on the Air Quality page.</p>
            ) : (
              <ul className="card divide-y divide-line">
                {alerts.state.data.statuses.map((s) => (
                  <li key={s.rule.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                    <span>{s.rule.name}</span>
                    <StateChip state={s.status} />
                  </li>
                ))}
              </ul>
            ))}
        </section>
        <section aria-labelledby="sources-h">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="sources-h" className="text-xs font-semibold uppercase tracking-wider text-muted">Services</h2>
            <Link href="/settings" className="text-sm text-accent hover:underline">Manage</Link>
          </div>
          {state.status === "loading" ? (
            <LoadingState label="Checking services" />
          ) : (
            <ul className="card divide-y divide-line">
              {sources.map((s) => (
                <li key={s.name} className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm">
                  <span>{s.name}</span>
                  <StatusBadge state={s.state} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
