import { Icon } from "./Icon";
import { Tooltip } from "./Tooltip";

/** A single measurement. A null value renders as "No data", never a placeholder number. */
export function Metric({
  label,
  value,
  unit,
  definition,
  source,
  note,
}: {
  label: string;
  value: number | string | null;
  unit?: string;
  definition?: string;
  source?: string;
  /** Free-text line under the value, e.g. when and how it was observed. */
  note?: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted">
        {label}
        {definition && (
          <Tooltip text={definition}>
            <button aria-label={`About ${label}`} className="rounded text-muted hover:text-fg">
              <Icon name="info" className="h-3.5 w-3.5" />
            </button>
          </Tooltip>
        )}
      </div>
      {value === null ? (
        <p className="mt-2 text-sm text-muted">No data</p>
      ) : (
        <p className="mt-1.5 font-mono text-2xl font-semibold tabular-nums">
          {value}
          {unit && <span className="ml-1 text-sm font-normal text-muted">{unit}</span>}
        </p>
      )}
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
      {source && value !== null && <p className="mt-1 text-xs text-muted">Source: {source}</p>}
    </div>
  );
}
