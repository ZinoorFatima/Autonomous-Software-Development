"""Base class shared by every specialist agent.

An agent bundles: a name, a model tier, a system prompt, and the subset of tools
it is allowed to use. It offers two execution helpers:

- `act()`  — run a tool-calling loop (for agents that change the workspace);
- `think_json()` — get a structured JSON answer (for planners/reviewers).

Both emit `agent_started` / `agent_finished` events so the dashboard can show a
live timeline.
"""
from __future__ import annotations

from typing import Any

from agent.events import Event, EventBus
from agent.llm.gemini import GeminiClient, ModelTier, ToolLoopResult
from agent.tools.registry import ToolRegistry


class Agent:
    name: str = "agent"
    tier: ModelTier = ModelTier.FLASH
    system: str = ""
    tool_names: list[str] = []

    def __init__(
        self,
        gemini: GeminiClient,
        registry: ToolRegistry,
        bus: EventBus | None = None,
        run_id: str = "",
    ) -> None:
        self.gemini = gemini
        self.registry = registry
        self.bus = bus
        self.run_id = run_id

    # -- events ------------------------------------------------------- #
    def emit(self, type_: str, message: str = "", **data: Any) -> None:
        if self.bus is not None:
            self.bus.emit(
                Event(run_id=self.run_id, type=type_, message=message, agent=self.name, data=data)
            )

    def _start(self, message: str) -> None:
        self.emit("agent_started", message)

    def _finish(self, message: str) -> None:
        self.emit("agent_finished", message)

    # -- execution helpers ------------------------------------------- #
    def act(self, prompt: str, max_iterations: int = 25) -> ToolLoopResult:
        """Run a tool-calling loop with this agent's allowed tools."""
        sub = self.registry.subset(self.tool_names) if self.tool_names else self.registry
        return self.gemini.run_tool_loop(
            prompt,
            tools=sub.declarations(),
            executor=sub.execute,
            tier=self.tier,
            system=self.system,
            max_iterations=max_iterations,
        )

    def think_json(self, prompt: str, schema: dict[str, Any] | None = None) -> Any:
        return self.gemini.generate_json(
            prompt, tier=self.tier, system=self.system, schema=schema
        )

    def think_text(self, prompt: str) -> str:
        return self.gemini.generate_text(prompt, tier=self.tier, system=self.system)
