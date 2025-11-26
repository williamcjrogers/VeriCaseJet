# Redundant / Conflicting File Candidates

This list captures files and directories that appear to be redundant, conflicting, or auto-generated. These items should be reviewed in the next cleanup steps before archiving or removal.

## Build / Generated Artefacts

| Location | Approx. Size | Evidence | Recommended Action |
|----------|--------------|----------|--------------------|
| `.venv/` | ~49k files (dominates repo) | Inventory scan shows 49,151 tracked files (main source of `.pyc`, `.h`, `.pyd`, `.lib`). | Remove from VCS; add to `.gitignore`. Consider recreating locally when needed. |
| `.idea/` | 27 files | JetBrains IDE settings. Not required for all contributors. | Move to developer-specific ignore list or document opt-in usage. |
| `pst-analysis-engine/ag-grid-enterprise.min.js` | 1 file (~8KB) | CDN version already referenced in UI (`https://cdn.jsdelivr.net/...`). | Remove bundled copy; rely on CDN or vendor package manager. |
| `*.pyc`, `*.pyd`, `*.lib` within repo | Thousands (primarily inside `.venv/`) | Compiled Python artefacts. | Purge alongside `.venv`. |
| `__pycache__/` directories | (implicit) | Created by CPython; should be excluded with `.gitignore`. | Confirm none remain after `.venv` removal; add ignore rules if needed. |

## Documentation Overlap

| Files | Notes | Proposed Canonical Source |
|-------|-------|---------------------------|
| `README.md`, `pst-analysis-engine/README.md`, `pst-analysis-engine/README_DEV.md`, `pst-analysis-engine/README_SETUP.md`, `pst-analysis-engine/README_PYCHARM.md`, `pst-analysis-engine/api/migrations/README.md`, `pst-analysis-engine/migrations/README.md` | Multiple onboarding guides with overlapping content. | Consolidate into root `README.md` + targeted docs (e.g., `/docs/setup.md`). Flag duplicates for merge in documentation phase. |
| Numerous quick-start guides (`START_HERE_FIRST.md`, `READY_TO_RUN.md`, `QUICK_START.md`, etc.) | Similar purpose, conflicting instructions. | Create a single authoritative onboarding guide; retire outdated copies. |

## Source Code Duplication / Legacy Copies

| Location | Concern | Suggested Follow-up |
|----------|---------|---------------------|
| `pst-analysis-engine/pst-analysis-engine/` (nested source tree) | Appears to duplicate primary `pst-analysis-engine` app structure. | Audit modules for last modification dates and references; decide whether to keep only one source tree. |
| `ag-grid-enterprise.min.js` alongside CDN usage | Local asset may be stale vs remote version. | Confirm no build step depends on local file; remove to avoid version drift. |

## Miscellaneous Items

| Item | Notes / Risk | Recommendation |
|------|--------------|----------------|
| `NUL` (top-level file) | Reserved device name on Windows; can create sync/build issues. | Delete or rename; ensure not required by tooling. |
| `pst-analysis-engine/ai_*` vs `pst-analysis-engine/pst-analysis-engine/src/app/ai_*` | Similar filenames could confuse maintainers. | During dependency review, confirm active entry points and retire stale module copies. |

---

*Next step:* Review dependencies and confirm that removing/archiving the items above will not break builds or onboarding flows. Document findings in `CLEANUP_LOG.md` before proceeding to archiving.*
