"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { FullReportExport } from "@/components/reports/FullReportExport";
import { ReportView } from "@/components/reports/ReportView";
import { FilterBar, SelectField } from "@/components/ui/FilterBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState, ErrorState, LoadingState, btnPrimary } from "@/components/ui/states";
import { labelOf, POLLUTANTS } from "@/lib/air/pollutants";
import { useLocation } from "@/lib/location";
import { LOCATIONS } from "@/lib/locations";
import { createReport, fetchReport, isReportId } from "@/lib/reports/api";
import type { Report } from "@/lib/reports/types";
import { ApiError } from "@/lib/weather/api";

const PERIODS = [6, 12, 24, 48, 72, 168];

type State = { status: "idle" } | { status: "loading"; label: string } | { status: "error"; error: ApiError } | { status: "ready"; report: Report };

export default function ReportsPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading" />}>
      <Reports />
    </Suspense>
  );
}

function Reports() {
  const { location } = useLocation();
  const params = useSearchParams();
  const linked = params.get("id");
  const [locationId, setLocationId] = useState(location.id);
  const [hours, setHours] = useState(24);
  const [pollutant, setPollutant] = useState("pm25");
  const [state, setState] = useState<State>(isReportId(linked) ? { status: "loading", label: "Opening the report" } : { status: "idle" });

  // A report linked from the assistant (/reports?id=…) is opened as it was generated.
  useEffect(() => {
    if (!isReportId(linked)) return;
    const ac = new AbortController();
    fetchReport(linked, ac.signal)
      .then((report) => setState({ status: "ready", report }))
      .catch((e) => {
        if (!ac.signal.aborted) setState({ status: "error", error: e instanceof ApiError ? e : new ApiError("Could not open the report.", 0) });
      });
    return () => ac.abort();
  }, [linked]);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setState({ status: "loading", label: "Collecting weather, air-quality and reference data (the first report after a restart can take a few minutes)" });
    try {
      const report = await createReport(locationId, hours, pollutant);
      window.history.replaceState(null, "", `/reports?id=${report.id}`); // so reload and sharing the link reopen this report
      setState({ status: "ready", report });
    } catch (err) {
      setState({ status: "error", error: err instanceof ApiError ? err : new ApiError("Could not generate the report.", 0) });
    }
  }

  return (
    <>
      <PageHeader title="Reports" description="Built from the live weather, air-quality and knowledge-base services. Every number comes from a cited source; nothing is estimated or filled in." />
      <form onSubmit={generate} aria-label="Report options">
        <FilterBar>
          <SelectField label="Location" value={locationId} onChange={setLocationId} options={LOCATIONS.map((l) => ({ value: l.id, label: l.name }))} />
          <SelectField label="Period" value={String(hours)} onChange={(v) => setHours(Number(v))} options={PERIODS.map((h) => ({ value: String(h), label: h === 168 ? "7 days" : `${h} hours` }))} />
          <SelectField label="Pollutant" value={pollutant} onChange={setPollutant} options={POLLUTANTS.map((p) => ({ value: p.key, label: p.label }))} />
          <button type="submit" className={btnPrimary} disabled={state.status === "loading"}>Generate report</button>
        </FilterBar>
      </form>
      <FullReportExport options={{ location_id: locationId, hours, pollutant }} />
      {state.status === "idle" && (
        <EmptyState title="No report yet" message={`Choose a location, period and pollutant (now ${labelOf(pollutant)}), then generate a report. It is built on request and kept for two hours.`} />
      )}
      {state.status === "loading" && <LoadingState label={state.label} />}
      {state.status === "error" && (
        <ErrorState
          title={state.error.code === "report_expired" ? "This report has expired" : "The report could not be generated"}
          message={state.error.message}
        />
      )}
      {state.status === "ready" && <ReportView key={state.report.id} report={state.report} />}
    </>
  );
}
