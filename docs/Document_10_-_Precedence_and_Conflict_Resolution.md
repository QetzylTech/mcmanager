Document 10: Precedence & Conflict Resolution

Purpose
- Establish a single rule for resolving disagreements between design documents.
- Record every known conflict found across Documents 1-9 and how each was resolved.
- Distinguish real conflicts from apparent-but-not-actual conflicts (terminology, taxonomy) so they aren't re-litigated later.
- Serve as the log that future conflicts get added to before code is written.

This document does not introduce new product requirements. It arbitrates between existing ones.

1. Precedence Rule

- Documents are ordered by number. A higher-numbered document supersedes a lower-numbered document wherever they conflict.
- Order of authority (highest to lowest): Doc 10 > Doc 9 > Doc 8 > Doc 7 > Doc 6 > Doc 5 > Doc 4 > Doc 3 > Doc 2 > Doc 1.
  - In practice, Doc 9 is a checklist/tracker, not a source of behavior, so it does not itself override anything; it only tracks completion status of the others.
  - Docs 6, 7, and 8 are now substantially complete (see Document 9's updated status) with specific, named remaining items rather than being wholesale in-progress. Where Doc 9 still shows an item open for one of them, treat the lower-numbered docs as authoritative on that specific point only, per the numbering rule.
- **One canonical file per document number.** Each numbered document must exist as exactly one file in the project at any time. If a document is revised, the new file replaces the old one (same or updated filename, old file removed) rather than the two coexisting — this project previously had both an original and a `_v2` file for Documents 5, 6, 7, and 8 simultaneously, with no rule for which one governed. That ambiguity is now resolved by deletion, not by a "the higher revision wins" rule, because a standing rule of that kind would require every reader to check file metadata instead of just reading the document — removing the stale copy is simpler and safer.
- Reference-only materials are outside the precedence chain entirely and never supersede a numbered document:
  - `ISO/IEC 25010` (external standard, informs quality goals, not a requirements source)
  - `legacyARCHITECTURE.md` and `legacyImplementation.txt` (historical record of the old system, not a spec for the new one)
  - `ARCHITECTURE.md` sits alongside the numbered docs as the standing instruction to AI coding assistants; where it references "Documents 2-10" it means them as governed by this precedence rule.
- Doc 1 is retained as historical/legacy-requirements reference. Where a later document has addressed a topic, Doc 1's version is superseded. Where a later document is silent on something Doc 1 covered, Doc 1 still applies until explicitly amended.

2. Resolved Conflicts

2.1 Nav alert / nav severity styling
- Conflict: Doc 1 §7 and §13 require the nav bar to flash orange/red and go solid teal based on server and job state. Doc 4 §4 and §14 explicitly ban all nav alerts, pulses, and severity coloring.
- Resolution: Doc 4 wins. The nav bar carries no status or notification indication of any kind — no flashing, no pulsing, and no static/solid state coloring either (e.g. no solid-teal-when-running). Nav is purely navigational.
- Clarification: this is a ban on *where* state indication appears (nav), not a ban on the colors themselves. Teal/red/orange/blue remain part of the shared button and status-color system and are used freely elsewhere — stat boxes, status fields, notification entries, etc. Nothing about the color system itself changes; only the nav area is off-limits for it.
- Replacement behavior: server/job state changes that previously drove nav flashing (starting, shutting down, crashed/emergency, restore-pane-open, missed cleanup) are surfaced through a dedicated notification section/dropdown in the shell, and through the existing per-page status displays (e.g. the Minecraft Status stat box already shows server state per Doc 1 §8 / Doc 5 homepage), per the alert-history model in Doc 2 §7.3 and Doc 8 §7 (Notifications).
- Amends: Doc 1 §7 ("Alerts" subsection) and §13 ("Notification system" nav-bar bullets) are marked superseded. Doc 4 requires no change; it already specifies the desired state.

2.2 Secrets storage mechanism
- Conflict: Doc 1 §12 places password hashes and the secret key in the env file. Doc 3 §6.5 describes a standalone "secret storage" subsystem that "may initially live on disk." Doc 7 §4 already lists a `secrets` table as part of the relational schema.
- Resolution: the SQLite `secrets` table (Doc 7) is the mechanism. Env-file-based secret storage is dropped as the primary store.
- Amends:
  - Doc 1 §12: remove "Secret keys" and "Password Hashes" from the list of env-file contents; env file retains only non-secret runtime config (paths, refresh rates).
  - Doc 3 §6.5: remove "may initially live on disk" language; state plainly that the `secrets` table is the storage backend, with the subsystem boundary (§5.10/§8.4) still standing as the access-control layer in front of it.
- Unchanged: Doc 3 §8.3/§8.4's rules (secrets never leave the server, per-world/per-session RCON isolation, rotation requirements) still apply — this resolution only changes *where* the bytes live, not the access rules around them.
- Confirmed: amendment applies to Doc 1 and Doc 3 only. Doc 4 has no secrets-related content and is unaffected.

3. Clarified Non-Conflicts

These looked like conflicts on a first pass but are not. Recorded here so they aren't reopened.

3.1 Modal taxonomy
- Doc 4 §11 defines exactly four structural modal kinds: Confirmation, Password, Notification, Action Prompt.
- Doc 1 §13 lists content-level variants: Action Successful, Action Accepted, Action Rejected (password verification failed), Password input prompt, Cleanup dry-run list, Cleanup execution summary, Error (with "more details"), Warnings/Prompts.
- These are not competing modal systems. Doc 1's list is content dressed inside Doc 4's four structural kinds. Mapping:
  - Action Successful acknowledgement -> Notification modal
  - Action Accepted (Initiated successfully) -> Notification modal
  - Password input prompt -> Password modal
  - Action Rejected (password verification failed) -> Password modal, rejected/retry state
  - Cleanup dry-run list -> Confirmation modal (summary of pending actions, proceed/cancel)
  - Cleanup execution summary -> Notification modal (informational, "Show more info" + OK)
  - Error (action failed, exception, has more-details button) -> Notification modal
  - Warnings/Prompts (clicking opens the concerned page/pane) -> Action Prompt modal
- No document needs amending. Future modal work should reference this mapping instead of inventing a fifth modal family.

3.2 Pane terminology ("Nav Pane / Header Pane / Content Pane / Action Pane" vs. "pane -> card -> div group")
- Doc 1 §7 names pane types by role: Nav Pane, Header Pane, Content Pane, Action Pane.
- Doc 4 §3.1 and Doc 5 describe pane internal structure: an `article` (pane) containing `header` (Pane Title Area) and one or more content `div`s (Pane Content Area), optionally with div groups inside.
- These describe different axes of the same object, not competing models: Doc 1's list is a classification of pane *purpose*; Doc 4/5's model is the *anatomy* every pane shares regardless of purpose. A Header Pane and a Content Pane are both still built from one Pane Title Area card plus Pane Content Area cards.
- No document needs amending. Future UI work should read Doc 1's pane-type names as labels for what a given pane instance is *for*, and Doc 4's structure as how *any* pane instance is *built*.

4. Forwarded to Document 6 (not resolved here)

These are gaps, not conflicts, and belong in the Doc 6 expansion work already tracked in Doc 9:
- `User` entity is referenced (Doc 7 relationships, Doc 8 `AuthenticationService`) but never defined as an entity in Doc 6.
- `RuntimeSession` is described as an entity with its own relationships in Doc 6, but has no corresponding table in Doc 7 §4's table list.

5. Change Log Convention

- Any new conflict discovered during Doc 6/7/8 completion or during implementation gets added to Section 2 of this document before it is resolved in code.
- Each new entry follows the format used above: Conflict / Resolution / Amends / Open items (if any).
- This document itself follows the precedence rule: as the highest-numbered document once complete, it has final say over any Doc 1-9 disagreement it explicitly addresses.
