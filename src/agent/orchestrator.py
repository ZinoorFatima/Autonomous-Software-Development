"""Orchestrator — the state machine that drives the whole pipeline.

It runs synchronously (so it can live in a worker thread under the web server) and
reports every step through the EventBus. Human-in-the-loop gates are delegated to a
CheckpointController.

Pipeline:
    setup → Planning ─[plan gate]→ RepoAnalysis → Architect → Backend/Frontend
          → Testing ⇄ Debug(loop) → Review + Security
          ─[commit gate]→ commit → PR draft ─[pr gate]→ push + open PR
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any

from agent.agents import (
    ArchitectAgent,
    BackendAgent,
    DebugAgent,
    FrontendAgent,
    PlanningAgent,
    PullRequestAgent,
    RepoAnalysisAgent,
    ReviewAgent,
    SecurityAgent,
    TestingAgent,
)
from agent.checkpoints import AutoCheckpointController, CheckpointController
from agent.config import Autonomy, get_settings
from agent.events import Event, EventBus
from agent.integrations.github import GitHubClient, normalize_repo
from agent.integrations.workspace import Workspace
from agent.llm.gemini import GeminiClient
from agent.tools import build_registry
from agent.tools.registry import ToolContext


@dataclass
class RunConfig:
    repo: str
    issue_number: int
    base_branch: str | None = None
    run_tests: bool = True
    open_pr: bool = True
    # When the token can't push to `repo`, fork it and contribute from the fork.
    # By default the PR is opened on YOUR fork only; the upstream PR opens only
    # when upstream_pr is True (respects maintainer norms / your explicit intent).
    upstream_pr: bool = False


@dataclass
class RunResult:
    run_id: str
    status: str = "pending"  # pending | success | rejected | error
    branch: str | None = None
    pr_url: str | None = None
    test_summary: str | None = None
    mode: str = "direct"  # direct | fork
    fork: str | None = None
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        run_id: str,
        config: RunConfig,
        bus: EventBus | None = None,
        checkpoints: CheckpointController | None = None,
        gemini: GeminiClient | None = None,
        github: GitHubClient | None = None,
    ) -> None:
        self.run_id = run_id
        self.config = config
        self.bus = bus or EventBus()
        self.settings = get_settings()
        self.checkpoints = checkpoints or AutoCheckpointController()
        self.gemini = gemini
        self.github = github
        self.workspace: Workspace | None = None

    # -- helpers ------------------------------------------------------ #
    def emit(self, type_: str, message: str = "", **data: Any) -> None:
        self.bus.emit(Event(run_id=self.run_id, type=type_, message=message, data=data))

    def _gate(self, stage: str, message: str, **data: Any) -> bool:
        if self.settings.autonomy == Autonomy.AUTO:
            return True
        decision = self.checkpoints.request(stage, message, data)
        self.emit("checkpoint_resolved", f"{stage}: {'approved' if decision.approved else 'rejected'}",
                  stage=stage, approved=decision.approved)
        return decision.approved

    # -- main --------------------------------------------------------- #
    def run(self) -> RunResult:
        result = RunResult(run_id=self.run_id)
        try:
            self._run(result)
        except Exception as exc:  # noqa: BLE001
            result.status = "error"
            result.message = f"{type(exc).__name__}: {exc}"
            self.emit("error", result.message, traceback=traceback.format_exc())
        finally:
            usage = getattr(self.gemini, "usage", None)
            if usage:
                result.detail["usage"] = usage
                self.emit("usage", f"{usage['total_tokens']} tokens across {usage['calls']} calls",
                          **usage)
            self.emit("run_finished", result.message or result.status,
                      status=result.status, pr_url=result.pr_url, branch=result.branch)
        return result

    def _run(self, result: RunResult) -> None:
        self.gemini = self.gemini or GeminiClient()
        self.github = self.github or GitHubClient()
        cfg = self.config

        # 1) Setup -----------------------------------------------------
        self.emit("stage", "Setup: reading issue and cloning repo")
        issue = self.github.get_issue(cfg.repo, cfg.issue_number)
        issue_prompt = issue.as_prompt()
        base_branch = cfg.base_branch or self.github.default_branch(cfg.repo)
        self.emit("issue", issue.title, number=issue.number, url=issue.url)

        # Decide contribution mode: push directly, or fork-and-PR if we lack access.
        if self.github.can_push(cfg.repo):
            mode = "direct"
            clone_repo = normalize_repo(cfg.repo)
            head_prefix = ""
        else:
            self.emit("stage", "No push access to the repo — forking it to your account")
            clone_repo = self.github.ensure_fork(cfg.repo)
            mode = "fork"
            head_prefix = clone_repo.split("/")[0] + ":"
            self.emit("fork", f"Forked to {clone_repo}", fork=clone_repo)
        result.mode = mode
        result.fork = clone_repo if mode == "fork" else None

        self.workspace = Workspace(self.run_id)
        git = self.workspace.clone(self.github.authed_clone_url(clone_repo))
        branch = f"ai-dev-agent/issue-{cfg.issue_number}"
        git.create_branch(branch)
        result.branch = branch

        ctx = ToolContext(root=self.workspace.path, settings=self.settings, bus=self.bus, run_id=self.run_id)
        registry = build_registry(ctx)

        def make(agent_cls):
            return agent_cls(self.gemini, registry, self.bus, self.run_id)

        # 2) Planning + gate ------------------------------------------
        plan = make(PlanningAgent).run(issue_prompt)
        tasks = plan.get("tasks", [])
        if not self._gate("plan", plan.get("summary", "Review the plan"), tasks=tasks):
            result.status = "rejected"
            result.message = "Plan rejected by user."
            return

        # 3) Repo analysis --------------------------------------------
        repo_map = make(RepoAnalysisAgent).run(issue_prompt, tasks)

        # 4) Architect ------------------------------------------------
        design = make(ArchitectAgent).run(issue_prompt, tasks, repo_map)
        subtasks = design.get("subtasks") or [
            {"specialist": "backend", "instruction": t["description"], "files": repo_map.get("relevant_files", [])}
            for t in tasks
        ]

        # 5) Implement (route to specialists) -------------------------
        backend = make(BackendAgent)
        frontend = make(FrontendAgent)
        for st in subtasks:
            agent = frontend if st.get("specialist") == "frontend" else backend
            agent.implement(issue_prompt, st["instruction"], st.get("files", []))

        # 6) Test + debug loop ----------------------------------------
        if cfg.run_tests:
            self.emit("stage", "Preparing workspace venv and installing dependencies")
            install_notes = self.workspace.install_deps()
            self.emit("log", "dependency install: " + ", ".join(install_notes))
            test_plan = self.workspace.detect_test_plan()
            test_argv = test_plan.test_argv
            tester = make(TestingAgent)
            test = tester.run(test_argv)
            attempt = 0
            while not test.passed and attempt < self.settings.max_debug_retries:
                attempt += 1
                make(DebugAgent).run(issue_prompt, test.output, attempt)
                test = tester.run(test_argv)
            result.test_summary = test.short
            if not test.passed:
                self.emit("warning", f"Tests still failing after {attempt} debug attempt(s): {test.short}")
        else:
            result.test_summary = "skipped"

        # 7) Review + Security ----------------------------------------
        diff = git.diff() or git.diff(staged=True)
        if not diff.strip():
            git.add_all()
            diff = git.diff(staged=True)
        review = make(ReviewAgent).run(issue_prompt, diff)
        security = make(SecurityAgent).run(issue_prompt, diff)

        if not git.changed_files() and not diff.strip():
            result.status = "error"
            result.message = "No code changes were produced."
            return

        # 8) Commit gate ----------------------------------------------
        if not self._gate("commit", "Approve committing these changes?",
                           changed_files=git.changed_files(), diff=diff[:6000]):
            result.status = "rejected"
            result.message = "Commit rejected by user."
            return
        commit_msg = f"Fix #{cfg.issue_number}: {issue.title}"
        sha = git.commit(commit_msg)
        self.emit("commit", commit_msg, sha=sha)

        # 9) PR draft + gate + open -----------------------------------
        if not cfg.open_pr:
            result.status = "success"
            result.message = f"Committed {sha[:8]} to {branch} (PR creation skipped)."
            return

        pr = make(PullRequestAgent).run(
            issue_prompt, plan.get("summary", ""), diff, result.test_summary or "",
            review.get("verdict", ""), security.get("verdict", ""),
        )
        # Describe where the PR will land so the approval is informed.
        if mode == "direct":
            pr_target_desc = f"open a PR on {clone_repo} ({branch} → {base_branch})"
        elif cfg.upstream_pr:
            pr_target_desc = f"open an UPSTREAM PR on {normalize_repo(cfg.repo)} (from your fork {clone_repo})"
        else:
            pr_target_desc = f"open a PR on your fork {clone_repo} (upstream PR withheld)"

        if not self._gate("pr", f"Approve: {pr_target_desc}?",
                          title=pr["title"], body=pr["body"], mode=mode, fork=result.fork):
            result.status = "rejected"
            result.message = f"PR rejected. Changes committed to {branch}."
            return

        # Push to whichever repo we cloned (upstream in direct mode, the fork otherwise).
        git.push(branch, authed_url=self.github.authed_clone_url(clone_repo))

        if mode == "direct":
            opened = self.github.open_pull_request(
                clone_repo, head=branch, base=base_branch, title=pr["title"], body=pr["body"])
            result.message = f"Opened PR: {opened['url']}"
        elif cfg.upstream_pr:
            opened = self.github.open_pull_request(
                normalize_repo(cfg.repo), head=f"{head_prefix}{branch}", base=base_branch,
                title=pr["title"], body=pr["body"])
            result.message = f"Opened upstream PR from fork: {opened['url']}"
        else:
            fork_base = self.github.default_branch(clone_repo)
            opened = self.github.open_pull_request(
                clone_repo, head=branch, base=fork_base, title=pr["title"], body=pr["body"])
            result.message = (
                f"Pushed to fork and opened a review PR on {clone_repo}: {opened['url']}. "
                f"Re-run with upstream_pr=True to propose it to {normalize_repo(cfg.repo)}.")

        result.pr_url = opened["url"]
        result.status = "success"
        self.emit("pull_request", opened["title"], url=opened["url"], number=opened["number"])
