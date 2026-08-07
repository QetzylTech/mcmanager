Document 4: MC Manager CSS Style Guide

Scope
- Single CSS reference for the entire site. All pages follow this guide; no local styling systems for pages, panes, nav sections, or one-off elements.

Primary source
- `Prototypes/Legacy/static/global.css` — used only to identify reusable patterns for the shared system.

Core rules
- One shared visual system for the whole site.
- No local styling for panes, nav items, buttons, dropdowns, cards, or common controls.
- No nav alerts, nav pulses, or nav-specific attention styling.
- No page-specific button variants.
- No pane-specific control styling.
- If a pattern is needed in more than one place, it belongs in shared global CSS.

0. Functional Appropriateness Exception (amends the no-local-styling rule)

- IF a page's layout is unreachable via shared classes/tokens (checked first, per §13 workflow) AND generalizing it into the shared system would bloat it with one-page exceptions, THEN a layout-only page-scoped class is permitted.
- Conditions (all must hold):
  1. Structural layout only (column/grid geometry, density, arrangement); never re-skins shared components (buttons, panes, dropdowns, inputs, modals, status indicators).
  2. Consumes only shared tokens in §2 — no new color/radius/spacing/typography token locally.
  3. Registered in the style guide's shared-pattern inventory, prefixed as page-scoped, promoted into the shared system when a second page needs it.
- Permitted example pages: World Maintenance (dense per-rule editors), File Manager (multi-pane browser + viewer), Restore (staged workflow with live progress). Everything interactive reuses the shared component system; only page-level arrangement may differ.

1. Design direction

The site should remain:
- compact, operational, pane-based, lightweight, easy to scan, consistent in light and dark mode

The site should not become:
- decorative, marketing-like, overly animated, full of page-specific control styles

2. Global tokens

These values stay the baseline unless the entire site design changes.

Base colors
- Canvas background: `#eef2ff`
- Body background: `#eef2ff`
- Pane background: `#ffffff`
- Border: `#d8dee6`
- Main text: `#1f2a37`
- Muted text: `#5a6878`

Dark mode baseline
- Canvas background: `#161b22`
- Body background: `#161b22`
- Pane background: `#0d1117`
- Border: `#334155`
- Main text: `#e6edf3`
- Muted text: `#9fb0c6`

Spacing and shape
- Control height: `40px`
- Control min width: `80px`
- Common gap: `12px`
- Pane radius: `12px`
- Inner radius: `10px`
- Light shadow: `0 2px 5px rgba(15, 23, 42, 0.04)`

Typography
- Font stack for `html`, `body`, `button`, `input`, `textarea`, `select`: `Arial, Helvetica, Roboto, sans-serif`

Headings
- `h1` and `h2` share identical styling. `h1` = page title, `h2` = default pane title.

3. Layout system

3.1 Standard page structure terms

- Body: the actual page / top-level container.
- Landmarks: children of body; the only top-level elements are `nav` and `main`.
  - `nav` reuses pane CSS.
  - `main` is a container with no styling of its own.
- Panes: children of `main`, implemented as `article` elements.
- Cards: children of panes. First card = Pane Title Area; remaining cards = Pane Content Areas.
- Div groups: children of cards, used only when needed.

Nav
- Contains primarily buttons and site logo; may contain sections/divs for grouping.
- Sticky; no internal scroll area; spans full available screen height.

3.2 Structural rules

- `nav` is always a child of `body`, always a sibling of `main`.
- Every pane starts with exactly one Pane Title Area; remaining sibling cards are Pane Content Areas.
- Pane Title Area: a `header` containing the pane title (`h1`/`h2`) and optionally pane buttons/inputs.
- Pane Content Area: a `div`; any card after the first Pane Title Area card.
- Card usage: first card = Pane Title Area; remaining = Pane Content Areas; grouped child divs only when necessary and sparingly (lists of items, form-item groups, custom log output DOM). No deeper wrapper chains unless genuinely required. No default background/styling on grouped divs.
- Pane Title Area has no background color by default; Pane Content Area uses the body background color.

