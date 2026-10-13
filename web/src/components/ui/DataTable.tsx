import { EmptyState } from "./states";

export type Column<T> = { key: string; header: string; render: (row: T) => React.ReactNode };

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  empty,
}: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty: { title: string; message: string };
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full min-w-120 text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className="px-4 py-2.5 font-medium">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={rowKey(r)}>
              {columns.map((c) => (
                <td key={c.key} className="px-4 py-2.5 align-top">
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="p-4">
          <EmptyState title={empty.title} message={empty.message} />
        </div>
      )}
    </div>
  );
}
