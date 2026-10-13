export type LegendItem = { label: string; color: string };

export function MapLegend({ title, unit, items }: { title: string; unit?: string; items: LegendItem[] }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3" role="group" aria-label={`${title} legend`}>
      <p className="mb-2 text-xs font-medium text-muted">
        {title}
        {unit && <span className="ml-1">({unit})</span>}
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {items.map((i) => (
          <li key={i.label} className="flex items-center gap-1.5 text-xs">
            <span className="h-2.5 w-4 rounded-sm" style={{ background: i.color }} aria-hidden="true" />
            {i.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
