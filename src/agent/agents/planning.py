"""Planning agent: turn an issue into an ordered task list."""
from __future__ import annotations

from typing import Any

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "description"],
            },
        },
    },
    "required": ["summary", "tasks"],
}


class PlanningAgent(Agent):
    name = "Planning"
    tier = ModelTier.PRO
    system = (
        "You are a senior software planning agent. Given a GitHub issue, produce a concise, "
        "ordered list of concrete engineering tasks to resolve it. Tasks should be specific and "
        "actionable (e.g. 'Add reset-token model field', not 'work on backend'). Keep it minimal "
        "— only what the issue needs. Always include a task for adding/updating tests."
    )

    def run(self, issue_prompt: str) -> dict[str, Any]:
        self._start("Planning tasks from the issue")
        result = self.think_json(
            f"Create an implementation plan for this issue:\n\n{issue_prompt}", schema=_SCHEMA
        )
        tasks = result.get("tasks", [])
        self.emit("plan", result.get("summary", ""), tasks=tasks)
        self._finish(f"{len(tasks)} task(s) planned")
        return result
