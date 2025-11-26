# Repository Inventory Summary

## Scan Metadata
- **Scan date:** 2025-11-21
- **Working directory:** `C:/Users/William/Documents/Projects/VeriCase Analysis`
- **Command source:** Temporary Python scripts (`.inventory_scan.py`, `.dir_counts.py`)

## File Counts by Category

| Category | Description | File Count |
|----------|-------------|-----------:|
| code     | Source files (`.py`, `.js`, `.ts`, `.html`, `.css`, `.sql`, scripts) | 16,632 |
| configs  | Configuration formats (`.json`, `.yaml`, `.ini`, `.cfg`) | 1,558 |
| docs     | Documentation (`.md`, `.rst`, `.txt`, `.pdf`) | 337 |
| data     | Data artefacts (`.csv`, `.xlsx`, `.db`, etc.) | 36 |
| build    | Generated build artefacts (`.lock`, `.log`, `.tmp`) | 6 |
| other    | Everything else (not in categories above) | 32,546 |
| **Total** |  | **51,115** |

### Notable "Other" Extensions (Top 15)
- `.pyc`: 16,116 files (Python bytecode, likely redundant if `.venv` or build output)
- `.h`: 9,254 (C/C++ headers, bundled within `.venv`)
- `(no ext)`: 3,580 (mixed executables, metadata)
- `.gz`: 986 (compressed resources)
- `.pyi`: 601 (type hint stubs)
- `.pyd`: 289 (native Python extensions)
- `.lib`: 147, `.a`: 114, `.mat`: 110, `.typed`: 107, `.hpp`: 83, `.pyx`: 79, `.cpp`: 70, `.proto`: 63, `.cuh`: 63

## Top-Level Folder Footprint

| Top-Level Item | File Count | Notes |
|----------------|-----------:|-------|
| `.venv` | 49,151 | Dominates repository size; Python virtual environment committed to repo. Primary candidate for archival/removal. |
| `pst-analysis-engine` | 1,788 | Main application source tree. |
| `.git` | 117 | Git metadata (expected). |
| `.idea` | 27 | IDE settings. |
| Project root files | 29 | Individual scripts/docs at root level. |

> **Observation:** The `.venv` directory accounts for ~96% of all tracked files, explaining the large volume of compiled `.pyc`, headers, and native libs in the "other" bucket.

## Next Steps
- Exclude or archive `.venv` and any other generated environments.
- Use this inventory to drive redundancy detection (Step 2 of cleanup plan).
