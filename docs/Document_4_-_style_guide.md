# Document 4: CSS Style Guide

One shared visual system for the whole site. No local styling for panes, nav items, buttons, dropdowns, cards, or common controls. No nav alerts/pulses/attention styling. No page-specific button variants. No pane-specific control styling. A pattern needed in >1 place belongs in shared global CSS.

## §0 Functional Appropriateness Exception

IF a page's layout is unreachable via shared classes/tokens (checked first, per §13) AND generalizing it would bloat the shared system with one-page exceptions, THEN a layout-only page-scoped class is permitted. All must hold:
1. Structural layout only (column/grid geometry, density, arrangement); never re-skins shared components (buttons, panes, dropdowns, inputs, modals, status indicators).
2. Consumes only shared tokens in §2 — no new color/radius/spacing/typography token locally.
3. Registered in the style guide's shared-pattern inventory, prefixed page-scoped, promoted into shared system when a second page needs it.

Permitted example pages: World Maintenance (dense per-rule editors), File Manager (multi-pane browser+viewer), Restore (staged workflow with live progress). Everything interactive reuses the shared component system; only page-level arrangement may differ.

## §1 Design direction

Stay: compact, operational, pane-based, lightweight, easy to scan, consistent light/dark.
Avoid: decorative, marketing-like, overly animated, page-specific control styles.

## §2 Global tokens

Base: canvas/bg `#eef2ff`; pane bg `#ffffff`; border `#d8dee6`; main text `#1f2a37`; muted `#5a6878`.
Dark: canvas/bg `#161b22`; pane bg `#0d1117`; border `#334155`; main text `#e6edf3`; muted `#9fb0c6`.

Control height 40px; min width 80px; common gap 12px; pane radius 12px; inner radius 10px; light shadow `0 2px 5px rgba(15,23,42,0.04)`.
Font stack for `html/body/button/input/textarea/select`: `Arial, Helvetica, Roboto, sans-serif`.
`h1`/`h2` identical styling; h1 = page title, h2 = default pane title.

## §3 Layout system

Terms: Body = top-level container. Landmarks: only `nav` + `main` as body children. `nav` reuses pane CSS; `main` has no styling. Panes = `article` children of `main`. Cards = children of panes; first card = Pane Title Area, rest = Pane Content Areas. Div groups = children of cards, only when needed.

- `nav` always child of body, sibling of `main`; sticky; no internal scroll; spans full screen height; primarily buttons + site logo.
- Every pane starts with exactly one Pane Title Area (`header` with title `h1`/`h2` + optional pane buttons/inputs); remaining sibling cards = Pane Content Areas (`div`).
- Grouped divs: sparingly (lists, form-item groups, custom log DOM); no deeper wrapper chains; no default bg/styling.
- Pane Title Area: no bg by default. Pane Content Area: body bg color.
- Shell: left sidebar (`nav`) + right content (`main`); outer padding 12px; internal gap 12px; pane-based grouping; `.pane-title-area`/`.pane-content-area` one shared pattern; pane titles use shared `h1`/`h2`.

## §4 Navigation

Nav items = one shared general-button style; active = highlighted general button. Sticky; no internal scroll; full viewport height respecting outer padding; spacing from shared rhythm/controls.
Forbidden: alert pulse, running-state green, warning-state yellow, red flashing, any page-specific nav treatment.

## §5 Component property table

| Component | Geometry | Roles / Kinds | States | Bans |
|---|---|---|---|---|
| Buttons | h 40px; min-w 80px; r 10px; fw 700; no page-specific sizing | Action — Blue (neutral default primary: save/backup/confirm), Teal (safe forward: start/create/continue/open), Red (dangerous: stop/restore/delete/force). General — Normal (body-bg, neutral: close/cancel/secondary nav), Highlighted (purple emphasis). Order: Teal > Red > Blue > BG | Normal, Hover (darker family color), Onclick (subtle pressed), Disabled Normal/Hover/Onclick (lower contrast, never looks active). Same set globally, not per page | No third family; no page variants |
| Dropdowns | Trigger = general button; list = body bg; 40px/min-w/radius family as buttons+inputs | — | — | No page/pane themes |
| Inputs | h 40px; shared border/radius/padding/text/disabled/focus | Two kinds only: `.ui-title-input` (Pane Title Area), `.ui-text-input` (Pane Content Area). Same system; placement differs | Shared disabled/focus | No third input look; no size/shape variation between kinds; no pane/page themes |
| Content surfaces | Rounded; low shadow; compact padding; shared border/bg tokens | Body = body bg; pane = pane bg; Pane Title Area = no bg; Pane Content Area = body bg; div groups = no default styling | — | No one-off gradients, decorative heroes, page-specific pane chrome/skins |
| Lists & selection rows | Item padding 12px; row-action gap 12px; shared item spacing/separators; bg from body/input system | One shared list surface | Selection affordances global, never per page | No page-specific list styling |

