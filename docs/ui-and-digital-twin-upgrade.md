# UI upgrade: library evaluation and migration matrix

## Skiper UI: what was verified (2026-10-10)

* Skiper UI (`https://skiper-ui.com`) is a **shadcn registry**: components install as single files with `npx shadcn add @skiper-ui/skiperNN` and are served as JSON at `https://skiper-ui.com/r/skiperNN.json`. Most use `framer-motion`.
* 37 registry items were fetchable without an account. The rest are Pro (paid, one-time USD 129 / 549 per the site) and were **not** used. Buying a licence is a decision for you.
* The fetchable items are almost all marketing and "creative" interactions (parallax, carousels, scroll reveals, hover effects, a canvas crowd, theme toggles). For an analytical dashboard only two fit: **skiper101 "Custom tooltip"** (Radix tooltip with a bordered content box and arrow) and **skiper87 "Scroll with fade effect"** (top/bottom fade on a scroll area). Both are adopted, rewritten onto this project's tokens and API (`components/ui/Tooltip.tsx`, `components/ui/ScrollFade.tsx`). The others were evaluated and rejected: they decorate rather than inform, add weight, and several animate numbers or layouts in ways that could imply change in measured values.

## Libraries adopted (and why)

| Library | Use | Why |
|---|---|---|
| Radix UI (`react-tooltip`, `react-dialog`, `react-tabs`, `react-scroll-area`, `react-slot`) | tooltip, dialog/sheet, tabs, scroll area | accessible primitives (focus trap, Escape, ARIA) that the shadcn/Skiper components are built on; React 19 compatible |
| class-variance-authority + clsx + tailwind-merge | `Button` variants, `cn()` | the standard shadcn pattern; tiny |
| lucide-react | one icon set for the whole app | replaced the hand-drawn SVG path table in `Icon.tsx` |
| framer-motion | sliding active-nav highlight, `MotionConfig reducedMotion="user"` | purposeful motion only; honours reduced-motion |

Not installed: Aceternity, Magic UI, Origin UI (decorative, overlapping), a second design system. ECharts, MapLibre and deck.gl are kept.

## Migration matrix

| Component | Before | After | Status |
|---|---|---|---|
| Icons | custom SVG path table | Lucide via the same `Icon` API | done |
| Sidebar | CSS-highlighted list | Motion `layoutId` highlight, `ScrollFade` list, new Digital Twin entry | done, seen in browser |
| Mobile navigation | hand-rolled overlay + key handler | Radix `Sheet` (focus trap, Escape, restored focus) | done |
| Dialog | native `<dialog>` | Radix `Dialog`, same props | done (4 call sites unchanged) |
| Tooltip | CSS-only (caused horizontal overflow on phones) | Radix tooltip from Skiper `skiper101`, portalled | done |
| Buttons | class-name constants | `Button` + `buttonVariants`; `btnPrimary/btnSecondary` now come from the variants | done (call sites still use the constants for `<a>` and `<button>`) |
| Tabs | none | Radix `Tabs` (twin layer selector) | done |
| Provenance labels | none | `ProvenanceBadge` (eight kinds) on Overview, Weather, Air Quality, Atmosphere, Twin | done |
| Model / Jev status | none | `ModelStatusPanel` on Settings, `ForecastAvailability` on Overview | done, seen in browser |
| Page headers, filters, tables, metric cards | existing | unchanged (already consistent tokens) | retained deliberately |
| Toasts | custom | unchanged | retained |
| Assistant messages, citation panel, knowledge-base pages, reports page | existing | unchanged in this pass | **not migrated** |

## Design tokens

The existing navy/charcoal tokens in `app/globals.css` (`--bg`, `--surface`, `--surface-2`, `--line`, `--fg`, `--fg-muted`,
`--accent` cyan, `--accent-2` blue, `--warn`, `--danger`) are retained and every new component uses them; overlay animations
(`tw-fade`, `tw-pop`, `tw-slide`) and a `skeleton` shimmer class were added and are disabled by the existing reduced-motion rule.

## Digital twin

See `docs/digital-twin-architecture.md`. New route `/twin` with map layers (observations, weather wind, spatial estimate, model
forecast; transport disabled with its reason), timeline controls, station charts, risk-window and regime panels.

## Verification so far

`tsc`, `eslint` and `vitest` (56 tests) pass; the shell, `/twin` (unavailable state), Overview and Settings were opened in the
browser pane. **Still to verify:** `/twin` with real data (needs the cleaned store), axe-core and mobile-overflow re-run on every
route, and a production build.
