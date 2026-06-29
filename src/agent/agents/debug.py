"""Debug agent: diagnose failing tests and fix the code (self-correction loop)."""
from __future__ import annotations

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier
from agent.tools import EDIT_TOOLS


class DebugAgent(Agent):
    name = "Debug"
    tier = ModelTier.PRO
    tool_names = EDIT_TOOLS
    system = (
        "You are a debugging agent. You are given failing test output. Find the ROOT CAUSE "
        "(not a surface symptom), then fix the code using the file/shell tools. Read the failing "
        "files and the test before editing. Do not delete or weaken tests to make them pass. "
        "When you believe the fix is complete, reply with a short explanation of the root cause "
        "and the fix."
    )

    def run(self, issue_prompt: str, test_output: str, attempt: int) -> str:
        self._start(f"Debugging failing tests (attempt {attempt})")
        prompt = (
            f"Original issue:\n{issue_prompt}\n\n"
            f"The test suite is failing. Output:\n```\n{test_output[:8000]}\n```\n\n"
            "Diagnose the root cause and fix the code."
        )
        result = self.act(prompt, max_iterations=40)
        self._finish(f"fix attempt {attempt} done")
        return result.final_text
