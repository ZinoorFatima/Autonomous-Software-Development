"""Review & Security agents: inspect the diff and report findings (read-only)."""
from __future__ import annotations

from typing import Any

from agent.agents.base import Agent
from agent.llm.gemini import ModelTier

_FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["info", "low", "medium", "high"]},
                    "file": {"type": "string"},
                    "issue": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["severity", "issue"],
            },
        },
        "verdict": {"type": "string", "description": "One-line overall assessment"},
    },
    "required": ["findings", "verdict"],
}


class _DiffReviewer(Agent):
    tier = ModelTier.PRO

    def run(self, issue_prompt: str, diff: str) -> dict[str, Any]:
        self._start(f"{self.name} review")
        if not diff.strip():
            self._finish("no changes to review")
            return {"findings": [], "verdict": "No diff to review."}
        prompt = (
            f"Issue context:\n{issue_prompt}\n\n"
            f"Review this diff:\n```diff\n{diff[:20000]}\n```\n\n"
            "Report concrete findings only (no nitpicks unless they matter)."
        )
        result = self.think_json(prompt, schema=_FINDINGS_SCHEMA)
        findings = result.get("findings", [])
        self.emit(f"{self.name.lower()}_findings", result.get("verdict", ""), findings=findings)
        self._finish(f"{len(findings)} finding(s)")
        return result


class ReviewAgent(_DiffReviewer):
    name = "Review"
    system = (
        "You are a code reviewer. Inspect the diff for correctness bugs, code style, duplication, "
        "performance issues, and missing tests. Be specific and reference files."
    )


class SecurityAgent(_DiffReviewer):
    name = "Security"
    system = (
        "You are a security reviewer. Inspect the diff for security issues: injection, secrets in "
        "code, missing authz, unsafe deserialization, token/expiry handling, path traversal, and "
        "similar. Flag only real risks, with severity."
    )
