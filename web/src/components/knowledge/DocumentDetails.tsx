"use client";

import { DatasetPanel } from "@/components/knowledge/DatasetPanel";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fetchChunks } from "@/lib/kb/api";
import type { KbDocument } from "@/lib/kb/types";
import { formatSize, safeHref } from "@/lib/kb/validate";
import { useResource } from "@/lib/weather/context";
import { formatIST } from "@/lib/weather/time";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 break-words">{children}</dd>
    </div>
  );
}

function Chunks({ id }: { id: string }) {
  const res = useResource(`chunks:${id}`, 0, (s) => fetchChunks(id, s));
  if (res.status === "loading") return <LoadingState label="Loading passages" />;
  if (res.status === "error") return <ErrorState title="Passages could not be loaded" message={res.error.message} />;
  if (res.data.length === 0) return <p className="text-xs text-muted">No indexed passages.</p>;
  return (
    <ol className="space-y-2">
      {res.data.map((c) => (
        <li key={c.index} className="rounded-md border border-line bg-bg/40 p-2 text-xs">
          <p className="mb-1 text-muted">
            Passage {c.index + 1}
            {c.page_start !== null && ` · ${c.page_end && c.page_end !== c.page_start ? `pp. ${c.page_start}-${c.page_end}` : `p. ${c.page_start}`}`}
            {c.section && ` · section "${c.section}"`}
          </p>
          <p className="line-clamp-4 whitespace-pre-wrap">{c.text}</p>
        </li>
      ))}
    </ol>
  );
}

export function DocumentDetails({ doc, onClose }: { doc: KbDocument | null; onClose: () => void }) {
  const href = safeHref(doc?.source_url ?? null);
  return (
    <Dialog open={doc !== null} onClose={onClose} title={doc?.title ?? "Document"}>
      {doc && (
        <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
          <dl className="grid grid-cols-2 gap-3">
            <Row label="Type">{doc.category_label}</Row>
            <Row label="Status">{doc.status === "ready" ? "Ready" : doc.status === "indexing" ? "Indexing" : "Failed"}</Row>
            <Row label="Publisher">{doc.publisher ?? "Not given"}</Row>
            <Row label="Licence">{doc.licence ?? "Not given"}</Row>
            <Row label="File">{doc.filename} ({doc.kind.toUpperCase()}, {formatSize(doc.size_bytes)}{doc.pages !== null && `, ${doc.pages} pages`})</Row>
            <Row label="Passages">{doc.chunk_count}</Row>
            <Row label="Embedding model">{doc.embedding_model ?? "Not indexed"}</Row>
            <Row label="Indexed">{doc.indexed_at ? formatIST(doc.indexed_at) : "Not yet"}</Row>
            <Row label="Added">{formatIST(doc.created_at)}</Row>
            <Row label="Fingerprint (SHA-256)"><span className="font-mono text-xs">{doc.content_hash.slice(0, 16)}…</span></Row>
            <div className="col-span-2">
              <dt className="text-xs text-muted">Source link</dt>
              <dd className="mt-0.5 break-all">
                {href ? <a href={href} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">{href}</a> : (doc.source_url ?? "Not given")}
              </dd>
            </div>
          </dl>
          {doc.error && <p role="alert" className="rounded-md border border-danger/40 bg-danger/5 p-2 text-xs text-danger">{doc.error}</p>}
          {doc.notes.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-warn">
              {doc.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
          {doc.status === "ready" && <DatasetPanel doc={doc} />}
          {doc.status === "ready" && (
            <section aria-label="Indexed passages">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">First indexed passages</h3>
              <Chunks id={doc.id} />
            </section>
          )}
        </div>
      )}
    </Dialog>
  );
}
