# AGENTS.md

This repository is the only authorized edit boundary for all project work.

Rules for every agent:
- Work only inside the current repository root.
- Read files from within the repo; do not depend on or edit files outside this root
- Do not create, delete, move, rename, or patch files in parent folders, sibling repos, or unrelated directories
- Do not write generated or temporary artifacts outside this repository
- If a task needs a scratch file, place it under the repo's existing working directories (for example, app/data/, dev_artifacts/, or a task-local folder inside the repo)
- If a required file is outside the repo, stop and report the blocker instead of editing external content

This rule applies to all source changes, test edits, docs updates, generated files, and any operational artifacts produced during work.
