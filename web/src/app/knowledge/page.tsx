"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { DocumentDetails } from "@/components/knowledge/DocumentDetails";
import { DocumentTable } from "@/components/knowledge/DocumentTable";
import { SearchPanel } from "@/components/knowledge/SearchPanel";
import { UploadPanel } from "@/components/knowledge/UploadPanel";
import { Dialog } from "@/components/ui/Dialog";
import { useNotify } from "@/components/ui/Notifications";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { ErrorState, LoadingState, btnPrimary, btnSecondary } from "@/components/ui/states";
import { deleteDocument, fetchKbStatus, reindexDocument } from "@/lib/kb/api";
import type { KbDocument } from "@/lib/kb/types";
import { useDocuments } from "@/lib/kb/useDocuments";
import { useResource } from "@/lib/weather/context";

function KnowledgeContent() {
  const notify = useNotify();
  const { state, reload } = useDocuments();
  const [statusVersion, setStatusVersion] = useState(0);
  const status = useResource("kb-status", statusVersion, (s) => fetchKbStatus(s));
  // A link from an assistant citation arrives as /knowledge?doc=<id> and opens that document's details.
  const linked = useSearchParams().get("doc");
  const [openId, setOpenId] = useState<string | null>(null);
  const [dismissedLink, setDismissedLink] = useState(false);
  const shownId = openId ?? (linked && !dismissedLink ? linked : null);
  const [toDelete, setToDelete] = useState<KbDocument | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const docs = state.status === "ready" ? state.data.documents : [];
  const opened = docs.find((d) => d.id === shownId) ?? null;

  function closeDetails() {
    setOpenId(null);
    setDismissedLink(true);
  }

  async function reindex(d: KbDocument) {
    setBusyId(d.id);
    try {
      await reindexDocument(d.id);
      notify(`Re-indexing "${d.title}".`);
    } catch (e) {
      notify(e instanceof Error ? e.message : "Could not start re-indexing.", "error");
    } finally {
      setBusyId(null);
      void reload();
    }
  }

  async function remove(d: KbDocument) {
    setBusyId(d.id);
    try {
      await deleteDocument(d.id);
      notify(`Deleted "${d.title}" and its indexed passages.`);
      if (shownId === d.id) closeDetails();
    } catch (e) {
      notify(e instanceof Error ? e.message : "Could not delete the document.", "error");
    } finally {
      setBusyId(null);
      setToDelete(null);
      void reload();
    }
  }

  return (
    <>
      <PageHeader
        title="Knowledge Base"
        description="Documents the assistant can search and cite: official guidance, scientific publications and project documentation. Every answer that uses one names it, its type and the passage."
      />

      {status.status === "ready" && !status.data.embedding.available && (
        <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warn/50 bg-warn/5 p-3 text-sm">
          <div>
            <p className="font-medium text-warn">Indexing and search are unavailable</p>
            <p className="text-muted">{status.data.embedding.message}</p>
            <p className="mt-1 text-xs text-muted">You can still upload; documents are indexed once embeddings work (use Re-index).</p>
          </div>
          <button className={btnSecondary} onClick={() => setStatusVersion((v) => v + 1)}>Check again</button>
        </div>
      )}
      {status.status === "ready" && status.data.embedding.available && (
        <p className="mb-5 text-xs text-muted">
          Embedding model {status.data.embedding.model} · {status.data.documents_ready} searchable, {status.data.documents_indexing} indexing,{" "}
          {status.data.documents_failed} failed.
        </p>
      )}
      {status.status === "error" && (
        <div className="mb-5">
          <ErrorState title="Cannot reach the AEROCAST API" message={status.error.message} onRetry={() => setStatusVersion((v) => v + 1)} />
        </div>
      )}

      {state.status === "loading" && <LoadingState label="Loading documents" />}
      {state.status === "error" && <ErrorState title="Documents could not be loaded" message={state.error.message} onRetry={() => void reload()} />}
      {state.status === "ready" && (
        <>
          <Section title="Add a document">
            <UploadPanel limits={state.data.limits} onUploaded={() => void reload()} onShowExisting={setOpenId} />
          </Section>

          <Section title="Search">
            <SearchPanel limits={state.data.limits} onOpen={setOpenId} />
          </Section>

          <Section title={`Documents (${docs.length})`}>
            <DocumentTable documents={docs} onOpen={(d) => setOpenId(d.id)} onReindex={reindex} onDelete={setToDelete} busyId={busyId} />
          </Section>
        </>
      )}

      <DocumentDetails doc={opened} onClose={closeDetails} />

      <Dialog open={toDelete !== null} onClose={() => setToDelete(null)} title="Delete this document?">
        <p className="text-muted">
          “{toDelete?.title}” will be removed together with its file and every indexed passage. The assistant will no longer be able to cite it.
        </p>
        <div className="mt-4">
          <button className={btnPrimary} disabled={busyId !== null} onClick={() => toDelete && void remove(toDelete)}>
            Delete document
          </button>
        </div>
      </Dialog>
    </>
  );
}

export default function KnowledgePage() {
  // useSearchParams needs a Suspense boundary so the page can still be pre-rendered.
  return (
    <Suspense fallback={<LoadingState label="Loading" />}>
      <KnowledgeContent />
    </Suspense>
  );
}
