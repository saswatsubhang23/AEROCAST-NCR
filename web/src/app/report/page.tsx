"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Kicker } from "@/components/ui/Glass";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { outline, parseArticle, type Block, type Inline } from "@/lib/article/markdown";
import { request } from "@/lib/http";
import { useResource } from "@/lib/weather/context";

type Meta = { slug: string; title: string; summary: string; minutes: number; updated: number };
type Article = Meta & { markdown: string };

// The selected article lives in the URL (?a=slug) so it can be linked and shared; this reads it without an effect.
function subscribe(cb: () => void) {
  window.addEventListener("popstate", cb);
  window.addEventListener("report-nav", cb);
  return () => {
    window.removeEventListener("popstate", cb);
    window.removeEventListener("report-nav", cb);
  };
}
const snapshot = () => new URLSearchParams(window.location.search).get("a") ?? "";
const serverSnapshot = () => "";

function go(slug: string | null) {
  const url = slug ? `/report?a=${encodeURIComponent(slug)}` : "/report";
  window.history.pushState({}, "", url);
  window.dispatchEvent(new Event("report-nav"));
  window.scrollTo({ top: 0 });
}

function Inlines({ items }: { items: Inline[] }) {
  return (
    <>
      {items.map((it, i) => {
        switch (it.kind) {
          case "bold":
            return <strong key={i} className="font-semibold text-fg">{it.text}</strong>;
          case "italic":
            return <em key={i}>{it.text}</em>;
          case "code":
            return <code key={i} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.86em]">{it.text}</code>;
          case "link":
            return it.external ? (
              <a key={i} href={it.href} target="_blank" rel="noopener noreferrer" className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">{it.text}</a>
            ) : (
              <Link key={i} href={it.href} className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">{it.text}</Link>
            );
          default:
            return <span key={i}>{it.text}</span>;
        }
      })}
    </>
  );
}

