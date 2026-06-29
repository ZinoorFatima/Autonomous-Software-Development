"""Gemini client wrapper.

Wraps the `google-genai` SDK with three capabilities every agent needs:

1. **Tiered model selection** — `ModelTier.PRO` for reasoning-heavy agents,
   `ModelTier.FLASH` for cheap high-volume work.
2. **Structured JSON output** — `generate_json()` forces `application/json`
   responses and parses them.
3. **Manual tool-calling loop** — `run_tool_loop()` exposes function declarations
   to the model and lets a caller-supplied executor run each call, so the
   orchestrator (not the SDK) mediates every tool invocation. This is what makes
   checkpoints, event streaming, and the workspace sandbox possible.

All calls retry with exponential backoff on transient errors.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from google import genai
from google.genai import types

from agent.config import get_settings


class ModelTier(str, Enum):
    PRO = "pro"
    FLASH = "flash"


@dataclass
class ToolCall:
    """A single function call requested by the model."""

    name: str
    args: dict[str, Any]


# A tool executor takes a ToolCall and returns a JSON-serialisable result dict.
ToolExecutor = Callable[[ToolCall], dict[str, Any]]


@dataclass
class ToolLoopResult:
    """Outcome of a tool-calling conversation."""

    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    iterations: int = 0


# Errors worth retrying (rate limits, transient server errors). We match on the
# class name / message to avoid importing private SDK error types.
_RETRYABLE_HINTS = ("rate", "quota", "429", "500", "502", "503", "504", "deadline", "unavailable")


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(h in text for h in _RETRYABLE_HINTS)


def _strip_json_fence(text: str) -> str:
    """Remove ```json ... ``` fences a model sometimes adds despite JSON mime type."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -3]
    return t.strip()


class GeminiClient:
    """Thin, retrying wrapper over `google-genai`."""

    def __init__(self, api_key: str | None = None, max_retries: int = 4) -> None:
        settings = get_settings()
        self._client = genai.Client(api_key=api_key or settings.require_gemini())
        self._model_for = {
            ModelTier.PRO: settings.gemini_model_pro,
            ModelTier.FLASH: settings.gemini_model_flash,
        }
        self._max_retries = max_retries
        self.usage = {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}

    def model_name(self, tier: ModelTier) -> str:
        return self._model_for[tier]

    def _record_usage(self, resp: Any) -> None:
        self.usage["calls"] += 1
        meta = getattr(resp, "usage_metadata", None)
        if meta is None:
            return
        self.usage["prompt_tokens"] += getattr(meta, "prompt_token_count", 0) or 0
        self.usage["output_tokens"] += getattr(meta, "candidates_token_count", 0) or 0
        self.usage["total_tokens"] += getattr(meta, "total_token_count", 0) or 0

    # ------------------------------------------------------------------ #
    # Low-level call with retry
    # ------------------------------------------------------------------ #
    def _generate(self, *, model: str, contents: Any, config: types.GenerateContentConfig):
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                self._record_usage(resp)
                return resp
            except Exception as exc:  # noqa: BLE001 - SDK raises varied types
                last_exc = exc
                if not _is_retryable(exc) or attempt == self._max_retries - 1:
                    raise
                time.sleep(min(2 ** attempt, 16))
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------ #
    # Plain text
    # ------------------------------------------------------------------ #
    def generate_text(
        self,
        prompt: str,
        *,
        tier: ModelTier = ModelTier.FLASH,
        system: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
        )
        resp = self._generate(model=self._model_for[tier], contents=prompt, config=config)
        return resp.text or ""

    # ------------------------------------------------------------------ #
    # Structured JSON
    # ------------------------------------------------------------------ #
    def generate_json(
        self,
        prompt: str,
        *,
        tier: ModelTier = ModelTier.PRO,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> Any:
        """Return parsed JSON. `schema` is an optional JSON-schema dict to constrain output."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
        )
        resp = self._generate(model=self._model_for[tier], contents=prompt, config=config)
        raw = resp.text or ""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return json.loads(_strip_json_fence(raw))

    # ------------------------------------------------------------------ #
    # Tool-calling loop (manual, orchestrator-mediated)
    # ------------------------------------------------------------------ #
    def run_tool_loop(
        self,
        prompt: str,
        *,
        tools: list[dict[str, Any]],
        executor: ToolExecutor,
        tier: ModelTier = ModelTier.FLASH,
        system: str | None = None,
        temperature: float = 0.2,
        max_iterations: int = 25,
    ) -> ToolLoopResult:
        """Drive a conversation where the model may call `tools` repeatedly.

        `tools` is a list of function-declaration dicts:
            {"name": ..., "description": ..., "parameters": {<json schema>}}
        `executor` runs one ToolCall and returns a JSON-serialisable result.
        The loop ends when the model replies with text instead of a function call,
        or `max_iterations` is hit.
        """
        tool_config = types.Tool(function_declarations=tools) if tools else None
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            tools=[tool_config] if tool_config else None,
        )

        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        ]
        all_calls: list[ToolCall] = []

        for iteration in range(1, max_iterations + 1):
            resp = self._generate(
                model=self._model_for[tier], contents=contents, config=config
            )

            calls = self._extract_function_calls(resp)
            if not calls:
                return ToolLoopResult(
                    final_text=resp.text or "",
                    tool_calls=all_calls,
                    iterations=iteration,
                )

            # Record the model's turn (its function-call parts) verbatim.
            model_parts = self._model_parts(resp)
            contents.append(types.Content(role="model", parts=model_parts))

            # Execute every requested call and feed results back in one user turn.
            response_parts: list[types.Part] = []
            for call in calls:
                all_calls.append(call)
                try:
                    result = executor(call)
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                response_parts.append(
                    types.Part.from_function_response(name=call.name, response=result)
                )
            contents.append(types.Content(role="user", parts=response_parts))

        return ToolLoopResult(
            final_text="(tool loop hit max iterations)",
            tool_calls=all_calls,
            iterations=max_iterations,
        )

    # ------------------------------------------------------------------ #
    # Response parsing helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_function_calls(resp: Any) -> list[ToolCall]:
        calls: list[ToolCall] = []
        fcs = getattr(resp, "function_calls", None)
        if fcs:
            for fc in fcs:
                calls.append(ToolCall(name=fc.name, args=dict(fc.args or {})))
            return calls
        # Fallback: walk parts manually.
        for cand in getattr(resp, "candidates", None) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    calls.append(ToolCall(name=fc.name, args=dict(fc.args or {})))
        return calls

    @staticmethod
    def _model_parts(resp: Any) -> list[types.Part]:
        for cand in getattr(resp, "candidates", None) or []:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None)
            if parts:
                return list(parts)
        return []
