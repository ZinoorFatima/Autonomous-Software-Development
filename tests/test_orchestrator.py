"""Orchestrator wiring test using fake Gemini + fake GitHub (no network)."""
from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

from agent.events import EventBus
from agent.integrations.github import IssueInfo
from agent.llm.gemini import ModelTier, ToolCall, ToolLoopResult
from agent.orchestrator import Orchestrator, RunConfig
from agent.tools.git_tools import GitRepo


class FakeGemini:
    """Returns canned responses keyed off the JSON schema / prompt content."""

    def model_name(self, tier: ModelTier) -> str:
        return tier.value

    def generate_json(self, prompt, *, tier=ModelTier.PRO, system=None, schema=None, temperature=0.1):
        props = (schema or {}).get("properties", {})
        if "tasks" in props:
            return {"summary": "plan summary", "tasks": [{"title": "Add feature", "description": "implement feature"}]}
        if "subtasks" in props:
            return {"design": "simple design", "subtasks": [
                {"specialist": "backend", "instruction": "create feature.py", "files": ["app.py"]}]}
        if "findings" in props:
            return {"findings": [], "verdict": "looks fine"}
        if "title" in props:
            return {"title": "Fix #1: Add feature", "body": "## Summary\nDid the thing."}
        return {}

    def generate_text(self, prompt, *, tier=ModelTier.FLASH, system=None, temperature=0.2):
        return ""

    def run_tool_loop(self, prompt, *, tools, executor, tier=ModelTier.FLASH, system=None,
                      temperature=0.2, max_iterations=25):
        if "identify the relevant files" in prompt.lower():
            return ToolLoopResult(final_text='{"relevant_files": ["app.py"], "notes": "flat repo"}',
                                  tool_calls=[], iterations=1)
        # coding / debug agent: actually write a file through the executor
        executor(ToolCall(name="write_file", args={"path": "feature.py", "content": "VALUE = 42\n"}))
        return ToolLoopResult(final_text="wrote feature.py", tool_calls=[], iterations=1)


class FakeGitHub:
    def __init__(self, remote_path: Path, default_branch: str, can_push_flag: bool = True) -> None:
        self.remote_path = remote_path
        self._default = default_branch
        self._can_push = can_push_flag
        self.opened = None
        self.opened_repo = None
        self.opened_head = None

    def get_issue(self, repo, number):
        return IssueInfo(number=number, title="Add feature", body="Please add a feature.",
                         labels=[], url="https://example.com/issue/1")

    def default_branch(self, repo):
        return self._default

    def login(self):
        return "ZinoorFatima"

    def can_push(self, repo):
        return self._can_push

    def ensure_fork(self, repo):
        return "ZinoorFatima/" + repo.split("/")[-1]

    def authed_clone_url(self, repo):
        return str(self.remote_path)

    def open_pull_request(self, repo, *, head, base, title, body):
        self.opened = {"number": 7, "url": "https://example.com/pr/7", "title": title}
        self.opened_repo = repo
        self.opened_head = head
        return self.opened


@pytest.fixture
def remote_repo(tmp_path: Path) -> tuple[Path, str]:
    rp = tmp_path / "remote"
    rp.mkdir()
    Repo.init(str(rp))
    (rp / "app.py").write_text("# app\n", encoding="utf-8")
    g = GitRepo(rp)
    g.commit("initial", author_name="t", author_email="t@e.com")
    return rp, g.current_branch()


def test_pipeline_commits_changes(remote_repo, tmp_path, monkeypatch):
    rp, default_branch = remote_repo
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    # rebuild settings cache so the new workspace root takes effect
    import agent.config as cfg
    cfg._settings = None

    bus = EventBus()
    seen = []
    bus.add_sync_listener(lambda e: seen.append((e.type, e.agent)))

    orch = Orchestrator(
        "testrun",
        RunConfig(repo="owner/name", issue_number=1, run_tests=False, open_pr=False),
        bus=bus,
        gemini=FakeGemini(),
        github=FakeGitHub(rp, default_branch),
    )
    result = orch.run()

    assert result.status == "success", result.message
    assert result.branch == "ai-dev-agent/issue-1"
    # the coding agent's file made it into the workspace and was committed
    ws_repo = GitRepo(orch.workspace.path)
    assert (orch.workspace.path / "feature.py").exists()
    assert ws_repo.current_branch() == "ai-dev-agent/issue-1"
    # the expected specialist agents ran
    agents_started = {a for t, a in seen if t == "agent_started"}
    assert {"Planning", "RepoAnalysis", "Architect", "Backend", "Review", "Security"} <= agents_started


def test_pipeline_opens_pr(remote_repo, tmp_path, monkeypatch):
    rp, default_branch = remote_repo
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws2"))
    import agent.config as cfg
    cfg._settings = None

    gh = FakeGitHub(rp, default_branch)
    # open_pr=True but pushing to a non-bare local repo fails; patch push to a no-op
    monkeypatch.setattr(GitRepo, "push", lambda self, *a, **k: None)

    orch = Orchestrator(
        "testrun2",
        RunConfig(repo="owner/name", issue_number=1, run_tests=False, open_pr=True),
        gemini=FakeGemini(),
        github=gh,
    )
    result = orch.run()
    assert result.status == "success", result.message
    assert result.mode == "direct"
    assert result.pr_url == "https://example.com/pr/7"
    assert gh.opened["title"].startswith("Fix #1")
    assert gh.opened_repo == "owner/name"
    assert gh.opened_head == "ai-dev-agent/issue-1"


def test_fork_mode_opens_pr_on_fork(remote_repo, tmp_path, monkeypatch):
    """No push access → fork the repo and (by default) open the PR on the fork."""
    rp, default_branch = remote_repo
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsfork"))
    import agent.config as cfg
    cfg._settings = None

    gh = FakeGitHub(rp, default_branch, can_push_flag=False)
    monkeypatch.setattr(GitRepo, "push", lambda self, *a, **k: None)

    orch = Orchestrator(
        "forkrun",
        RunConfig(repo="someone/proj", issue_number=1, run_tests=False, open_pr=True),
        gemini=FakeGemini(),
        github=gh,
    )
    result = orch.run()
    assert result.status == "success", result.message
    assert result.mode == "fork"
    assert result.fork == "ZinoorFatima/proj"
    # stop-at-fork default: PR opened on the fork, not upstream
    assert gh.opened_repo == "ZinoorFatima/proj"
    assert gh.opened_head == "ai-dev-agent/issue-1"


def test_fork_mode_upstream_pr(remote_repo, tmp_path, monkeypatch):
    """upstream_pr=True → cross-repo PR on upstream with 'forkowner:branch' head."""
    rp, default_branch = remote_repo
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "wsup"))
    import agent.config as cfg
    cfg._settings = None

    gh = FakeGitHub(rp, default_branch, can_push_flag=False)
    monkeypatch.setattr(GitRepo, "push", lambda self, *a, **k: None)

    orch = Orchestrator(
        "uprun",
        RunConfig(repo="someone/proj", issue_number=1, run_tests=False, open_pr=True,
                  upstream_pr=True),
        gemini=FakeGemini(),
        github=gh,
    )
    result = orch.run()
    assert result.status == "success", result.message
    assert gh.opened_repo == "someone/proj"
    assert gh.opened_head == "ZinoorFatima:ai-dev-agent/issue-1"
