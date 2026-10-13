"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { HUBS, hubFor } from "@/lib/nav";
import { Icon } from "@/components/ui/Icon";
import { ScrollFade } from "@/components/ui/ScrollFade";
import { cn } from "@/lib/utils";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const current = hubFor(pathname);
  return (
    <nav aria-label="Primary" className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-line px-5">
        <span className="h-2.5 w-2.5 rounded-full bg-accent shadow-[0_0_12px_var(--accent)]" aria-hidden="true" />
        <span className="text-sm font-semibold tracking-wide">AEROCAST NCR</span>
      </div>
      <ScrollFade className="min-h-0 flex-1">
        <ul className="space-y-1 p-3">
          {HUBS.map((hub) => {
            const active = current?.id === hub.id;
            return (
              <li key={hub.id} className="relative">
                {active && (
                  // The highlight slides between entries (Motion shared layout); with reduced motion it simply appears.
                  <motion.span layoutId="nav-active" className="absolute inset-0 rounded-md bg-surface-2 shadow-[inset_2px_0_0_var(--accent)]" transition={{ type: "spring", stiffness: 500, damping: 40 }} aria-hidden="true" />
                )}
                <Link
                  href={hub.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn("relative flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors", active ? "font-medium text-fg" : "text-muted hover:bg-surface-2/60 hover:text-fg")}
                >
                  <Icon name={hub.icon} className="h-4.5 w-4.5" />
                  {hub.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </ScrollFade>
    </nav>
  );
}
