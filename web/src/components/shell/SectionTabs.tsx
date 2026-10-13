"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { hubFor } from "@/lib/nav";
import { cn } from "@/lib/utils";

/** The tabs of the section the current page belongs to (see lib/nav.ts). Nothing is rendered for single-page sections. */
export function SectionTabs() {
  const pathname = usePathname();
  const hub = hubFor(pathname);
  if (!hub || hub.tabs.length < 2) return null;
  return (
    <nav aria-label={`${hub.label} sections`} className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
      {hub.tabs.map((t) => {
        const on = pathname === t.href || (t.href !== hub.href && pathname.startsWith(t.href));
        return (
          <Link
            key={t.href} href={t.href} aria-current={on ? "page" : undefined}
            className={cn("-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition-colors", on ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg")}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
