# Copilot repository guardrail

This repository is the only authorized edit boundary for all work.

- Limit all reads and writes to the current repository root.
- Do not edit files outside this repository, including parent folders, sibling projects, or user-level directories.
- If a task requires work outside the repo, stop and report the blocker instead of writing external files.
- Keep all generated artifacts, scratch files, logs, and temporary outputs under repo-local folders.

These instructions apply to code, tests, docs, configs, and generated artifacts.
