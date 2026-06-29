"""Checkpoint controllers — the human-in-the-loop approval gates.

The orchestrator calls `controller.request(stage, data)` at each gate. The call
blocks until a decision is available:

- `AutoCheckpointController` approves immediately (autonomy = auto).
- `TerminalCheckpointController` prompts on the CLI.
- `WebCheckpointController` emits a `checkpoint` event and blocks on a
  threading.Event that the web layer sets via `resolve()`.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from agent.events import Event, EventBus


@dataclass
class Decision:
    approved: bool
    feedback: str = ""


class CheckpointController:
    def request(self, stage: str, message: str, data: dict[str, Any] | None = None) -> Decision:
        raise NotImplementedError


class AutoCheckpointController(CheckpointController):
    def request(self, stage: str, message: str, data: dict[str, Any] | None = None) -> Decision:
        return Decision(approved=True)


class TerminalCheckpointController(CheckpointController):
    def request(self, stage: str, message: str, data: dict[str, Any] | None = None) -> Decision:
        print(f"\n=== CHECKPOINT [{stage}] ===\n{message}")
        try:
            answer = input("Approve? [Y/n] ").strip().lower()
        except EOFError:
            answer = "y"
        if answer in ("", "y", "yes"):
            return Decision(approved=True)
        return Decision(approved=False, feedback="rejected at terminal")


@dataclass
class _Pending:
    stage: str
    event: threading.Event = field(default_factory=threading.Event)
    decision: Decision | None = None


class WebCheckpointController(CheckpointController):
    """Blocks the orchestrator thread until the browser approves/rejects."""

    def __init__(self, bus: EventBus, run_id: str) -> None:
        self._bus = bus
        self._run_id = run_id
        self._pending: _Pending | None = None
        self._lock = threading.Lock()

    def request(self, stage: str, message: str, data: dict[str, Any] | None = None) -> Decision:
        pending = _Pending(stage=stage)
        with self._lock:
            self._pending = pending
        self._bus.emit(
            Event(run_id=self._run_id, type="checkpoint", message=message,
                  data={"stage": stage, **(data or {})})
        )
        pending.event.wait()  # block until resolve()
        with self._lock:
            self._pending = None
        return pending.decision or Decision(approved=True)

    def resolve(self, approved: bool, feedback: str = "") -> bool:
        with self._lock:
            pending = self._pending
        if pending is None:
            return False
        pending.decision = Decision(approved=approved, feedback=feedback)
        pending.event.set()
        return True

    @property
    def pending_stage(self) -> str | None:
        return self._pending.stage if self._pending else None
