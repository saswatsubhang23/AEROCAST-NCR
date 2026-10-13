/** Frame for any chart: title, optional caption, fixed minimum-height body supplied by the caller. */
export function ChartContainer({
  title,
  caption,
  children,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="rounded-lg border border-line bg-surface p-4">
      <figcaption className="mb-3">
        <p className="text-sm font-medium">{title}</p>
        {caption && <p className="text-xs text-muted">{caption}</p>}
      </figcaption>
      <div className="min-h-64">{children}</div>
    </figure>
  );
}
