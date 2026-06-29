"""Testing agent: run the test suite through the sandbox and parse the result."""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier
from agent.tools.shell import execute_argv


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class
    passed: bool
    exit_code: int
    summary: str
    output: str

    @property
    def short(self) -> str:
        return self.summary or ("passed" if self.passed else f"failed (exit {self.exit_code})")


_SUMMARY_RE = re.compile(r"(\d+ (?:passed|failed|error|skipped)[^\n]*)", re.IGNORECASE)


class TestingAgent(Agent):
    __test__ = False  # not a pytest test class
    name = "Testing"
    tier = ModelTier.FLASH

    def run(self, test_argv: list[str]) -> TestResult:
        """Execute the test command (argv list) inside the sandboxed workspace."""
        label = " ".join(test_argv[2:]) if len(test_argv) > 2 else "tests"
        self._start(f"Running tests: {label}")
        result = execute_argv(self.registry.ctx.root, test_argv, timeout=600)
        if "error" in result:
            self._finish(f"could not run tests: {result['error']}")
            return TestResult(False, -1, result["error"], result["error"])

        exit_code = result.get("exit_code", -1)
        output = (result.get("stdout", "") + "\n" + result.get("stderr", "")).strip()
        passed = exit_code == 0
        m = _SUMMARY_RE.findall(output)
        summary = m[-1] if m else ("all tests passed" if passed else "tests failed")
        self.emit("test_result", summary, passed=passed, exit_code=exit_code)
        self._finish(summary)
        return TestResult(passed, exit_code, summary, output)
