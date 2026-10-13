/** Static teaching diagram. Shown only when no vertical profile data is available; it carries no measured values. */
export function ConceptualInversion() {
  return (
    <figure className="rounded-lg border border-dashed border-line bg-surface p-4">
      <figcaption className="mb-2 text-sm font-medium">
        Conceptual diagram: temperature inversion{" "}
        <span className="ml-1 rounded bg-surface-2 px-1.5 py-0.5 text-xs font-normal text-muted">Not measured data</span>
      </figcaption>
      <svg viewBox="0 0 360 170" className="w-full max-w-md" role="img" aria-label="Conceptual diagram of a temperature inversion trapping pollutants under a warm layer">
        <rect x="0" y="0" width="360" height="170" fill="#0f1829" />
        <rect x="0" y="30" width="360" height="40" fill="#7f5a1a" opacity="0.35" />
        <text x="12" y="54" fill="#e8eef8" fontSize="12">Warmer air layer (the inversion “lid”)</text>
        <rect x="0" y="70" width="360" height="70" fill="#1d3a5c" opacity="0.6" />
        <text x="12" y="98" fill="#e8eef8" fontSize="12">Cooler air near the ground</text>
        <text x="12" y="116" fill="#9db0cc" fontSize="11">Pollutants stay trapped here</text>
        <rect x="0" y="140" width="360" height="30" fill="#22314d" />
        <text x="12" y="160" fill="#9db0cc" fontSize="11">Ground</text>
        <path d="M300 130 V76" stroke="#22d3ee" strokeWidth="2" markerEnd="url(#a)" />
        <defs><marker id="a" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#22d3ee" /></marker></defs>
        <line x1="286" y1="70" x2="314" y2="70" stroke="#f59e0b" strokeWidth="2" />
        <text x="270" y="20" fill="#9db0cc" fontSize="11">Rising air is blocked</text>
      </svg>
    </figure>
  );
}