## §11 Modal system

Four kinds only: Confirmation, Password, Notification, Action Prompt. No other families.
- Semantic `dialog` element (no custom div overlays); styled as pane with shared pane structure (first card = Pane Title Area, rest = Pane Content Areas).
- Overlay: dark translucent. Stronger shadow than panes (modal layer). Modal actions use global button families/states — no modal-specific styling.
- Confirmation: summary of actions; proceed/cancel. Password: password input; proceed/cancel. Notification: informs; `Show more info` + `OK`. Action Prompt: prompts action (navigate, deny access, scheduled maintenance, proceed with missed actions, software updates); cancel/proceed/defer.

## §12 Responsive rules

Breakpoints `1100px`/`900px`/`700px` (when needed). Sidebar → overlay/off-canvas at smaller sizes. Multi-column layouts collapse cleanly. Buttons may wrap/stack; styling unchanged. Controls remain 40px tall.

## §13 Reuse rules (required workflow)

1. Check if style exists globally. 2. Reuse existing global class/token. 3. If missing, add to shared global system. 4. Then reuse everywhere. 5. IF page needs a layout the shared system can't express AND generalizing would bloat it, THEN apply §0 exception.

Do not: new button look for one page; different dropdowns per pane; different nav styling; custom pane appearance per page; local alert styling on nav/pane headers; CSS overrides of shared component geometry/spacing.

## §14 Explicit bans

- Nav alerts/pulses/severity colors.
- Page-only button colors, pane-only control styles, page-only dropdown themes.
- Page-specific Pane Content Area chrome / pane skins.
- Decorative hero styling breaking the operational look.
- Local styles for common elements when a shared style should exist.
- Page-scoped re-skinning of shared components (button, input, dropdown, pane, status-indicator theme changes) — only permitted page-scoped CSS is layout-only under §0.

## §15 Short reference

- Buttons: Action Red/Teal/Blue; General Normal/Highlighted; each supports Normal/Hover/Onclick/Disabled×3. Geometry: h 40px, min-w 80px.
- Dropdowns: trigger = general button; list = body bg.
- Navigation: shared general-button styling only; no nav alerts.
- Panes: shared styling only; no local overrides.
- Status Indicators: shared only (§17); four meanings (positive/negative/neutral/transitional); never interactive, never animated.

## §16 Final summary

One global CSS language: one nav, one pane, one button, one dropdown, one token set, one status indicator system; page-scoped layout classes only under §0. If a control looks different because it lives on a different page, the styling is wrong unless formally added to the global system first.

## §16.1 Live-stream interaction model

Live log panes and status cards consume events from the persistent shell's shared BroadcastChannel dispatcher. Components must not create direct `EventSource` instances; the leader-tab stream manager owns the backend SSE connection and dispatches its payloads through `mcmanager_stream_channel`.

## §17 Status Indicators

Purpose: badge/pill communicating state at a glance (world run state, backup status, sync outcome) — informational only, never buttons, never onclick, no hover/pressed states.

§17.1 Where used: stat boxes (Server Status, Backup Stats); backup list rows (sync status per backup); anywhere a discrete state needs a compact label.

§17.2 Geometry: h 24px (distinct from 40px controls — not a control); width auto; fully rounded pill (distinct from 10px control radius — never mistaken for clickable); padding 12px rhythm horizontally, tighter vertically; font weight 600 (lighter than button 700, reinforcing non-interactivity).

§17.3 Color mapping — reuses exact button color tokens (§5), no new colors. Closed, exhaustive:

| Meaning | Token | Example states |
|---|---|---|
| Positive/complete/healthy | Teal | running, synced, completed successfully |
| Dangerous/failed/attention | Red | crashed, error, sync failed |
| Neutral/inactive/n/a | Body bg + muted text | off, idle, not configured |
| Transitional/in progress | Blue | queued, starting, stopping, pending, backing_up, restoring |

No fifth color family. Same tokens as buttons → dark/light inherited; no separate dark tokens.

§17.4 Bans: no flashing/pulsing/animation anywhere — state change via static color/text update only. No page/pane-specific variants. No third visual treatment beyond the four meanings (no separate warning/yellow — re-evaluate against the four).

§17.5 Reference class: `.status-indicator` base; `data-tone` = `positive`/`negative`/`neutral`/`transitional` selects the §17.3 mapping.
