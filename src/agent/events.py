"""Event bus — the single channel through which the pipeline reports progress.

The orchestrator and agents `emit()` events; consumers subscribe:
- the **CLI** registers a synchronous callback that pretty-prints events;
- the **web layer** subscribes an `asyncio.Queue` per WebSocket client.

`emit()` is thread-safe so the orchestrator can run in a worker thread while the
asyncio web server streams events to browsers.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class Event:
    run_id: str
    type: str  # agent_started | agent_finished | log | tool_call | tool_result | checkpoint | run_finished | error
    message: str = ""
    agent: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SyncListener = Callable[[Event], None]


class EventBus:
    """Fan-out bus with replayable history, sync callbacks, and async queues."""

    def __init__(self) -> None:
        self._history: list[Event] = []
        self._sync_listeners: list[SyncListener] = []
        self._queues: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- lifecycle ---------------------------------------------------- #
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Associate the asyncio loop so cross-thread emits can reach queues."""
        self._loop = loop

    # -- producers ---------------------------------------------------- #
    def emit(self, event: Event) -> None:
        self._history.append(event)
        for listener in list(self._sync_listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - a bad listener must not kill the run
                pass
        for q in list(self._queues):
            self._push(q, event)

    def _push(self, q: "asyncio.Queue[Event]", event: Event) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(q.put_nowait, event)
        else:
            try:
                q.put_nowait(event)
            except RuntimeError:
                pass

    # -- consumers ---------------------------------------------------- #
    def add_sync_listener(self, listener: SyncListener) -> None:
        self._sync_listeners.append(listener)

    def subscribe(self, replay: bool = True) -> "asyncio.Queue[Event]":
        q: asyncio.Queue[Event] = asyncio.Queue()
        if replay:
            for event in self._history:
                q.put_nowait(event)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[Event]") -> None:
        self._queues.discard(q)

    @property
    def history(self) -> list[Event]:
        return list(self._history)
