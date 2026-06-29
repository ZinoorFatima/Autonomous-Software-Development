"""Architect agent: turn tasks + repo map into a design and route work to specialists."""
from __future__ import annotations

from typing import Any

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier

_SCHEMA = {
    "type": "object",
    "properties": {
        "design": {"type": "string", "description": "High-level approach, 2-5 sentences"},
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "specialist": {"type": "string", "enum": ["backend", "frontend"]},
                    "instruction": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["specialist", "instruction"],
            },
        },
    },
    "required": ["design", "subtasks"],
}


class ArchitectAgent(Agent):
    name = "Architect"
    tier = ModelTier.PRO
    system = (
        "You are a software architect. Given the issue, the task plan, and a map of relevant files, "
        "produce a brief technical design and break the work into concrete sub-tasks, each routed to "
        "a 'backend' or 'frontend' specialist. Reference real file paths from the repo map. Keep "
        "sub-tasks self-contained so a specialist can execute one without seeing the others."
    )

    def run(
        self, issue_prompt: str, tasks: list[dict[str, Any]], repo_map: dict[str, Any]
    ) -> dict[str, Any]:
        self._start("Designing the solution")
        task_lines = "\n".join(f"- {t['title']}: {t['description']}" for t in tasks)
        files = ", ".join(repo_map.get("relevant_files", [])) or "(none identified)"
        prompt = (
            f"Issue:\n{issue_prompt}\n\nTasks:\n{task_lines}\n\n"
            f"Relevant files: {files}\nRepo notes: {repo_map.get('notes', '')}\n\n"
            "Produce the design and routed sub-tasks."
        )
        result = self.think_json(prompt, schema=_SCHEMA)
        subtasks = result.get("subtasks", [])
        self.emit("design", result.get("design", ""), subtasks=subtasks)
        self._finish(f"{len(subtasks)} sub-task(s) routed")
        return result
