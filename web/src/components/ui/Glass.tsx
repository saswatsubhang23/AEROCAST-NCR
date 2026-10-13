"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

/** A translucent panel for controls that float over a map or a 3D scene. Readable on both light and dark imagery. */
export function GlassPanel({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("glass rounded-xl", className)} {...rest}>
      {children}
    </div>
  );
}

/** A small status pill: a coloured dot or icon plus text. Never colour alone. */
export function Chip({
  tone = "neutral", icon, children, className, title,
}: { tone?: "neutral" | "ok" | "warn" | "danger" | "accent"; icon?: React.ReactNode; children: React.ReactNode; className?: string; title?: string }) {
  const tones = {
    neutral: "border-line text-muted",
    ok: "border-emerald-400/40 text-emerald-300",
    warn: "border-warn/50 text-warn",
    danger: "border-danger/50 text-danger",
    accent: "border-accent/50 text-accent",
  } as const;
  return (
    <span title={title} className={cn("inline-flex items-center gap-1.5 rounded-full border bg-surface/70 px-2.5 py-0.5 text-xs font-medium", tones[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function Dot({ tone }: { tone: "ok" | "warn" | "danger" | "idle" | "accent" }) {
  const c = { ok: "bg-emerald-400", warn: "bg-warn", danger: "bg-danger", idle: "bg-muted", accent: "bg-accent" }[tone];
  return <span className={cn("inline-block h-2 w-2 rounded-full", c)} aria-hidden="true" />;
}

/** A radio-group styled as a segmented control. Keyboard: arrow keys move between options (native radio behaviour). */
export function Segmented<T extends string>({
  label, value, onChange, options, className, size = "md",
}: {
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; hint?: string; disabled?: boolean }[];
  className?: string;
  size?: "sm" | "md";
}) {
  const name = useId();
  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className="sr-only">{label}</legend>
      <div className="inline-flex max-w-full flex-wrap gap-0.5 rounded-lg border border-line bg-surface-2/80 p-0.5">
        {options.map((o) => {
          const on = o.value === value;
          return (
            <label
              key={o.value}
              title={o.hint}
              className={cn(
                "relative cursor-pointer select-none rounded-md px-3 text-center text-sm font-medium transition-colors focus-within:outline-2 focus-within:outline-accent",
                size === "sm" ? "py-1 text-xs" : "py-1.5",
                on ? "bg-accent text-bg shadow-sm" : "text-muted hover:text-fg",
                o.disabled && "cursor-not-allowed opacity-40",
              )}
            >
              <input type="radio" name={name} value={o.value} checked={on} disabled={o.disabled} onChange={() => onChange(o.value)} className="sr-only" />
              {o.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function Kicker({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn("text-[11px] font-semibold uppercase tracking-[0.14em] text-muted", className)}>{children}</p>;
}

export function Toggle({ label, checked, onChange, hint, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string; disabled?: boolean }) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-2.5 text-sm", disabled && "cursor-not-allowed opacity-50")} title={hint}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
      <span
        aria-hidden="true"
        className="mt-0.5 h-5 w-9 shrink-0 rounded-full border border-line bg-surface-2 transition-colors peer-checked:border-accent peer-checked:bg-accent/30 peer-focus-visible:outline-2 peer-focus-visible:outline-accent after:m-0.5 after:block after:h-3.5 after:w-3.5 after:rounded-full after:bg-muted after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-accent"
      />
      <span className="min-w-0 leading-snug">{label}</span>
    </label>
  );
}
