"""Repo analysis agent: explore the codebase and identify relevant files."""
from __future__ import annotations

from typing import Any

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier
from agent.tools import READ_TOOLS
from agent.util import parse_json_loose


class RepoAnalysisAgent(Agent):
    name = "RepoAnalysis"
    tier = ModelTier.FLASH
    tool_names = READ_TOOLS
    system = (
        "You are a code-navigation agent. Use the read-only tools (list_dir, read_file, "
        "search_code) to explore the repository and find the files relevant to the given tasks. "
        "Be efficient: scan the tree, search for key symbols, open only what matters. "
        "When done, reply with ONLY a JSON object: "
        '{"relevant_files": ["path", ...], "notes": "1-3 sentences on structure & where to make changes"}.'
    )

    def run(self, issue_prompt: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        self._start("Mapping the repository")
        task_lines = "\n".join(f"- {t['title']}: {t['description']}" for t in tasks)
        prompt = (
            f"Issue:\n{issue_prompt}\n\nPlanned tasks:\n{task_lines}\n\n"
            "Explore the repo and identify the relevant files."
        )
        result = self.act(prompt, max_iterations=20)
        try:
            data = parse_json_loose(result.final_text)
        except ValueError:
            data = {"relevant_files": [], "notes": result.final_text[:500]}
        files = data.get("relevant_files", [])
        self.emit("repo_map", data.get("notes", ""), relevant_files=files)
        self._finish(f"{len(files)} relevant file(s) found")
        return data
