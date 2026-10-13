"use client";

import { useId } from "react";

export type Option = { value: string; label: string };

export function FilterBar({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="group"
      aria-label="Filters"
      className="mb-5 flex flex-wrap items-end gap-4 rounded-lg border border-line bg-surface p-3"
    >
      {children}
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Option[];
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 min-w-40 rounded-md border border-line bg-surface-2 px-2.5 text-sm text-fg"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SegmentedField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Option[];
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1 text-xs font-medium text-muted">
      <span id={id}>{label}</span>
      <div role="radiogroup" aria-labelledby={id} className="flex rounded-md border border-line bg-surface-2 p-0.5">
        {options.map((o) => (
          <button
            key={o.value}
            role="radio"
            aria-checked={value === o.value}
            onClick={() => onChange(o.value)}
            className={`h-8 rounded px-3 text-sm transition-colors ${
              value === o.value ? "bg-accent font-medium text-bg" : "text-muted hover:text-fg"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
