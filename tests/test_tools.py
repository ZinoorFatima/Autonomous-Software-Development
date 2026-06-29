"""Unit tests for the sandboxed tool layer (no Gemini / GitHub needed)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.llm.gemini import ToolCall
from agent.tools import build_registry
from agent.tools.registry import ToolContext


@pytest.fixture
def ws(tmp_path: Path) -> ToolContext:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    return ToolContext(root=tmp_path, run_id="test")


@pytest.fixture
def registry(ws: ToolContext):
    return build_registry(ws)


def call(registry, name, **args):
    return registry.execute(ToolCall(name=name, args=args))


def test_read_file(registry):
    res = call(registry, "read_file", path="src/app.py")
    assert "def add" in res["content"]


def test_write_and_read(registry):
    call(registry, "write_file", path="src/new.py", content="x = 1\n")
    res = call(registry, "read_file", path="src/new.py")
    assert res["content"] == "x = 1\n"


def test_edit_file_unique(registry):
    res = call(registry, "edit_file", path="src/app.py",
               old_string="a + b", new_string="a + b + 0")
    assert res["replacements"] == 1
    assert "a + b + 0" in call(registry, "read_file", path="src/app.py")["content"]


def test_edit_file_missing_anchor(registry):
    res = call(registry, "edit_file", path="src/app.py",
               old_string="nonexistent", new_string="x")
    assert "error" in res


def test_list_dir(registry):
    res = call(registry, "list_dir", path=".")
    assert "src/app.py" in res["tree"]


def test_search_code(registry):
    res = call(registry, "search_code", pattern="def add", glob="*.py")
    assert res["count"] >= 1
    assert any("app.py" in m for m in res["matches"])


def test_path_traversal_blocked(registry):
    res = call(registry, "read_file", path="../../../etc/passwd")
    assert "error" in res
    assert "escapes" in res["error"]


def test_run_command_allowed(registry):
    res = call(registry, "run_command", command="echo hello")
    assert res["exit_code"] == 0


def test_run_command_blocked(registry):
    res = call(registry, "run_command", command="rm -rf /")
    assert "error" in res
    assert "not allowlisted" in res["error"]


def test_unknown_tool(registry):
    res = registry.execute(ToolCall(name="does_not_exist", args={}))
    assert "error" in res
