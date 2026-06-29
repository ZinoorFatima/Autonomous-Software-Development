"""Tests for the GitRepo helper using a real local repo (no network)."""
from __future__ import annotations

from pathlib import Path

from git import Repo

from agent.tools.git_tools import GitRepo


def make_repo(tmp_path: Path) -> Path:
    Repo.init(str(tmp_path))
    (tmp_path / "f.txt").write_text("hello\n", encoding="utf-8")
    g = GitRepo(tmp_path)
    g.commit("initial", author_name="t", author_email="t@e.com")
    return tmp_path


def test_branch_and_commit(tmp_path: Path):
    make_repo(tmp_path)
    g = GitRepo(tmp_path)
    g.create_branch("feature/x")
    assert g.current_branch() == "feature/x"
    (tmp_path / "f.txt").write_text("hello world\n", encoding="utf-8")
    sha = g.commit("update", author_name="t", author_email="t@e.com")
    assert len(sha) == 40


def test_changed_files_and_diff(tmp_path: Path):
    make_repo(tmp_path)
    g = GitRepo(tmp_path)
    (tmp_path / "f.txt").write_text("changed\n", encoding="utf-8")
    assert "f.txt" in g.changed_files()
    assert "changed" in g.diff()
