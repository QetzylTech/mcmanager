# Document 4: CSS Style Guide

Purpose
- Single CSS reference for the entire site, based on the legacy prototype styling. All pages must follow it.
- No local styling systems for individual pages, panes, nav sections, or one-off elements.
- Primary source: `Prototypes/Legacy/static/global.css` — legacy page CSS is used only to identify reusable patterns for the shared system.

Core rules
- One shared visual system for the whole site.
- No local styling for panes, nav items, buttons, dropdowns, cards, or common controls.
- No nav alerts, nav pulses, or nav-specific attention styling.
- No page-specific button variants or pane-specific control styling.
- A pattern needed in more than one place belongs in shared global CSS.

1. Design direction
- Remain: compact, operational, pane-based, lightweight, easy to scan, consistent in light and dark mode.
- Don't become: decorative, marketing-like, overly animated, or full of page-specific control styles.

2. Global tokens
- Baseline values; change only if the entire site design changes.

Light mode
- Canvas/body background: `#eef2ff`; pane background: `#ffffff`; border: `#d8dee6`; main text: `#1f2a37`; muted text: `#5a6878`.

Dark mode
- Canvas/body background: `#161b22`; pane background: `#0d1117`; border: `#334155`; main text: `#e6edf3`; muted text: `#9fb0c6`.

Spacing and shape
- Control height `40px`; control min width `80px`; common gap `12px`; pane radius `12px`; inner radius `10px`; light shadow `0 2px 5px rgba(15, 23, 42, 0.04)`.

Typography
- Font stack `Arial, Helvetica, Roboto, sans-serif` on `html`, `body`, `button`, `input`, `textarea`, `select`.
- `h1` and `h2` share the same styling: `h1` is the page title when present; `h2` is the default pane title.

3. Layout system

3.1 Structure terms
- **Body** — top-level page container.
- **Landmarks** — children of the body; the only top-level elements are `nav` and `main`. `nav` reuses pane CSS and glues the app together; `main` is an unstylized container.
- **Panes** — children of `main`, implemented as `article` elements.
- **Cards** — children of panes. The first card in a pane is the Pane Title Area; remaining cards are Pane Content Areas.
- **Div groups** — children of cards, used only when needed.

3.2 Structure rules
- `nav` is always a child of `body`, a sibling of `main`; sticky; must not create its own scrollable area; spans the full available screen height.
- Every pane starts with exactly one Pane Title Area; remaining sibling cards are Pane Content Areas.
- Pane Title Area is a `header` containing the title (`h1`/`h2`) and optional pane buttons/inputs. No background color by default.
- Pane Content Area is a `div` (any card after the first); uses the body background color.
- Cards exist only for visual distinction between title and content.
- Div groups used only for: lists of items, grouping of form items, custom log output DOM. No default background or styling; no deeper wrapper chains unless genuinely required.
- App shell: persistent shell; desktop layout is left sidebar (`nav`) + right content area (`main`). Outer page padding `12px`; internal gap between major blocks `12px`.

4. Navigation
- Shared global style only. Nav links behave like general buttons; the active nav item uses the highlighted general button style.
- Sticky; not internally scrollable (page scrolls as a whole); spans full viewport height respecting outer page padding; spacing from the shared global rhythm.
- Forbidden: alert pulses, running-state green, warning-state yellow, red flashing, page-specific nav treatments.

5. Button system
- Exactly two families: **Action** (Red, Teal, Blue) and **General** (Normal, Highlighted). No other families.

5.1 Shared geometry (all buttons)
- Height `40px`; min width `80px`; border radius `10px`; font weight `700`; no page-specific sizing.

5.2 Action roles
| Color | Meaning | Example uses |
|---|---|---|
| Blue | Neutral | save, backup, confirm default action |
| Teal | Safe | start, create, continue, open/view as positive action |
| Red | Dangerous | stop, restore, delete, force action |

5.3 General roles
| Style | Meaning | Example uses |
|---|---|---|
| Normal (body background) | Neutral | close, cancel, secondary in-page navigation, non-destructive utility |
| Highlighted (purple) | Neutral with emphasis | any general button needing emphasis |

- Highlighted purple supports its own variations: Normal, Hover, Clicked, Disabled Normal, Disabled Hover, Disabled Clicked.
- Button color order when side by side: **Teal > Red > Blue > BG Color**.

6. Required button states
- Every button type supports, globally (never per page): Normal, On Hover, Onclick, Disabled Normal, Disabled On Hover, Disabled Onclick.
- Normal: stable, readable, clearly communicates its family. Hover: slight change, usually darker/stronger same-family color. Onclick: slight pressed feedback (subtle transform or darker shade). Disabled: lower contrast, clear non-interactive state; hover/click must not make it look active.

7. Dropdown system
- Trigger uses the general button style; list background uses the body background color.
- Height `40px`; same min-width logic and radius family as buttons/inputs; no page-specific dropdown themes.

8. Inputs and text fields
- Two global input kinds, one system: **Pane Title Area input** (`.ui-title-input`) and **Pane Content Area input** (`.ui-text-input`). They differ only by placement.
- Both: height `40px`; shared border/radius/padding/text/disabled/focus behavior; no page-specific overrides.
- Labels and controls sit beside each other when row width permits; wrap only when width requires; controls keep the `80px` min width when wrapping. Placement comes from shared CSS, not inline styles.
- Forbidden: a third input look; size/shape/behavior differences between the two kinds; pane- or page-specific input themes.

