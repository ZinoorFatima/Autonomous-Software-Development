"""Small shared helpers."""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_loose(text: str) -> Any:
    """Best-effort JSON extraction from a model response.

    Handles raw JSON, ```json fenced blocks, and prose with an embedded object/array.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fall back to the first balanced { } or [ ] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from response: {text[:200]}...")
