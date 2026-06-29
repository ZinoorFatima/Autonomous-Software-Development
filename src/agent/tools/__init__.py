"""Tool layer — sandboxed actions exposed to agents via Gemini function-calling."""
from __future__ import annotations

from agent.tools import files, git_tools, search, shell
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec

# Tool-name groups, so each agent can be handed only what its role needs.
READ_TOOLS = ["read_file", "list_dir", "search_code", "git_status", "git_diff"]
WRITE_TOOLS = ["write_file", "edit_file"]
EXEC_TOOLS = ["run_command"]
# Coding/debug agents only read & write; the Testing agent owns execution. This
# keeps them fast and prevents them from burning iterations trying to run linters
# or tools that aren't installed in the workspace.
EDIT_TOOLS = READ_TOOLS + WRITE_TOOLS
CODING_TOOLS = READ_TOOLS + WRITE_TOOLS + EXEC_TOOLS


def build_registry(ctx: ToolContext) -> ToolRegistry:
    """Create a registry with every default tool registered against `ctx`."""
    registry = ToolRegistry(ctx)
    files.register(registry)
    search.register(registry)
    shell.register(registry)
    git_tools.register(registry)
    return registry


__all__ = [
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "build_registry",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "EXEC_TOOLS",
    "EDIT_TOOLS",
    "CODING_TOOLS",
]
