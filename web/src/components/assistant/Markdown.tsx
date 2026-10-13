"use client";

import Link from "next/link";
import { Fragment } from "react";
import { parseMarkdown, type Inline } from "@/lib/assistant/markdown";

function Inlines({ items, messageId, known }: { items: Inline[]; messageId: string; known: Set<string> }) {
  return (
    <>
      {items.map((it, i) => {
        switch (it.kind) {
          case "bold":
            return <strong key={i} className="font-semibold">{it.text}</strong>;
          case "code":
            return <code key={i} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.85em]">{it.text}</code>;
          case "report-link":
            return <Link key={i} href={`/reports?id=${it.id}`} className="text-accent underline hover:no-underline">{it.text}</Link>;
          case "cite":
            // A citation is only a link when the source really exists in this answer; otherwise it is shown as unverified.
            return known.has(it.id) ? (
              <a
                key={i}
                href={`#src-${messageId}-${it.id}`}
                className="mx-0.5 rounded bg-surface-2 px-1 py-0.5 align-baseline font-mono text-[0.75em] text-accent hover:underline"
                aria-label={`Source ${it.id}`}
              >
                {it.id}
              </a>
            ) : (
              <span key={i} className="mx-0.5 font-mono text-[0.75em] text-warn" title="No retrieved source has this id">[{it.id}?]</span>
            );
          default:
            return <Fragment key={i}>{it.text}</Fragment>;
        }
      })}
    </>
  );
}

export function Markdown({ text, messageId, sourceIds }: { text: string; messageId: string; sourceIds: string[] }) {
  const known = new Set(sourceIds);
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {parseMarkdown(text).map((b, i) => {
        if (b.kind === "heading")
          return (
            <p key={i} className={b.level === 2 ? "pt-1 text-base font-semibold" : "pt-1 font-semibold text-muted"}>
              <Inlines items={b.inline} messageId={messageId} known={known} />
            </p>
          );
        if (b.kind === "list") {
          const List = b.ordered ? "ol" : "ul";
          return (
            <List key={i} className={`space-y-1 pl-5 ${b.ordered ? "list-decimal" : "list-disc"}`}>
              {b.items.map((item, j) => (
                <li key={j}><Inlines items={item} messageId={messageId} known={known} /></li>
              ))}
            </List>
          );
        }
        return <p key={i}><Inlines items={b.inline} messageId={messageId} known={known} /></p>;
      })}
    </div>
  );
}
