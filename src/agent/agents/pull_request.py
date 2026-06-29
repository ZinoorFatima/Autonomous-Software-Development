"""PR agent: write the pull-request title and body."""
from __future__ import annotations

from typing import Any

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier

_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string", "description": "Markdown PR description"},
    },
    "required": ["title", "body"],
}


class PullRequestAgent(Agent):
    name = "PullRequest"
    tier = ModelTier.FLASH
    system = (
        "You write clear, professional pull-request descriptions. Use sections: Summary, Changes "
        "(bulleted), Testing. Keep it factual and based only on what was actually done. The title "
        "should be a concise conventional-commit-style summary."
    )

    def run(
        self,
        issue_prompt: str,
        plan_summary: str,
        diff: str,
        test_summary: str,
        review_verdict: str,
        security_verdict: str,
    ) -> dict[str, Any]:
        self._start("Drafting the pull request")
        prompt = (
            f"Issue:\n{issue_prompt}\n\n"
            f"Plan: {plan_summary}\n"
            f"Test status: {test_summary}\n"
            f"Review: {review_verdict}\nSecurity: {security_verdict}\n\n"
            f"Diff:\n```diff\n{diff[:15000]}\n```\n\n"
            "Write the PR title and body."
        )
        result = self.think_json(prompt, schema=_SCHEMA)
        self._finish("PR description ready")
        return result
