"""Command-line interface.

    ai-dev-agent run --repo owner/name --issue 42
    ai-dev-agent serve          # launch the web dashboard
"""
from __future__ import annotations

import sys
import uuid

# Windows legacy consoles default to cp1252, which can't encode the status emojis.
# Switch stdio to UTF-8 (replace on failure) so the CLI never crashes on output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

import typer
from rich.console import Console

from agent.checkpoints import AutoCheckpointController, TerminalCheckpointController
from agent.config import Autonomy, get_settings
from agent.events import Event, EventBus
from agent.orchestrator import Orchestrator, RunConfig

app = typer.Typer(add_completion=False, help="Autonomous multi-agent software development agent.")
console = Console()

_ICON = {
    "stage": "▶", "issue": "📌", "agent_started": "🤖", "agent_finished": "✓",
    "tool_call": "🔧", "tool_result": "  ", "log": "·", "plan": "📋",
    "repo_map": "🗺", "design": "📐", "test_result": "🧪",
    "review_findings": "🔎", "security_findings": "🛡",
    "checkpoint": "⏸", "checkpoint_resolved": "✔", "commit": "💾",
    "pull_request": "🔀", "usage": "📊", "error": "❌", "warning": "⚠",
    "run_finished": "🏁",
}


def _printer(event: Event) -> None:
    if event.type in ("tool_result",):
        return
    icon = _ICON.get(event.type, "·")
    who = f"[bold cyan]{event.agent}[/]" if event.agent else ""
    console.print(f"{icon} {who} {event.message}")


@app.command()
def run(
    repo: str = typer.Option(..., "--repo", "-r", help="owner/name or GitHub URL"),
    issue: int = typer.Option(..., "--issue", "-i", help="Issue number to fix"),
    base: str = typer.Option(None, "--base", help="Base branch (default: repo default)"),
    no_tests: bool = typer.Option(False, "--no-tests", help="Skip running tests"),
    no_pr: bool = typer.Option(False, "--no-pr", help="Commit only; don't open a PR"),
    upstream_pr: bool = typer.Option(
        False, "--upstream-pr",
        help="In fork mode, open the PR on the UPSTREAM repo (default: stop at your fork)"),
    auto: bool = typer.Option(False, "--auto", help="Run without approval checkpoints"),
) -> None:
    """Resolve a GitHub issue end-to-end."""
    settings = get_settings()
    try:
        settings.require_gemini()
        settings.require_github()
    except RuntimeError as exc:
        console.print(f"[red]Configuration error:[/] {exc}")
        raise typer.Exit(2)

    run_id = uuid.uuid4().hex[:12]
    bus = EventBus()
    bus.add_sync_listener(_printer)

    use_auto = auto or settings.autonomy == Autonomy.AUTO
    checkpoints = AutoCheckpointController() if use_auto else TerminalCheckpointController()

    console.rule(f"[bold]Run {run_id} — {repo}#{issue}")
    orch = Orchestrator(
        run_id,
        RunConfig(repo=repo, issue_number=issue, base_branch=base,
                  run_tests=not no_tests, open_pr=not no_pr, upstream_pr=upstream_pr),
        bus=bus,
        checkpoints=checkpoints,
    )
    result = orch.run()
    console.rule("[bold]Result")
    color = {"success": "green", "rejected": "yellow", "error": "red"}.get(result.status, "white")
    console.print(f"[{color}]Status: {result.status}[/]")
    if result.mode == "fork" and result.fork:
        console.print(f"Mode: fork → {result.fork}")
    if result.test_summary:
        console.print(f"Tests: {result.test_summary}")
    if result.pr_url:
        console.print(f"PR: {result.pr_url}")
    console.print(result.message)
    raise typer.Exit(0 if result.status == "success" else 1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev)"),
) -> None:
    """Launch the web dashboard."""
    import uvicorn

    console.print(f"Dashboard on http://{host}:{port}{'  (auto-reload)' if reload else ''}")
    uvicorn.run("agent.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
