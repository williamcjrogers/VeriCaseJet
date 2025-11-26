# Dependency & Conflict Review

Date: 2025-11-21
Reviewer: GPT-5 Codex (assistant)

This document records dependency checks for the items flagged as potentially redundant in `redundant-candidates.md`.

## 1. Build / Generated Artefacts

### `.venv/`
- **Status:** Present locally with ~49k files (Python packages, compiled artefacts).
- **Tracking:** `git ls-files .venv` returned no results → directory is currently untracked but bloats working copy.
- **Dependencies:** No scripts reference `.venv`; developers recreate environments via `pip`/`poetry`/`requirements.txt`.
- **Action:** Safe to ignore/remove. Update `.gitignore` to include `.venv/` so it is not recommitted.

### `.idea/`
- **Status:** Directory exists, but `git ls-files .idea` is empty (not tracked).
- **Dependencies:** IDE-specific; no build tooling depends on it.
- **Action:** Keep ignored; optionally add developer note. No conflicts.

### `pst-analysis-engine/ag-grid-enterprise.min.js`
- **Status:** Local copy of AG Grid Enterprise bundle.
- **Usage Check:** `grep` shows the UI loads AG Grid via CDN (`https://cdn.jsdelivr.net/...`). No imports reference the local file.
- **Action:** Candidate for removal to avoid version drift; ensure build pipeline does not expect local asset (none found).

## 2. Documentation Overlap

### Multiple README / Quick Start Guides
- **Files Reviewed:** Root `README.md`, `pst-analysis-engine/README*.md`, `START_HERE_FIRST.md`, `READY_TO_RUN.md`, `QUICK_START*.md`.
- **Dependencies:** No automated tooling reads these files (pure documentation). Overlap is organisational rather than technical.
- **Action:** Consolidate in later documentation pass. No blocking dependencies identified.

## 3. Source Code Duplication

### `pst-analysis-engine/pst-analysis-engine/`
- **Observation:** Nested directory mirrors parts of the primary `pst-analysis-engine` package.
- **Counts:**
  - Active `pst-analysis-engine/src`: 15 tracked files.
  - Nested `pst-analysis-engine/pst-analysis-engine/src`: 29 files (older timestamp: 2025-11-10).
- **Dependencies:** No immediate imports referencing the nested path were identified during quick scan; however, deeper audit needed to ensure no tooling points to nested copy.
- **Action:** Flag for manual review. Recommend checking deployment scripts & PYTHONPATH adjustments before removal.

### `NUL` File
- **Status:** File exists at repo root but `git ls-files NUL` returns nothing → not tracked. Windows-reserved name could cause sync issues.
- **Action:** Delete locally; ensure no automation depends on it (none found).

## Summary
- **Safe removals/ignores:** `.venv/`, `.idea/`, `pst-analysis-engine/ag-grid-enterprise.min.js`, `NUL` (not referenced).
- **Requires follow-up:** Documentation consolidation (content decision), nested `pst-analysis-engine/pst-analysis-engine` tree (confirm unused before deleting).

All findings will be carried into the archiving step once stakeholders confirm the decisions above.
