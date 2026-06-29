"""Code search tool. Uses ripgrep if available, else a pure-Python fallback."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent.tools.files import IGNORE_DIRS
from agent.tools.registry import ToolContext, ToolRegistry

MAX_RESULTS = 100


def _ripgrep(root: Path, pattern: str, glob: str | None) -> list[str] | None:
    rg = shutil.which("rg")
    if not rg:
        return None
    cmd = [rg, "--line-number", "--no-heading", "--color", "never", "--max-count", "50"]
    if glob:
        cmd += ["--glob", glob]
    cmd += [pattern, str(root)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode not in (0, 1):  # 1 = no matches
        return None
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    return lines[:MAX_RESULTS]


def _python_grep(root: Path, pattern: str, glob: str | None) -> list[str]:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return [f"(invalid regex: {exc})"]
    results: list[str] = []
    for p in root.rglob(glob or "*"):
        if not p.is_file():
            continue
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    rel = p.relative_to(root).as_posix()
                    results.append(f"{rel}:{i}:{line.strip()[:200]}")
                    if len(results) >= MAX_RESULTS:
                        return results
        except OSError:
            continue
    return results


def search_code(ctx: ToolContext, pattern: str, glob: str | None = None) -> dict[str, Any]:
    root = ctx.root.resolve()
    matches = _ripgrep(root, pattern, glob)
    engine = "ripgrep"
    if matches is None:
        matches = _python_grep(root, pattern, glob)
        engine = "python"
    # Normalise ripgrep absolute paths to relative.
    rel_matches = []
    for m in matches:
        rel_matches.append(m.replace(str(root) + "\\", "").replace(str(root) + "/", ""))
    return {
        "pattern": pattern,
        "engine": engine,
        "matches": rel_matches,
        "count": len(rel_matches),
        "summary": f"{len(rel_matches)} match(es) for /{pattern}/",
    }


def register(registry: ToolRegistry) -> None:
    registry.add(
        "search_code",
        "Search the repository for a regex pattern. Optionally restrict with a glob "
        "(e.g. '*.py'). Returns 'path:line:text' matches.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex to search for"},
                "glob": {"type": "string", "description": "Optional file glob, e.g. '*.py'"},
            },
            "required": ["pattern"],
        },
        search_code,
    )
