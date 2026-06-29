"""Tool registry — the bridge between Gemini function-calling and real actions.

Each tool is a `ToolSpec` (name, description, JSON-schema parameters, handler).
`ToolRegistry.declarations()` produces the function-declaration dicts handed to
Gemini; `ToolRegistry.execute()` runs a `ToolCall` by dispatching to the handler.

Every handler receives a `ToolContext`, which carries the workspace root (so all
file/shell operations are sandboxed to a single run) and an optional event hook.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.config import Settings, get_settings
from agent.events import Event, EventBus
from agent.llm.gemini import ToolCall


@dataclass
class ToolContext:
    """Everything a tool handler needs, scoped to one run."""

    root: Path
    settings: Settings = field(default_factory=get_settings)
    bus: EventBus | None = None
    run_id: str = ""

    def safe_path(self, relative: str) -> Path:
        """Resolve `relative` inside the workspace, rejecting path traversal."""
        candidate = (self.root / relative).resolve()
        root_resolved = self.root.resolve()
        if candidate != root_resolved and root_resolved not in candidate.parents:
            raise ValueError(
                f"Path '{relative}' escapes the workspace sandbox ({self.root})."
            )
        return candidate

    def log(self, message: str, agent: str | None = None, **data: Any) -> None:
        if self.bus is not None:
            self.bus.emit(
                Event(run_id=self.run_id, type="log", message=message, agent=agent, data=data)
            )


ToolHandler = Callable[..., dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def add(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        self.register(ToolSpec(name, description, parameters, handler))

    def names(self) -> list[str]:
        return list(self._tools)

    def subset(self, names: list[str]) -> "ToolRegistry":
        """A new registry exposing only `names` (same context). Lets each agent
        see only the tools relevant to its role."""
        r = ToolRegistry(self.ctx)
        for n in names:
            if n in self._tools:
                r.register(self._tools[n])
        return r

    def declarations(self) -> list[dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in self._tools.values()
        ]

    def execute(self, call: ToolCall) -> dict[str, Any]:
        spec = self._tools.get(call.name)
        if spec is None:
            return {"error": f"Unknown tool '{call.name}'. Available: {self.names()}"}
        if self.ctx.bus is not None:
            self.ctx.bus.emit(
                Event(
                    run_id=self.ctx.run_id,
                    type="tool_call",
                    message=call.name,
                    data={"args": call.args},
                )
            )
        try:
            result = spec.handler(self.ctx, **call.args)
        except TypeError as exc:
            return {"error": f"Bad arguments for '{call.name}': {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        if self.ctx.bus is not None:
            preview = result.get("error") or result.get("summary") or "ok"
            self.ctx.bus.emit(
                Event(
                    run_id=self.ctx.run_id,
                    type="tool_result",
                    message=f"{call.name}: {preview}",
                    data={"result_keys": list(result.keys())},
                )
            )
        return result
