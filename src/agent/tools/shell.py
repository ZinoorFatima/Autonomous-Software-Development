"""Sandboxed shell tool.

`run_command` executes ONLY allowlisted programs, ONLY inside the workspace, with
no shell interpretation (so `;`, `|`, `&&`, redirects, and `$()` cannot be used to
escape). This is the v1 stand-in for a Docker sandbox: the execution surface is
abstracted here so a container backend can replace it later.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from agent.tools.registry import ToolContext, ToolRegistry

# First token (program) must be in this set.
ALLOWED_PROGRAMS = {
    "python", "python3", "py",
    "pytest", "pip", "poetry", "uv",
    "git",
    "ls", "cat", "echo", "pwd",
    "ruff", "flake8", "mypy", "black",
}

DEFAULT_TIMEOUT = 600
MAX_OUTPUT = 30_000


def _program_name(token: str) -> str:
    """Basename of argv[0], lower-cased, without .exe — for allowlist checks.
    Handles absolute paths (e.g. a workspace venv's python.exe)."""
    return Path(token).name.lower().replace(".exe", "")


def execute_argv(
    root: Path, argv: list[str], timeout: int = DEFAULT_TIMEOUT
) -> dict[str, Any]:
    """Run an allowlisted argv list inside `root`. Shared by the run_command tool
    and the TestingAgent (which passes an argv list directly, avoiding shlex so
    paths with spaces — like a workspace venv python — survive intact)."""
    if not argv:
        return {"error": "Empty command."}
    program = _program_name(argv[0])
    if program not in ALLOWED_PROGRAMS:
        return {
            "error": f"Program '{program}' is not allowlisted. Allowed: {sorted(ALLOWED_PROGRAMS)}"
        }
    try:
        proc = subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=min(timeout, DEFAULT_TIMEOUT),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s", "command": " ".join(argv)}
    except FileNotFoundError:
        return {"error": f"Program not found: {program}"}

    stdout = (proc.stdout or "")[-MAX_OUTPUT:]
    stderr = (proc.stderr or "")[-MAX_OUTPUT:]
    return {
        "command": " ".join(argv),
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "summary": f"exit {proc.returncode}",
    }


def run_command(ctx: ToolContext, command: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as exc:
        return {"error": f"Could not parse command: {exc}"}
    return execute_argv(ctx.root, argv, timeout)


def register(registry: ToolRegistry) -> None:
    registry.add(
        "run_command",
        "Run an allowlisted command (pytest, pip, python, git, ruff, …) inside the "
        "workspace. No shell operators; single program only. Returns exit code + output.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "e.g. 'pytest -q' or 'python -m pip install -r requirements.txt'"},
                "timeout": {"type": "integer", "description": "Seconds, max 600"},
            },
            "required": ["command"],
        },
        run_command,
    )
