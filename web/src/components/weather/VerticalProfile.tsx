"use client";

import { useMemo, useState } from "react";
import { ChartContainer } from "@/components/ui/ChartContainer";
import { EChart } from "@/components/charts/EChart";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useLocation } from "@/lib/location";
import { fetchProfile } from "@/lib/weather/api";
import { buildProfileOption } from "@/lib/weather/chartOptions";
import { useResource, useWeather } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";
import { ConceptualInversion } from "./ConceptualInversion";

/** Model-forecast vertical temperature profile at the selected hour, with inversion layers shaded. */
export function VerticalProfile() {
  const { location } = useLocation();
  const { point, selected } = useWeather();
  const [version, setVersion] = useState(0);
  const profile = useResource(`profile:${location.id}`, version, (s) => fetchProfile(location.lat, location.lon, s));

  const hour = useMemo(() => {
    if (profile.status !== "ready" || point.status !== "ready") return null;
    const t = point.data.times[selected];
    return profile.data.hours.find((h) => h.time === t) ?? null;
  }, [profile, point, selected]);
  const option = useMemo(() => (hour && hour.points.length >= 2 ? buildProfileOption(hour) : null), [hour]);

  if (profile.status === "loading") return <LoadingState label="Loading vertical profile" />;
  if (profile.status === "error")
    return (
      <div className="space-y-3">
        <ErrorState title="Vertical profile is unavailable" message={profile.error.message} onRetry={() => setVersion((v) => v + 1)} />
        <ConceptualInversion />
      </div>
    );
  if (!hour || !option) return <ConceptualInversion />;

  const inv = hour.inversions;
  return (
    <ChartContainer
      title={`Vertical temperature profile, ${formatIST(hour.time)}`}
      caption={profile.data.note}
    >
      <p className={`mb-2 text-sm ${inv.length ? "text-warn" : "text-muted"}`} role="status">
        {inv.length
          ? `Inversion in the model profile: temperature rises ${inv.map((i) => `${i.strength_c} °C between ${Math.round(i.base_agl_m)} m and ${Math.round(i.top_agl_m)} m`).join("; ")}.`
          : "No temperature inversion between the model levels at this hour."}
      </p>
      <EChart option={option} ariaLabel="Temperature against height above ground at the selected hour" height={300} />
    </ChartContainer>
  );
}
