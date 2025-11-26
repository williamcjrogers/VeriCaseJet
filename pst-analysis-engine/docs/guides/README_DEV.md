Development tooling quickstart (Windows)

- Install dev tools into your virtual environment:

```powershell
# From pst-analysis-engine directory
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

- Format and lint locally:

```powershell
# Format with Black and check Ruff
./format.ps1
# Or autofix Ruff issues too
./format.ps1 -Fix
```

- Enable pre-commit hooks (optional):

```powershell
pre-commit install
# run on all files once
pre-commit run --all-files
```

- Optional: PyCharm File Watcher
  - Program: `$PyInterpreterDirectory$/python`
  - Arguments: `-m black --quiet $FilePath$`
  - Working dir: `$ProjectFileDir$`

Black config lives in pyproject.toml and is shared across editors.