9. Shared content surfaces
- Panes, Pane Content Areas, lists, console outputs, and dialogs share one design language: rounded, low-shadow, compact padding, shared border/background tokens.
- Inheritance: body → body background; panes → pane background; Pane Title Area → none; Pane Content Area → body background; div groups → none.
- Forbidden: one-off gradients, decorative hero surfaces, page-specific content-area chrome, unique nav/pane skins.

10. Lists and selection rows
- One shared list surface style based on the body/input background system; shared item spacing and separators; item padding `12px`; row action spacing uses the shared `12px` gap.
- Selection affordances are global; selection highlighting is never redefined page by page.

11. Modal system
- Exactly four kinds: Confirmation, Password, Notification, Action Prompt. No other modal families.

11.1 Shared styling
- Modals use the semantic `dialog` element (no custom `div` overlays), with a dark translucent overlay.
- The dialog itself is styled as a pane: first card = Pane Title Area, remaining cards = Pane Content Areas; shared surface styling, radius, compact padding; stronger shadow than standard panes.
- Modal actions use the global button families and states; no modal-specific styling.

11.2 Allowed kinds
| Kind | Content | Actions |
|---|---|---|
| Confirmation | Summary of actions to be taken | Proceed / cancel |
| Password | Password input | Proceed / cancel |
| Notification | Informational; `Show more info` + `OK` buttons | OK; expand details |
| Action Prompt | Prompt for a navigation/denial/maintenance/missed-action/update decision | Cancel / proceed / defer to later |

12. Responsive rules
- Breakpoints: `1100px`, `900px`, `700px` when needed.
- Sidebar becomes overlay/off-canvas on smaller screens; multi-column layouts collapse cleanly; buttons may wrap/stack without visual change; controls remain `40px` tall.

13. Reuse rules
- Required workflow: 1) check if the style exists globally; 2) reuse it; 3) if missing, add it to the shared system; 4) reuse everywhere.
- Forbidden: new button look per page; different dropdown/input themes per pane; nav deviations; custom pane appearances; local alert styling on nav or pane headers; forced CSS overrides of shared geometry/spacing.

14. Explicit bans
- Nav alerts, nav pulses, nav severity colors.
- Page-only button colors; pane-only control styles; page-only dropdown themes; page-specific content-area chrome; page-specific pane skins; decorative hero styling; local styles for common elements when a shared style exists.

15. Short reference matrix

| Component | Spec |
|---|---|
| Action buttons | Red / Teal / Blue — each with 6 states |
| General buttons | Normal / Highlighted — each with 6 states |
| Geometry | Height `40px`; min width `80px` |
| Dropdowns | Trigger = general button style; list = body background |
| Navigation | Shared general-button-like styling only; no nav alerts |
| Panes | Shared styling only; no local visual overrides |
| Status indicators | Shared styling only (§17); four meanings; never interactive, never animated |

16. Final summary
- One global CSS language: one nav system, one pane system, one button system, one dropdown system, one token set, one status-indicator system.
- If a control looks different on one page, the styling is wrong unless the difference was formally added to the global system first.

17. Status Indicators

Purpose
- A Status Indicator (badge/pill) communicates the current state of something at a glance — a world's run state, a backup's status, a sync job's outcome — without being clickable and without introducing a new visual language.
- Informational only: never a button, never takes onclick behavior, never gains hover/pressed states.

17.1 Usage
- Stat boxes (Server Status, Backup Stats — Doc 1 §8).
- Backup list rows (sync status per backup — Doc 5).
- Anywhere a discrete state is shown as a compact label rather than prose.

17.2 Geometry
- Height `24px` (distinct from the `40px` control height — a Status Indicator is not a control).
- Width auto (content + horizontal padding); fully rounded (pill), distinct from the `10px` radius of buttons/dropdowns/inputs.
- Compact padding on the shared `12px` rhythm; font weight `600` (lighter than buttons' `700`, reinforcing non-interactivity).

17.3 Color mapping
- Reuses the action-button color tokens by *meaning*, not by page — no new colors, per §13.

| Meaning | Color token | Example states |
|---|---|---|
| Positive / complete / healthy | Teal | running, synced, completed successfully |
| Dangerous / failed / needs attention | Red | crashed, error, sync failed |
| Neutral / inactive / not applicable | Body background + muted text | off, idle, not configured |
| Transitional / in progress | Blue | queued, starting, stopping, pending, backing_up, restoring |

- Mapping is exhaustive and closed — no fifth color family. Dark/light mode inherited automatically from the shared tokens.

17.4 Bans (extends §14)
- No flashing, pulsing, or animated status indicators anywhere — state changes are communicated by static color/text updating, not motion.
- No page- or pane-specific variants — one shared component.
- No third visual treatment beyond the four meanings (no "warning/yellow" status; ambiguous states must map to the four).

17.5 Reference class
- `.status-indicator` — base class taking a `data-tone` value of `positive` / `negative` / `neutral` / `transitional` selecting the §17.3 mapping.
