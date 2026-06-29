"""Per-run workspace: clone the target repo, build an isolated venv, install deps,
and detect how to run the tests.

Each run gets its own directory under `WORKSPACE_ROOT` **and its own virtualenv**,
so the target repo's dependencies (and pytest) never collide with the agent's own
environment, and tests run against the interpreter that actually has them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.config import get_settings
from agent.tools.git_tools import GitRepo


@dataclass
class TestPlan:
    test_argv: list[str]
    description: str


class Workspace:
    def __init__(self, run_id: str, root: Path | None = None) -> None:
        settings = get_settings()
        base = root or settings.workspace_path
        base.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.path = base / run_id
        self.git: GitRepo | None = None

    # -- setup / teardown -------------------------------------------- #
    def clone(self, authed_url: str) -> GitRepo:
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        self.git = GitRepo.clone(authed_url, self.path)
        return self.git

    def cleanup(self) -> None:
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)

    # -- virtualenv -------------------------------------------------- #
    @property
    def venv_python(self) -> Path:
        if os.name == "nt":
            return self.path / ".venv" / "Scripts" / "python.exe"
        return self.path / ".venv" / "bin" / "python"

    def ensure_venv(self) -> Path:
        """Create the workspace venv if needed and return its python path."""
        if not self.venv_python.exists():
            subprocess.run(
                [sys.executable, "-m", "venv", str(self.path / ".venv")],
                cwd=str(self.path), capture_output=True, text=True, timeout=180,
            )
        return self.venv_python

    def install_deps(self) -> list[str]:
        """Install pytest plus the repo's own dependencies into the venv.

        Best-effort: returns a list of human-readable notes about what ran/failed,
        but never raises — a failed install just means tests may error, which the
        Debug agent can see.
        """
        py = str(self.ensure_venv())
        notes: list[str] = []

        def pip(*args: str, label: str) -> None:
            proc = subprocess.run(
                [py, "-m", "pip", "install", "-q", *args],
                cwd=str(self.path), capture_output=True, text=True, timeout=600,
            )
            notes.append(f"{label}: {'ok' if proc.returncode == 0 else 'failed'}")

        pip("-U", "pip", "pytest", label="pytest")
        if (self.path / "requirements.txt").exists():
            pip("-r", "requirements.txt", label="requirements.txt")
        elif (self.path / "pyproject.toml").exists() or (self.path / "setup.py").exists():
            pip("-e", ".", label="editable install")
        return notes

    # -- test detection ---------------------------------------------- #
    def detect_test_plan(self) -> TestPlan:
        """Return the argv to run the test suite with the workspace venv python."""
        py = str(self.venv_python)
        return TestPlan([py, "-m", "pytest", "-q"], "pytest in workspace venv")

    def run(self, argv: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv, cwd=str(self.path), capture_output=True, text=True,
            timeout=timeout, shell=False,
        )
