# Cleanup Action Log

| Date | Step | Item | Action | Notes |
|------|------|------|--------|-------|
| 2025-11-21 | Inventory | Repository-wide | Generated `inventory-summary.md` via temp Python scripts | Captured file counts by category and highlighted `.venv` size impact. |
| 2025-11-21 | Detection | Multiple docs/scripts | Recorded candidates in `redundant-candidates.md` | Includes `.venv`, `.idea`, duplicated READMEs, local AG Grid bundle, nested source tree, `NUL`. |
| 2025-11-21 | Dependency review | Key candidates | Added findings to `dependency-review.md` | Confirmed `.venv` & `.idea` untracked; CDN covers AG Grid; nested tree requires manual audit. |
| 2025-11-21 | Archival | `pst-analysis-engine/ag-grid-enterprise.min.js` | Moved to `_archive/2025-11-21/pst-analysis-engine/` | CDN usage confirmed; local copy isolated pending deletion. |
| 2025-11-21 | Archival | Developer onboarding docs (`README_DEV.md`, `README_PYCHARM.md`, `README_SETUP.md`) | Copied to `_archive/2025-11-21/docs/` | Originals left in place pending consolidation decision. |
| 2025-11-21 | Archival | AWS root scripts (`apprunner.yaml`, IAM helpers, `s3-policy.json`) | Moved to `_archive/2025-11-21/aws/` | Decommissioned with AWS hosting. |
| 2025-11-21 | Archival | AWS docs & configs under `pst-analysis-engine/` | Moved to `_archive/2025-11-21/aws/pst-analysis-engine/` | Includes AWS guides, env template, `setup_aws_s3.py`, `run_apprunner.sh`, and `docs/aws-reference/`. |
| 2025-11-21 | Validation | API app | Ran `python -m compileall pst-analysis-engine/api/app` | Verified Python source compiles after archival changes. |
| 2025-11-21 | Cleanup | Archived items | Pending stakeholder sign-off | Final deletion of archived assets deferred until approval. |
