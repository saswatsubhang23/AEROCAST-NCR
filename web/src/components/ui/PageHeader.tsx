export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Section({
  title,
  children,
  aside,
}: {
  title: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
