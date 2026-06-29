"""Git helpers.

`GitRepo` wraps GitPython for the operations the orchestrator performs at
checkpoints (branch, commit, push). A read-only `git_diff`/`git_status` is also
exposed as a tool so the Review and Security agents can inspect what changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from git import Repo

from agent.tools.registry import ToolContext, ToolRegistry


class GitRepo:
    def __init__(self, path: Path) -> None:
        self.repo = Repo(str(path))

    @classmethod
    def clone(cls, url: str, dest: Path) -> "GitRepo":
        Repo.clone_from(url, str(dest))
        return cls(dest)

    def current_branch(self) -> str:
        return self.repo.active_branch.name

    def create_branch(self, name: str) -> str:
        new = self.repo.create_head(name)
        new.checkout()
        return name

    def diff(self, staged: bool = False) -> str:
        if staged:
            return self.repo.git.diff("--cached")
        return self.repo.git.diff()

    def diff_against(self, ref: str) -> str:
        return self.repo.git.diff(ref)

    def status(self) -> str:
        return self.repo.git.status("--short")

    def changed_files(self) -> list[str]:
        out = self.repo.git.status("--short")
        return [ln[3:].strip() for ln in out.splitlines() if ln.strip()]

    def add_all(self) -> None:
        self.repo.git.add("--all")

    def commit(self, message: str, author_name: str = "AI Dev Agent",
               author_email: str = "ai-dev-agent@example.com") -> str:
        self.repo.git.add("--all")
        env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
        with self.repo.git.custom_environment(**env):
            self.repo.git.commit("-m", message)
        return self.repo.head.commit.hexsha

    def push(self, branch: str, authed_url: str | None = None, remote: str = "origin") -> None:
        if authed_url:
            self.repo.git.push(authed_url, f"HEAD:refs/heads/{branch}")
        else:
            self.repo.git.push("--set-upstream", remote, branch)


# --- read-only tools for agents ------------------------------------- #
def git_diff(ctx: ToolContext) -> dict[str, Any]:
    try:
        repo = GitRepo(ctx.root)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Not a git repo: {exc}"}
    diff = repo.diff() or "(no unstaged changes)"
    return {"diff": diff[:30_000], "summary": f"{len(repo.changed_files())} file(s) changed"}


def git_status(ctx: ToolContext) -> dict[str, Any]:
    try:
        repo = GitRepo(ctx.root)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Not a git repo: {exc}"}
    return {"status": repo.status() or "(clean)", "changed_files": repo.changed_files()}


def register(registry: ToolRegistry) -> None:
    registry.add(
        "git_diff",
        "Show the current uncommitted diff in the workspace (read-only).",
        {"type": "object", "properties": {}},
        git_diff,
    )
    registry.add(
        "git_status",
        "Show short git status and the list of changed files (read-only).",
        {"type": "object", "properties": {}},
        git_status,
    )
