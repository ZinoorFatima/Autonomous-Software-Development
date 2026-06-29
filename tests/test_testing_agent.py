"""TestingAgent parses command results deterministically."""
from __future__ import annotations

from pathlib import Path

from agent.agents.testing import TestingAgent
from agent.tools import build_registry
from agent.tools.registry import ToolContext


def _agent(tmp_path: Path) -> TestingAgent:
    ctx = ToolContext(root=tmp_path, run_id="t")
    return TestingAgent(gemini=None, registry=build_registry(ctx), bus=None, run_id="t")


def test_passing_command(tmp_path: Path):
    res = _agent(tmp_path).run(["echo", "all", "good"])
    assert res.passed is True
    assert res.exit_code == 0


def test_blocked_command_reports_error(tmp_path: Path):
    res = _agent(tmp_path).run(["rm", "-rf", "/"])
    assert res.passed is False
