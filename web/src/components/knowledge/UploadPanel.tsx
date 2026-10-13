"use client";

import { useRef, useState } from "react";
import { useNotify } from "@/components/ui/Notifications";
import { btnPrimary } from "@/components/ui/states";
import { uploadDocument } from "@/lib/kb/api";
import type { CategoryKey, KbLimits } from "@/lib/kb/types";
import { validateUpload } from "@/lib/kb/validate";
import { ApiError } from "@/lib/weather/api";

const field = "h-9 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg placeholder:text-muted";

export function UploadPanel({
  limits, onUploaded, onShowExisting,
}: { limits: KbLimits; onUploaded: () => void; onShowExisting: (id: string) => void }) {
  const notify = useNotify();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState<CategoryKey | "">("");
  const [title, setTitle] = useState("");
  const [publisher, setPublisher] = useState("");
  const [licence, setLicence] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ message: string; existingId?: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const invalid = validateUpload(file, category, url, limits);
    if (invalid) return setProblem({ message: invalid });
    setProblem(null);
    setBusy(true);
    try {
      const doc = await uploadDocument({ file: file!, category: category as CategoryKey, title, publisher, licence, source_url: url });
      notify(`"${doc.title}" uploaded. Indexing has started.`);
      setFile(null); setTitle(""); setPublisher(""); setLicence(""); setUrl("");
      if (fileInput.current) fileInput.current.value = "";
      onUploaded();
    } catch (err) {
      const existing = err instanceof ApiError && err.code === "duplicate"
        ? (err.details as { existing_document_id?: string } | undefined)?.existing_document_id
        : undefined;
      setProblem({ message: err instanceof ApiError ? err.message : "The upload failed.", existingId: existing });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-line bg-surface p-4" aria-label="Upload a document">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs font-medium text-muted md:col-span-2">
          File (PDF, TXT, Markdown or CSV, up to {limits.max_upload_mb} MB)
          <input
            ref={fileInput}
            type="file"
            accept={limits.extensions.join(",")}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-fg file:mr-3 file:h-9 file:cursor-pointer file:rounded-md file:border file:border-line file:bg-surface-2 file:px-3 file:text-sm file:text-fg"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Type of document (required)
          <select value={category} onChange={(e) => setCategory(e.target.value as CategoryKey | "")} className={field}>
            <option value="">Choose…</option>
            {Object.entries(limits.categories).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Title (optional, defaults to the file name)
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={field} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Publisher (optional)
          <input value={publisher} onChange={(e) => setPublisher(e.target.value)} maxLength={120} placeholder="e.g. WHO, CPCB" className={field} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted">
          Licence (optional)
          <input value={licence} onChange={(e) => setLicence(e.target.value)} maxLength={120} placeholder="e.g. CC BY 4.0" className={field} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted md:col-span-2">
          Source link (optional)
          <input value={url} onChange={(e) => setUrl(e.target.value)} maxLength={500} placeholder="https://…" inputMode="url" className={field} />
        </label>
      </div>

      {problem && (
        <div role="alert" className="mt-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
          <p className="text-danger">{problem.message}</p>
          {problem.existingId && (
            <button type="button" className="mt-1 text-accent hover:underline" onClick={() => onShowExisting(problem.existingId!)}>
              Show the existing document
            </button>
          )}
        </div>
      )}

      <div className="mt-3 flex items-center gap-3">
        <button type="submit" disabled={busy} className={btnPrimary}>{busy ? "Uploading…" : "Upload and index"}</button>
        <p className="text-xs text-muted">Files are read as text only. Nothing in a document is ever run.</p>
      </div>
    </form>
  );
}
