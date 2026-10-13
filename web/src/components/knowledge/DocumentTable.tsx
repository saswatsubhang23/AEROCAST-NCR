"use client";

import { DataTable, type Column } from "@/components/ui/DataTable";
import { btnSecondary } from "@/components/ui/states";
import { formatSize } from "@/lib/kb/validate";
import type { KbDocument } from "@/lib/kb/types";
import { formatIST } from "@/lib/weather/time";

function Status({ d }: { d: KbDocument }) {
  if (d.status === "indexing")
    return (
      <span role="status" className="inline-flex items-center gap-2 text-sm">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden="true" />
        Indexing…
      </span>
    );
  if (d.status === "failed")
    return (
      <div role="alert">
        <span className="inline-flex items-center gap-2 text-sm text-danger">
          <span className="h-2 w-2 rounded-full bg-danger" aria-hidden="true" />
          Indexing failed
        </span>
        {d.error && <p className="mt-1 max-w-xs text-xs text-muted">{d.error}</p>}
      </div>
    );
  return (
    <div>
      <span className="inline-flex items-center gap-2 text-sm">
        <span className="h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
        Ready
      </span>
      {d.needs_reindex && <p className="mt-1 text-xs text-warn">Re-index needed: the embedding model changed.</p>}
    </div>
  );
}

export function DocumentTable({
  documents, onOpen, onReindex, onDelete, busyId,
}: {
  documents: KbDocument[];
  onOpen: (d: KbDocument) => void;
  onReindex: (d: KbDocument) => void;
  onDelete: (d: KbDocument) => void;
  busyId: string | null;
}) {
  const columns: Column<KbDocument>[] = [
    {
      key: "title",
      header: "Document",
      render: (d) => (
        <div className="max-w-xs">
          <button onClick={() => onOpen(d)} className="text-left font-medium hover:text-accent" aria-label={`Details of ${d.title}`}>
            {d.title}
          </button>
          <p className="truncate text-xs text-muted">
            {d.filename} · {d.kind.toUpperCase()} · {formatSize(d.size_bytes)}
            {d.pages !== null && ` · ${d.pages} pages`}
          </p>
        </div>
      ),
    },
    { key: "category", header: "Type", render: (d) => <span className="text-sm">{d.category_label}</span> },
    { key: "status", header: "Status", render: (d) => <Status d={d} /> },
    { key: "chunks", header: "Passages", render: (d) => (d.status === "ready" ? d.chunk_count : <span className="text-muted">—</span>) },
    {
      key: "added",
      header: "Added (IST)",
      render: (d) => <span className="text-xs text-muted">{formatIST(d.created_at)}</span>,
    },
    {
      key: "actions",
      header: "Actions",
      render: (d) => (
        <div className="flex gap-2">
          <button className={btnSecondary} onClick={() => onReindex(d)} disabled={d.status === "indexing" || busyId === d.id}>
            Re-index
          </button>
          <button className={btnSecondary} onClick={() => onDelete(d)} disabled={busyId === d.id} aria-label={`Delete ${d.title}`}>
            Delete
          </button>
        </div>
      ),
    },
  ];

  return (
    <DataTable
      caption="Documents in the knowledge base"
      columns={columns}
      rows={documents}
      rowKey={(d) => d.id}
      empty={{ title: "No documents yet", message: "Upload a PDF, text, Markdown or CSV file above. The assistant can only cite documents listed here." }}
    />
  );
}
