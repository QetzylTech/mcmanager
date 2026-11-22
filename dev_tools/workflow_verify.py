from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "AGENTS.md",
    "docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md",
    "docs/WORKBOARD.md",
    "docs/wbs.txt",
    "Audits/README.md",
)

errors: list[str] = []
warnings: list[str] = []

for relative_path in REQUIRED_FILES:
    if not (PROJECT_ROOT / relative_path).is_file():
        errors.append(f"missing required file: {relative_path}")

agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
if "docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md" not in agents:
    errors.append("AGENTS.md does not reference the workflow specification")
if "docs/WORKBOARD.md" not in agents:
    errors.append("AGENTS.md does not reference the workboard")

spec = (PROJECT_ROOT / "docs/AGENT_DEVELOPMENT_WORKFLOW_SPEC.md").read_text(encoding="utf-8")
if "**Status:** Approved" not in spec:
    errors.append("workflow specification is not marked Approved")

workboard = (PROJECT_ROOT / "docs/WORKBOARD.md").read_text(encoding="utf-8")
if "## In Progress" not in workboard:
    errors.append("workboard has no In Progress section")
if "KB-WF-001" not in workboard:
    errors.append("workflow migration task KB-WF-001 is missing")

section = None
card_id = None
for line in workboard.splitlines():
    heading = re.match(r"^## (Backlog|To Do|In Progress|Review|Blocked|Done)$", line)
    if heading:
        section = heading.group(1)
        continue
    card = re.match(r"^### (KB-[A-Z0-9-]+)", line)
    if card:
        card_id = card.group(1)
        continue
    status = re.match(r"^- \*\*Status:\*\* (Backlog|To Do|In Progress|Review|Blocked|Done)$", line)
    if status and card_id and section:
        card_status = status.group(1)
        if card_status != section:
            warnings.append(f"{card_id}: Status={card_status}, section={section}")

audits_readme = (PROJECT_ROOT / "Audits/README.md").read_text(encoding="utf-8")
for required_term in ("PASS", "PASS_WITH_FINDINGS", "FAIL", "BLOCKER", "BLOCKED"):
    if required_term not in audits_readme:
        errors.append(f"Audits/README.md missing audit term: {required_term}")

for warning in warnings:
    print(f"WARNING: {warning}")
for error in errors:
    print(f"ERROR: {error}", file=sys.stderr)

if errors:
    raise SystemExit(1)
print("Workflow documentation checks passed")
print(f"Workboard status/section warnings: {len(warnings)}")
