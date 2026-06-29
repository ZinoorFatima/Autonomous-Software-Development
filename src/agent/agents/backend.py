"""Backend & Frontend coding agents — they actually change the workspace via tools."""
from __future__ import annotations

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier
from agent.tools import EDIT_TOOLS


class CodingAgent(Agent):
    """Shared implementation loop for specialists that edit code."""

    tier = ModelTier.FLASH
    tool_names = EDIT_TOOLS

    def implement(self, issue_prompt: str, instruction: str, files: list[str]) -> str:
        self._start(instruction[:80])
        hint = f"\nLikely files: {', '.join(files)}" if files else ""
        prompt = (
            f"Original issue:\n{issue_prompt}\n\n"
            f"Your sub-task:\n{instruction}{hint}\n\n"
            "Implement this now. Read files before editing them, prefer edit_file for "
            "targeted changes, and write clean code that matches the surrounding style. "
            "Do NOT run the test suite — a separate agent does that. "
            "When finished, reply with a one-paragraph summary of what you changed."
        )
        result = self.act(prompt, max_iterations=40)
        self._finish(f"done ({len(result.tool_calls)} tool calls)")
        return result.final_text


class BackendAgent(CodingAgent):
    name = "Backend"
    system = (
        "You are a backend software engineer. You implement server-side code (Python, APIs, "
        "models, services, business logic) to fulfil a sub-task. You have file read/write tools "
        "scoped to the repo (no shell — a separate agent runs tests). Make focused, correct "
        "changes and keep the code idiomatic."
    )


class FrontendAgent(CodingAgent):
    name = "Frontend"
    system = (
        "You are a frontend software engineer. You implement client-side code (templates, JS/TS, "
        "forms, UI) to fulfil a sub-task. You have file read/write tools scoped to the repo (no "
        "shell). Make focused, correct changes consistent with the existing frontend."
    )
