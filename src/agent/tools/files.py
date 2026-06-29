"""File tools: read_file, write_file, edit_file, list_dir. All sandboxed."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.registry import ToolContext, ToolRegistry

MAX_READ_BYTES = 200_000
IGNORE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}


def read_file(ctx: ToolContext, path: str, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    p = ctx.safe_path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if p.is_dir():
        return {"error": f"{path} is a directory; use list_dir."}
    data = p.read_text(encoding="utf-8", errors="replace")
    truncated = len(data.encode("utf-8")) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return {
        "path": path,
        "content": data,
        "truncated": truncated,
        "summary": f"read {len(data)} chars from {path}",
    }


def write_file(ctx: ToolContext, path: str, content: str) -> dict[str, Any]:
    p = ctx.safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    return {
        "path": path,
        "created": not existed,
        "bytes": len(content.encode("utf-8")),
        "summary": f"{'created' if not existed else 'overwrote'} {path}",
    }


def edit_file(
    ctx: ToolContext, path: str, old_string: str, new_string: str, replace_all: bool = False
) -> dict[str, Any]:
    """Anchored replace — `old_string` must appear (uniquely unless replace_all)."""
    p = ctx.safe_path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return {"error": f"old_string not found in {path}. Read the file first."}
    if count > 1 and not replace_all:
        return {
            "error": f"old_string is not unique in {path} ({count} matches). "
            "Add surrounding context or set replace_all=true."
        }
    new_text = text.replace(old_string, new_string)
    p.write_text(new_text, encoding="utf-8")
    return {
        "path": path,
        "replacements": count if replace_all else 1,
        "summary": f"edited {path} ({count if replace_all else 1} replacement(s))",
    }


def list_dir(ctx: ToolContext, path: str = ".", depth: int = 2) -> dict[str, Any]:
    base = ctx.safe_path(path)
    if not base.exists():
        return {"error": f"Not found: {path}"}
    root = ctx.root.resolve()
    lines: list[str] = []

    def walk(d: Path, prefix: str, level: int) -> None:
        if level > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return
        for e in entries:
            if e.name in IGNORE_DIRS:
                continue
            rel = e.relative_to(root)
            lines.append(f"{prefix}{'📁 ' if e.is_dir() else '📄 '}{rel.as_posix()}")
            if e.is_dir():
                walk(e, prefix + "  ", level + 1)

    if base.is_dir():
        walk(base, "", 1)
    else:
        lines.append(base.relative_to(root).as_posix())
    return {"path": path, "tree": "\n".join(lines), "count": len(lines), "summary": f"{len(lines)} entries"}


def register(registry: ToolRegistry) -> None:
    registry.add(
        "read_file",
        "Read a UTF-8 text file from the workspace. Returns its content.",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path relative to repo root"}},
            "required": ["path"],
        },
        read_file,
    )
    registry.add(
        "write_file",
        "Create or overwrite a file with the given content. Creates parent dirs.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        write_file,
    )
    registry.add(
        "edit_file",
        "Replace an exact substring in a file. old_string must match exactly and be "
        "unique unless replace_all is true. Prefer this over write_file for edits.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        edit_file,
    )
    registry.add(
        "list_dir",
        "List files/directories under a path as a tree (ignores .git, venv, node_modules…).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Defaults to repo root '.'"},
                "depth": {"type": "integer", "description": "Recursion depth, default 2"},
            },
        },
        list_dir,
    )
