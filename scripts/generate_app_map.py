"""Generate a repo-wide APP_MAP.md.

Goal: produce a practical, navigable map of the VeriCase repo:
- high-level architecture summary
- per-directory intent
- per-file role hints
- dependency signals (imports / requires / script refs)

This is best-effort static analysis intended for humans. It does not execute code.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "docs" / "APP_MAP.md"

# Keep the map focused on source + operational docs; omit very large/binary-like artifacts.
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "nul",
}

SKIP_FILE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
    ".ico",
    ".pdf",
    ".docx",
    ".pem",
    ".ttf",
    ".woff",
    ".woff2",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".db",
    ".exe",
    ".dll",
}

MAX_BYTES = 220_000  # avoid parsing huge bundled JS assets etc.


@dataclass(frozen=True)
class FileInfo:
    rel_path: str
    ext: str
    size_bytes: int
    role_hint: str
    deps: list[str]


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skip dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            yield Path(dirpath) / fn


def safe_read_text(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def role_hint_for_path(rel: str) -> str:
    # Lightweight heuristics for this repo specifically.
    # Keep these hints human-readable and conservative.
    r = rel.replace("\\", "/")

    if r == "README.md" or r.endswith("/README.md"):
        return "Documentation / operator guide"

    if r.startswith("vericase/api/app/"):
        if r.endswith("main.py"):
            return "API entrypoint (FastAPI app)"
        if r.endswith("config.py") or r.endswith("config_production.py"):
            return "API configuration"
        if r.endswith("db.py"):
            return "Database connection + session management"
        if r.endswith("auth.py") or r.endswith("auth_enhanced.py"):
            return "Authentication / authorization"
        if r.endswith("ai_router.py") or r.endswith("ai_orchestrator.py"):
            return "AI routing/orchestration"
        if r.endswith("models.py"):
            return "Database models / schemas"
        return "API module"

    if r.startswith("vericase/ui/"):
        if r.endswith("vericase-ui.js") or r.endswith("nav-shell.js"):
            return "UI shell / client runtime"
        if r.endswith(".html"):
            return "UI page"
        if r.endswith(".css"):
            return "UI styling"
        if r.endswith(".js"):
            return "UI script/module"
        return "UI asset"

    if r.startswith("vericase/k8s/"):
        return "Kubernetes manifests"

    if r.startswith("vericase/nginx/"):
        return "Nginx configuration"

    if r.startswith("vericase/tests/"):
        return "Tests"

    if r.startswith("vericase/ops/"):
        return "Ops scripts (deploy/diagnose/cleanup)"

    if r.startswith("scripts/"):
        return "Repo helper script"

    if r.endswith("docker-compose.yml") or r.endswith("docker-compose.prod.yml"):
        return "Local/production container orchestration"

    if r.endswith("pyproject.toml"):
        return "Python project configuration"

    if r.endswith("requirements.txt"):
        return "Python dependencies"

    return ""


def deps_from_python(source: str) -> list[str]:
    deps: set[str] = set()
    try:
        tree = ast.parse(source)
    except Exception:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                deps.add(node.module.split(".")[0])

    # Reduce noise: hide obvious stdlib modules
    stdlib_like = {
        "os",
        "sys",
        "re",
        "json",
        "time",
        "datetime",
        "pathlib",
        "typing",
        "dataclasses",
        "logging",
        "uuid",
        "base64",
        "hashlib",
        "subprocess",
        "asyncio",
        "functools",
        "itertools",
        "collections",
        "math",
        "random",
        "tempfile",
        "traceback",
        "contextlib",
        "http",
        "email",
    }

    filtered = [d for d in deps if d and d not in stdlib_like]
    return sorted(filtered)


_JS_IMPORT_RE = re.compile(
    r"(?m)^\s*(?:import\s+[^;]+?from\s+['\"](?P<im1>[^'\"]+)['\"]|import\s*\(\s*['\"](?P<im2>[^'\"]+)['\"]\s*\)|require\(\s*['\"](?P<im3>[^'\"]+)['\"]\s*\))"
)


def deps_from_js_like(source: str) -> list[str]:
    deps: set[str] = set()
    for m in _JS_IMPORT_RE.finditer(source):
        imp = m.group("im1") or m.group("im2") or m.group("im3")
        if not imp:
            continue
        # Keep module specifiers as-is; they are meaningful (relative vs package)
        deps.add(imp)
    return sorted(deps)


def parse_docker_compose_services(compose_text: str) -> list[dict[str, object]]:
    """Very small docker-compose parser (best-effort).

    We only need a human-facing summary: services + images/build + ports/depends_on.
    Avoid introducing a PyYAML dependency.
    """

    services: list[dict[str, object]] = []
    in_services = False
    current: dict[str, object] | None = None

    for raw in compose_text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue

        # When we reach a new top-level section (e.g., volumes:, networks:), stop.
        # This prevents mis-parsing volume names as services.
        if (
            in_services
            and re.match(r"^[A-Za-z0-9_-]+:\s*$", line)
            and not re.match(r"^services:\s*$", line)
        ):
            break

        if re.match(r"^services:\s*$", line):
            in_services = True
            continue

        if not in_services:
            continue

        # service name: two spaces indent
        m_service = re.match(r"^\s{2}([A-Za-z0-9_-]+):\s*$", line)
        if m_service:
            if current:
                services.append(current)
            current = {
                "name": m_service.group(1),
                "image": None,
                "build": None,
                "ports": [],
                "depends_on": [],
                "volumes": [],
                "command": None,
            }
            continue

        if current is None:
            continue

        # image:
        m_image = re.match(r"^\s{4}image:\s*(.+?)\s*$", line)
        if m_image:
            current["image"] = m_image.group(1).strip()
            continue

        # build: (either single line or start of block)
        m_build = re.match(r"^\s{4}build:\s*(.+?)\s*$", line)
        if m_build:
            current["build"] = m_build.group(1).strip()
            continue
        if re.match(r"^\s{4}build:\s*$", line):
            current["build"] = "(build block)"
            continue

        # ports: ["8010:8000", ...]
        m_ports_inline = re.match(r"^\s{4}ports:\s*\[(.+)\]\s*$", line)
        if m_ports_inline:
            items = [p.strip().strip("\"'") for p in m_ports_inline.group(1).split(",")]
            current["ports"] = [p for p in items if p]
            continue

        # depends_on: [a, b]
        m_dep_inline = re.match(r"^\s{4}depends_on:\s*\[(.+)\]\s*$", line)
        if m_dep_inline:
            items = [p.strip().strip("\"'") for p in m_dep_inline.group(1).split(",")]
            current["depends_on"] = [p for p in items if p]
            continue

        # volumes: ["..."]
        m_vol_inline = re.match(r"^\s{4}volumes:\s*\[(.+)\]\s*$", line)
        if m_vol_inline:
            items = [p.strip().strip("\"'") for p in m_vol_inline.group(1).split(",")]
            current["volumes"] = [p for p in items if p]
            continue

        # command: (single-line)
        m_cmd = re.match(r"^\s{4}command:\s*(.+?)\s*$", line)
        if m_cmd:
            current["command"] = m_cmd.group(1).strip()
            continue

    if current:
        services.append(current)

    return services


def parse_fastapi_wiring(main_py_text: str) -> dict[str, object]:
    """Extract FastAPI integration points from `vericase/api/app/main.py`.

    - which routers are included and where they come from
    - which static mounts exist (/ui, /assets)

    Uses AST parsing for robustness against multi-line imports.
    """
    router_imports: dict[str, str] = {}
    included: list[dict[str, str]] = []
    mounts: list[dict[str, str]] = []

    try:
        tree = ast.parse(main_py_text)
    except SyntaxError:
        return {"routers": [], "mounts": []}

    for node in ast.walk(tree):
        # 1. Track imports: from .module import router as alias
        if isinstance(node, ast.ImportFrom) and node.module:
            # We only care about relative imports for local modules
            mod_name = (
                ("." * node.level) + node.module if node.level > 0 else node.module
            )
            for name in node.names:
                # Track all imports. If asname exists, use it, otherwise use name.
                # This covers:
                #   from .x import router as y  -> y: .x
                #   from .x import y            -> y: .x
                imported_as = name.asname if name.asname else name.name
                router_imports[imported_as] = mod_name

        # 2. Track app.include_router(alias)
        if isinstance(node, ast.Call):
            # Check for app.include_router(...)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "app"
            ):
                if node.args and isinstance(node.args[0], ast.Name):
                    rtr_name = node.args[0].id
                    included.append(
                        {
                            "router_var": rtr_name,
                            "module": router_imports.get(rtr_name, ""),
                        }
                    )

            # 3. Track app.mount(path, app, name=...)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "mount"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "app"
            ):
                # We expect at least 2 args: path, app
                path_val = ""
                name_val = ""

                # Extract path (arg 0)
                if node.args and isinstance(node.args[0], ast.Constant):
                    path_val = str(node.args[0].value)

                # Extract name (keyword arg)
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        name_val = str(kw.value.value)

                if path_val:
                    mounts.append({"path": path_val, "name": name_val})

    return {"routers": included, "mounts": mounts}


def deps_from_yaml_like(source: str) -> list[str]:
    # crude extraction of image: / container: references
    deps: set[str] = set()
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("image:"):
            deps.add(line.split(":", 1)[1].strip())
    return sorted(deps)


def should_skip_file(path: Path) -> bool:
    if path.suffix.lower() in SKIP_FILE_SUFFIXES:
        return True

    # Ignore large bundled UI artifacts under Deep Research folder
    # (looks like vendor bundles / captured web assets)
    if "Deep Research" in path.parts:
        return True

    return False


def collect_file_info(path: Path) -> Optional[FileInfo]:
    if should_skip_file(path):
        return None

    try:
        st = path.stat()
    except Exception:
        return None

    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    ext = path.suffix.lower()

    role_hint = role_hint_for_path(rel)

    deps: list[str] = []
    src = safe_read_text(path)
    if src is not None:
        if ext == ".py":
            deps = deps_from_python(src)
        elif ext in {".js", ".ts", ".mjs", ".cjs", ".html"}:
            deps = deps_from_js_like(src)
        elif ext in {".yml", ".yaml"}:
            deps = deps_from_yaml_like(src)

    return FileInfo(
        rel_path=rel, ext=ext, size_bytes=st.st_size, role_hint=role_hint, deps=deps
    )


def group_by_top_dir(files: list[FileInfo]) -> dict[str, list[FileInfo]]:
    grouped: dict[str, list[FileInfo]] = {}
    for f in files:
        parts = f.rel_path.split("/")
        top = parts[0] if len(parts) > 1 else "."
        grouped.setdefault(top, []).append(f)
    for k in grouped:
        grouped[k].sort(key=lambda x: x.rel_path)
    return dict(sorted(grouped.items(), key=lambda kv: kv[0]))


def md_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("`", "\\`")


def write_app_map(files: list[FileInfo]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    grouped = group_by_top_dir(files)

    # Best-effort parsing of key integration points.
    compose_services: list[dict[str, object]] = []
    compose_path = REPO_ROOT / "vericase" / "docker-compose.yml"
    compose_text = safe_read_text(compose_path) if compose_path.exists() else None
    if compose_text:
        compose_services = parse_docker_compose_services(compose_text)

    fastapi_wiring: dict[str, object] = {"routers": [], "mounts": []}
    main_py_path = REPO_ROOT / "vericase" / "api" / "app" / "main.py"
    main_py_text = safe_read_text(main_py_path) if main_py_path.exists() else None
    if main_py_text:
        fastapi_wiring = parse_fastapi_wiring(main_py_text)

    def _as_str_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, tuple):
            return [str(v) for v in value]
        return []

    lines: list[str] = []
    lines.append("# VeriCase — App Map (repo-wide)")
    lines.append("")
    lines.append(
        "This file is auto-generated by `scripts/generate_app_map.py`. It is a **best-effort static map** of the repository: what’s where, what each area seems to do, and dependency signals (imports / module refs)."
    )
    lines.append("")
    lines.append("## High-level architecture (best-effort)")
    lines.append("")
    lines.append(
        "- **Backend API:** `vericase/api/app/` (Python). Looks like a FastAPI-style service with auth, cases, correspondence, evidence, AI orchestration/routing, and AWS integration."
    )
    lines.append(
        "- **UI:** `vericase/ui/` (HTML/CSS/JS). Multi-page UI with shared shell scripts and component fragments."
    )
    lines.append(
        "- **Worker:** `vericase/worker_app/` (Python). Background worker process."
    )
    lines.append(
        "- **Infra/Ops:** `vericase/k8s/`, `vericase/nginx/`, `vericase/ops/`, top-level deployment scripts."
    )
    lines.append("- **Tests:** `vericase/tests/` (pytest-style).")
    lines.append("")

    lines.append("## Navigation tips")
    lines.append("")
    lines.append("If you’re new to the repo, start here:")
    lines.append("- `vericase/README.md` and `vericase/docs/START_HERE_FIRST.md`")
    lines.append("- API entrypoint: `vericase/api/app/main.py`")
    lines.append(
        "- UI shell/runtime: `vericase/ui/vericase-ui.js` + `vericase/ui/nav-shell.js`"
    )
    lines.append("- Local orchestration: `vericase/docker-compose.yml`")
    lines.append("")

    lines.append("## Runtime topology (docker-compose)")
    lines.append("")
    if compose_services:
        lines.append("This is derived from `vericase/docker-compose.yml`.")
        lines.append("")
        lines.append("| Service | Image / build | Ports | Depends on | Notes |")
        lines.append("|---|---|---|---|---|")
        for svc in compose_services:
            name = str(svc.get("name") or "")
            img = str(svc.get("image") or "")
            build = str(svc.get("build") or "")
            img_or_build = img if img else (f"build {build}" if build else "")
            ports = ", ".join(_as_str_list(svc.get("ports")))
            depends = ", ".join(_as_str_list(svc.get("depends_on")))
            notes = ""
            if name == "api":
                notes = "FastAPI service; serves UI at /ui (mounted) and API at /api/*"
            elif name == "worker":
                notes = "Celery worker (pst_processing queue)"
            elif name == "minio":
                notes = "Object storage (PST + attachments)"
            elif name == "opensearch":
                notes = "Search index"
            elif name == "tika":
                notes = "Document text extraction"
            elif name == "postgres":
                notes = "Primary relational DB"
            elif name == "redis":
                notes = "Celery broker / cache"
            lines.append(
                "| "
                + md_escape(name)
                + " | "
                + md_escape(img_or_build)
                + " | "
                + md_escape(ports)
                + " | "
                + md_escape(depends)
                + " | "
                + md_escape(notes)
                + " |"
            )
        lines.append("")
    else:
        lines.append(
            "(Unable to parse docker-compose services; file missing or too large.)"
        )
        lines.append("")

    lines.append("## Backend wiring (FastAPI)")
    lines.append("")
    if main_py_text:
        lines.append("Derived from `vericase/api/app/main.py`.")
        lines.append("")
        mounts_val = fastapi_wiring.get("mounts")
        routers_val = fastapi_wiring.get("routers")
        mounts: list[dict[str, str]] = (
            mounts_val if isinstance(mounts_val, list) else []
        )  # best-effort typing
        routers: list[dict[str, str]] = (
            routers_val if isinstance(routers_val, list) else []
        )  # best-effort typing

        if mounts:
            lines.append("### Static mounts")
            lines.append("")
            for m in mounts:
                if not isinstance(m, dict):
                    continue
                lines.append(
                    f"- `{md_escape(str(m.get('path') or ''))}` → `{md_escape(str(m.get('name') or ''))}`"
                )
            lines.append("")

        if routers:
            lines.append("### Included routers")
            lines.append("")
            lines.append("| Router var | Module |")
            lines.append("|---|---|")
            for r in routers:
                if not isinstance(r, dict):
                    continue
                lines.append(
                    "| `"
                    + md_escape(str(r.get("router_var") or ""))
                    + "` | `"
                    + md_escape(str(r.get("module") or ""))
                    + "` |"
                )
            lines.append("")
    else:
        lines.append(
            "(Unable to read main FastAPI entrypoint: `vericase/api/app/main.py`.)"
        )
        lines.append("")

    lines.append("## Repo inventory (by top-level folder)")
    lines.append("")

    for top, fs in grouped.items():
        lines.append(f"### `{md_escape(top)}/`")
        lines.append("")
        lines.append("| File | Role hint | Dependency signals |")
        lines.append("|---|---|---|")
        for f in fs:
            # Keep dependency column readable
            dep_str = ", ".join(f.deps[:12])
            if len(f.deps) > 12:
                dep_str += f" … (+{len(f.deps) - 12} more)"

            role = f.role_hint or ""
            lines.append(
                "| `"
                + md_escape(f.rel_path)
                + "` | "
                + md_escape(role)
                + " | "
                + md_escape(dep_str)
                + " |"
            )
        lines.append("")

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    files: list[FileInfo] = []
    for p in iter_files(REPO_ROOT):
        info = collect_file_info(p)
        if info is None:
            continue
        # Skip our own output to avoid self-referential noise.
        if info.rel_path.replace("\\", "/") == str(
            OUTPUT_PATH.relative_to(REPO_ROOT)
        ).replace("\\", "/"):
            continue
        files.append(info)

    # Deterministic ordering of overall list
    files.sort(key=lambda x: x.rel_path)

    write_app_map(files)
    print(f"Wrote: {OUTPUT_PATH}")
    print(f"Files indexed: {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