function BlockView({ b }: { b: Block }) {
  switch (b.kind) {
    case "heading":
      if (b.level === 1) return null; // the title is shown by the article header
      return b.level === 2 ? (
        <h2 id={b.id} className="mt-12 scroll-mt-24 border-t border-line pt-8 text-2xl font-semibold tracking-tight"><Inlines items={b.inline} /></h2>
      ) : (
        <h3 id={b.id} className="mt-8 scroll-mt-24 text-lg font-semibold"><Inlines items={b.inline} /></h3>
      );
    case "paragraph":
      return <p className="mt-4 text-[1.0625rem] leading-8 text-fg/90"><Inlines items={b.inline} /></p>;
    case "quote":
      return <blockquote className="mt-5 rounded-r-lg border-l-2 border-accent bg-surface-2/50 px-4 py-3 text-[1.0625rem] leading-7 text-muted"><Inlines items={b.inline} /></blockquote>;
    case "list": {
      const List = b.ordered ? "ol" : "ul";
      return (
        <List className={`mt-4 space-y-2 pl-6 text-[1.0625rem] leading-8 text-fg/90 ${b.ordered ? "list-decimal" : "list-disc"} marker:text-muted`}>
          {b.items.map((it, i) => <li key={i}><Inlines items={it} /></li>)}
        </List>
      );
    }
    case "table":
      return (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <thead className="border-b border-line bg-surface-2/60 text-xs uppercase tracking-wider text-muted">
              <tr>{b.header.map((h, i) => <th key={i} scope="col" className={`px-3 py-2 font-medium ${b.align[i] === "right" ? "text-right" : b.align[i] === "center" ? "text-center" : ""}`}><Inlines items={h} /></th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {b.rows.map((r, i) => (
                <tr key={i}>{r.map((c, j) => <td key={j} className={`px-3 py-2 align-top ${b.align[j] === "right" ? "text-right font-mono tabular" : b.align[j] === "center" ? "text-center" : ""}`}><Inlines items={c} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "code":
      return <pre className="mt-5 overflow-x-auto rounded-lg border border-line bg-[#0b1322] p-4 font-mono text-[13px] leading-6 text-fg/90"><code>{b.text}</code></pre>;
    case "rule":
      return <hr className="my-10 border-line" />;
  }
}

function ReadingProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const on = () => {
      const h = document.documentElement.scrollHeight - window.innerHeight;
      setP(h > 0 ? Math.min(1, Math.max(0, window.scrollY / h)) : 0);
    };
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return <div aria-hidden="true" className="fixed inset-x-0 top-0 z-40 h-0.5 bg-transparent"><div className="h-full bg-accent transition-[width]" style={{ width: `${p * 100}%` }} /></div>;
}

function ArticleReader({ slug, meta }: { slug: string; meta: Meta[] }) {
  const res = useResource(`article:${slug}`, 0, (s) => request<Article>(`/api/docs/articles/${slug}`, { signal: s }));
  const blocks = useMemo(() => (res.status === "ready" ? parseArticle(res.data.markdown) : []), [res]);
  const toc = useMemo(() => outline(blocks), [blocks]);
  const idx = meta.findIndex((m) => m.slug === slug);
  if (res.status === "loading") return <LoadingState label="Opening the article" />;
  if (res.status === "error") return <ErrorState title="This article could not be opened" message={res.error.message} onRetry={() => go(null)} />;
  const a = res.data;
  return (
    <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[minmax(0,1fr)_15rem]">
      <ReadingProgress />
      <article className="min-w-0">
        <button type="button" onClick={() => go(null)} className="mb-6 text-sm text-muted hover:text-fg">← All reports</button>
        <Kicker>{a.minutes} minute read</Kicker>
        <h1 className="mt-2 text-4xl font-semibold leading-tight tracking-tight">{a.title}</h1>
        {a.summary && <p className="mt-4 text-xl leading-8 text-muted">{a.summary}</p>}
        {/* the first block quote is the summary shown above, so it is not repeated in the body */}
        <div className="mt-8">{blocks.map((b, i) => (b.kind === "quote" && i === blocks.findIndex((x) => x.kind === "quote") && a.summary ? null : <BlockView key={i} b={b} />))}</div>
        <nav aria-label="Other reports" className="mt-16 grid gap-3 border-t border-line pt-8 sm:grid-cols-2">
          {idx > 0 && (
            <button type="button" onClick={() => go(meta[idx - 1].slug)} className="card p-4 text-left hover:border-accent/60">
              <span className="text-xs text-muted">Previous</span>
              <span className="mt-1 block font-medium">{meta[idx - 1].title}</span>
            </button>
          )}
          {idx >= 0 && idx < meta.length - 1 && (
            <button type="button" onClick={() => go(meta[idx + 1].slug)} className="card p-4 text-left hover:border-accent/60 sm:col-start-2">
              <span className="text-xs text-muted">Next</span>
              <span className="mt-1 block font-medium">{meta[idx + 1].title}</span>
            </button>
          )}
        </nav>
      </article>
      <aside className="hidden lg:block" aria-label="Contents">
        <div className="sticky top-20">
          <Kicker>In this report</Kicker>
          <ul className="mt-3 space-y-1.5 border-l border-line text-sm">
            {toc.map((t) => (
              <li key={t.id} className={t.level === 3 ? "pl-6" : "pl-3"}>
                <a href={`#${t.id}`} className="block text-muted hover:text-fg">{t.text}</a>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}

export default function ReportPage() {
  const slug = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const list = useResource("articles", 0, (s) => request<{ articles: Meta[] }>("/api/docs/articles", { signal: s }));
  const open = useCallback((s: string) => go(s), []);
  if (list.status === "loading") return <LoadingState label="Loading the reports" />;
  if (list.status === "error") return <ErrorState title="The reports could not be loaded" message={list.error.message} />;
  const meta = list.data.articles;
  if (slug && meta.some((m) => m.slug === slug)) return <ArticleReader slug={slug} meta={meta} />;
  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header>
        <Kicker>Report</Kicker>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight">What this application knows, how it knows it, and how far to trust it</h1>
        <p className="mt-3 max-w-2xl text-lg leading-8 text-muted">The pages of the application show numbers and pictures. These reports hold the reasoning, the evidence and the limits behind them, so the pages can stay short.</p>
        <p className="mt-3 text-sm text-muted">Want every figure, table and report in one file? <Link href="/reports" className="text-accent underline underline-offset-2">Download the full report as PDF or HTML</Link>.</p>
      </header>
      <ul className="grid gap-4">
        {meta.map((m, i) => (
          <li key={m.slug}>
            <button type="button" onClick={() => open(m.slug)} className="card group block w-full p-6 text-left transition-colors hover:border-accent/60">
              <span className="text-xs text-muted">{String(i + 1).padStart(2, "0")} · {m.minutes} minute read</span>
              <span className="mt-1 block text-xl font-semibold tracking-tight group-hover:text-accent">{m.title}</span>
              <span className="mt-2 block text-[0.9375rem] leading-7 text-muted">{m.summary}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
