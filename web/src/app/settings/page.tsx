"use client";

import { useState } from "react";
import { ModelStatusPanel } from "@/components/settings/ModelStatusPanel";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Icon } from "@/components/ui/Icon";
import { useNotify } from "@/components/ui/Notifications";
import { btnSecondary } from "@/components/ui/states";
import { API_BASE, deriveSources, useHealth, type SourceRow } from "@/lib/health";

const COLUMNS: Column<SourceRow>[] = [
  { key: "name", header: "Source", render: (r) => <span className="font-medium">{r.name}</span> },
  { key: "state", header: "Status", render: (r) => <StatusBadge state={r.state} /> },
  { key: "detail", header: "Detail", render: (r) => <span className="text-muted">{r.detail}</span> },
];

export default function SettingsPage() {
  const { state, refresh } = useHealth();
  const notify = useNotify();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Settings & Data Sources"
        description="Connection status for the services AEROCAST NCR depends on."
        actions={
          <>
            <button onClick={() => setOpen(true)} className={btnSecondary}>
              Connection details
            </button>
            <button
              onClick={refresh}
              disabled={state.status === "loading"}
              className={btnSecondary}
            >
              <Icon name="refresh" className="h-4 w-4" />
              Recheck
            </button>
          </>
        }
      />

      <Section title="Services">
        <DataTable
          caption="Service connection status"
          columns={COLUMNS}
          rows={deriveSources(state)}
          rowKey={(r) => r.name}
          empty={{ title: "No services", message: "No services are configured." }}
        />
        <p className="mt-2 text-xs text-muted">
          {state.checkedAt ? `Last checked ${state.checkedAt.toLocaleTimeString()}` : "Checking…"}
        </p>
      </Section>

      <Section title="Forecasting model and decision support">
        <ModelStatusPanel />
      </Section>

      <Section title="Interface">
        <button
          onClick={() => notify("Notifications appear here and dismiss automatically.")}
          className={btnSecondary}
        >
          Send test notification
        </button>
      </Section>

      <Dialog open={open} onClose={() => setOpen(false)} title="Connection details">
        <dl className="space-y-3">
          <div>
            <dt className="text-xs text-muted">API base URL (NEXT_PUBLIC_API_BASE_URL)</dt>
            <dd className="mt-0.5 break-all font-mono">{API_BASE}</dd>
          </div>
          <p className="text-muted">
            PostgreSQL, Ollama and provider settings are configured on the API server in <span className="font-mono">api/.env</span>.
            Secrets are never shown in the interface.
          </p>
        </dl>
      </Dialog>
    </>
  );
}