App shell
- Persistent shell: left sidebar (`nav`) + right content area (`main`).
- Default rhythm: outer padding `12px`; internal gap between major blocks `12px`; pane-based grouping throughout.
- All standard panes share pane background, radius, shadow, and padding approach.
- `.pane-title-area` / `.pane-content-area` follow one shared pattern; pane titles use shared `h1`/`h2` styling.

4. Navigation

- Nav items follow one shared global style, visually like general buttons.
- Active nav item = highlighted general button style.
- Sticky positioning; no internal scrolling; spans full viewport height respecting outer padding; spacing from shared rhythm/controls.

Forbidden nav styling
- Alert pulse, running-state green, warning-state yellow, red flashing, or any page-specific nav treatment.

5. Component Property Table (compresses former §5–§10: button system, button states, dropdowns, inputs, content surfaces, lists)

| Component | Geometry | Roles / Kinds | States | Bans |
|---|---|---|---|---|
| Buttons | height `40px`; min-width `80px`; radius `10px`; font weight `700`; no page-specific sizing | Action — Blue (neutral default primary: save/backup/confirm), Teal (safe forward: start/create/continue/open), Red (dangerous: stop/restore/delete/force). General — Normal (body-bg, neutral: close/cancel/secondary nav), Highlighted (purple emphasis). Side-by-side order: Teal > Red > Blue > BG | Normal, On Hover (darker family color), Onclick (subtle pressed), Disabled Normal/Hover/Onclick (lower contrast, never looks active). Same set for every family, globally, not per page | No third family; no page variants |
| Dropdowns | Trigger = general button style; list = body background; same `40px` height / min-width / radius family as buttons & inputs | — | — | No page/pane-specific dropdown themes |
| Inputs | height `40px`; shared border/radius/padding/text/disabled/focus | Exactly two kinds: `.ui-title-input` (Pane Title Area), `.ui-text-input` (Pane Content Area). Same system; only placement differs | Shared disabled/focus behavior | No third input look; no size/shape variation between kinds; no pane/page themes |
| Content surfaces | Rounded; low shadow; compact padding; shared border/background tokens | Inheritance: body = body bg; pane = pane bg; Pane Title Area = no bg; Pane Content Area = body bg; div groups = no default styling | — | No one-off gradients, decorative heroes, or page-specific pane chrome/skins |
| Lists & selection rows | Item padding `12px`; row-action gap = shared `12px`; shared item spacing/separators; background from body/input system | One shared list surface | Selection affordances defined globally, never per page | No page-specific list styling |

11. Modal system

Four modal kinds only: Confirmation, Password, Notification, Action Prompt. No other modal families.
- Modals use the semantic `dialog` element (no custom `div` overlays), styled as a pane with the shared pane structure: first card = Pane Title Area, remaining = Pane Content Areas.
- Overlay: dark translucent.
- Stronger shadow than standard panes (modal layer).
- Modal actions use the global button families/states — no modal-specific styling.

11.2 Allowed modal kinds
- Confirmation: summary of actions to take; proceed or cancel.
- Password: password input; proceed or cancel.
- Notification: informs the user; `Show more info` + `OK` buttons.
- Action Prompt: prompts an action (navigate, deny access, scheduled maintenance, proceed with missed actions, software updates); cancel / proceed / defer.

12. Responsive rules

Breakpoints: `1100px`, `900px`, `700px` (when needed).
- Sidebar becomes overlay/off-canvas at smaller sizes.
- Multi-column layouts collapse cleanly.
- Buttons may wrap/stack; styling does not change.
- Controls remain `40px` tall.

13. Reuse rules

