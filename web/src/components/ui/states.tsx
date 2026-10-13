import { buttonVariants } from "./Button";
import { Icon } from "./Icon";

const base = "flex flex-col gap-2 rounded-lg border p-5 text-sm";
const box = `${base} items-start`;

// Kept as class-name constants because many call sites build their own <a>/<button>; they come from the shared Button variants.
export const btnPrimary = buttonVariants({ variant: "primary" });
export const btnSecondary = buttonVariants({ variant: "secondary" });

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className={`${box} border-line bg-surface`}>
      <div className="flex items-center gap-3 text-muted">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" />
        {label}…
      </div>
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className={`${box} border-danger/40 bg-danger/5`}>
      <div className="flex items-center gap-2 font-medium text-danger">
        <Icon name="alert" className="h-4 w-4" />
        {title}
      </div>
      {message && <p className="text-muted">{message}</p>}
      {onRetry && (
        <button onClick={onRetry} className={btnSecondary}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message: string;
  action?: React.ReactNode;
}) {
  return (
    <div className={`${base} items-center border-dashed border-line bg-surface py-10 text-center`}>
      <Icon name="inbox" className="h-6 w-6 text-muted" />
      <p className="font-medium">{title}</p>
      <p className="max-w-md text-muted">{message}</p>
      {action}
    </div>
  );
}

/** For capabilities whose backing service is not connected. States the reason; never shows placeholder values. */
export function UnavailableState({ title, reason }: { title: string; reason: string }) {
  return (
    <div className={`${box} border-line bg-surface`}>
      <p className="font-medium">{title}</p>
      <p className="text-muted">{reason}</p>
    </div>
  );
}
