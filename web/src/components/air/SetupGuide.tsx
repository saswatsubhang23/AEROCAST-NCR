import { EmptyState } from "@/components/ui/states";

/** Shown when the API has no air-quality key. This is an expected setup state, not an error. */
export function SetupGuide({ reasonCode }: { reasonCode: "not_configured" | "upstream_auth" }) {
  const rejected = reasonCode === "upstream_auth";
  return (
    <div className="space-y-4">
      <EmptyState
        title={rejected ? "The air-quality API key was rejected" : "Air-quality source not configured"}
        message={
          rejected
            ? "OpenAQ refused the key in AQ_API_KEY. Check that it is copied correctly and still active."
            : "No station observations can be shown until an OpenAQ API key is configured. Nothing is estimated or filled in."
        }
      />
      <ol className="mx-auto max-w-xl list-decimal space-y-1.5 rounded-lg border border-line bg-surface p-4 pl-8 text-sm text-muted">
        <li>
          Create a free account and API key at{" "}
          <a href="https://explore.openaq.org/register" target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">
            explore.openaq.org
          </a>
          .
        </li>
        <li>
          Put it in <span className="font-mono text-fg">api/.env</span> as <span className="font-mono text-fg">AQ_API_KEY=…</span>. The key stays on
          the server and is never sent to the browser.
        </li>
        <li>Restart the API, then use Reload on this page.</li>
      </ol>
    </div>
  );
}