Required CSS workflow:
1. Check if the style exists globally.
2. Reuse the existing global class/token.
3. If missing, add it to the shared global system.
4. Then reuse it everywhere.
5. IF a page needs a layout the shared system cannot express AND generalizing would bloat it with one-page exceptions, THEN apply the §0 Functional Appropriateness Exception.

Do not: create a new button look for one page; style dropdowns differently in one pane; style nav differently from the rest of the control system; create a custom pane appearance for one page; add local alert styling to nav or pane headers; force CSS overrides for shared component geometry/spacing.

14. Explicit bans

- Nav alerts, nav pulses, nav severity colors.
- Page-only button colors, pane-only control styles, page-only dropdown themes.
- Page-specific Pane Content Area chrome, page-specific pane skins.
- Decorative hero styling that breaks the operational look.
- Local styles for common elements when a shared style should exist.
- Page-scoped re-skinning of shared components (button, input, dropdown, pane, or status-indicator theme changes) — the only permitted page-scoped CSS is layout-only, under §0.

15. Short reference matrix

- Buttons: Action Red / Action Teal / Action Blue / General Normal / General Highlighted; each supports Normal, On Hover, Onclick, Disabled Normal, Disabled On Hover, Disabled Onclick. Geometry: height `40px`, min width `80px`.
- Dropdowns: trigger = general button style; list = body background color.
- Navigation: shared general-button-like styling only; no nav alerts.
- Panes: shared styling only; no local visual overrides.
- Status Indicators: shared styling only, per §17; four meanings only (positive/negative/neutral/transitional); never interactive, never animated.

16. Final summary

One global CSS language: one nav system, one pane system, one button system, one dropdown system, one token set, one status indicator system; page-scoped layout classes only under §0. If a control looks different because it lives on a different page, the styling is wrong unless formally added to the global system first.

17. Status Indicators

Purpose
- A Status Indicator (badge/pill) communicates state at a glance — a world's run state, a backup's status, a sync job's outcome — without being clickable or introducing a new visual language. Informational only: never buttons, never onclick, never hover/pressed states.

17.1 Where used
- Stat boxes (Server Status, Backup Stats — Doc 5 homepage).
- Backup list rows (sync status per backup — Doc 5).
- Any place a discrete state needs a compact label rather than prose.

17.2 Shared geometry
- Height `24px` (distinct from the `40px` control height — not a control).
- Width auto (content + horizontal padding).
- Border radius fully rounded (pill) — distinct from the `10px` control radius, so it's never mistaken for clickable.
- Padding: shared `12px` rhythm horizontally, tighter vertically.
- Font weight `600` (lighter than button `700`, reinforcing non-interactivity).

17.3 Color mapping
Status Indicators reuse the exact button color tokens (§5) — no new colors. Mapping by meaning, not by page:

| Meaning | Color token | Example states |
|---|---|---|
| Positive / complete / healthy | Teal (same token as Teal action button) | running, synced, completed successfully |
| Dangerous / failed / needs attention | Red (same token as Red action button) | crashed, error, sync failed |
| Neutral / inactive / not applicable | Body background + muted text (same token as General Normal button) | off, idle, not configured |
| Transitional / in progress | Blue (same token as Blue action button) | queued, starting, stopping, pending, backing_up, restoring |

- Mapping is exhaustive and closed — no fifth status color family (mirrors the two-button-family rule in §5).
- Same tokens as action buttons, so dark/light mode is inherited; no separate dark-mode token set.

17.4 Explicit bans (extends §14)
- No flashing, pulsing, or animated status indicators anywhere — state change is communicated by static color/text update, not motion.
- No page-specific or pane-specific status indicator variants.
- No third visual treatment beyond the four meanings in §17.3 (e.g., no separate "warning/yellow" color — re-evaluate against the four).

17.5 Reference class
- `.status-indicator` — base class; takes `data-tone` (or equivalent) of `positive` / `negative` / `neutral` / `transitional` to select the §17.3 mapping.
