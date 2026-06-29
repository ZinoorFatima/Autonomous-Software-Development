"""FastAPI application exposing the agent as a live web dashboard.

Endpoints:
    GET  /                      -> dashboard UI
    POST /runs                  -> start a run  {repo, issue, run_tests?, open_pr?}
    GET  /runs/{id}             -> run status
    WS   /runs/{id}/stream      -> live event stream
    POST /runs/{id}/approve     -> resolve the current checkpoint (approve)
    POST /runs/{id}/reject      -> resolve the current checkpoint (reject)

The orchestrator runs in a worker thread per run; events flow back over the
EventBus, which marshals them onto the asyncio loop for WebSocket delivery.
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent.checkpoints import WebCheckpointController
from agent.config import get_settings
from agent.events import EventBus
from agent.integrations.github import GitHubClient
from agent.orchestrator import Orchestrator, RunConfig, RunResult

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AI Software Development Agent")

_gh_client: GitHubClient | None = None


def gh_client() -> GitHubClient:
    """Cached GitHub client for discovery endpoints; 400 if no token configured."""
    global _gh_client
    if not get_settings().github_token:
        raise HTTPException(status_code=400, detail="GITHUB_TOKEN is not set in .env.")
    if _gh_client is None:
        _gh_client = GitHubClient(fail_fast=True)
    return _gh_client


_reco_cache: dict[str, Any] | None = None


# --------------------------------------------------------------------- #
# Run management
# --------------------------------------------------------------------- #
@dataclass
class RunState:
    run_id: str
    bus: EventBus
    controller: WebCheckpointController
    orchestrator: Orchestrator
    thread: threading.Thread | None = None
    result: RunResult | None = None


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def get(self, run_id: str) -> RunState:
        state = self._runs.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown run '{run_id}'")
        return state

    def start(self, cfg: RunConfig, loop: asyncio.AbstractEventLoop) -> str:
        run_id = uuid.uuid4().hex[:12]
        bus = EventBus()
        bus.bind_loop(loop)
        controller = WebCheckpointController(bus, run_id)
        orch = Orchestrator(run_id, cfg, bus=bus, checkpoints=controller)
        state = RunState(run_id=run_id, bus=bus, controller=controller, orchestrator=orch)
        self._runs[run_id] = state

        def _work() -> None:
            state.result = orch.run()

        t = threading.Thread(target=_work, name=f"run-{run_id}", daemon=True)
        state.thread = t
        t.start()
        return run_id


manager = RunManager()


# --------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------- #
class RunRequest(BaseModel):
    repo: str
    issue: int
    run_tests: bool = True
    open_pr: bool = True
    upstream_pr: bool = False
    base: str | None = None


class ResolveRequest(BaseModel):
    feedback: str = ""


# --------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------- #
@app.get("/")
async def index() -> FileResponse:
    # no-store so the dashboard HTML is never served stale after an update
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"gemini_key": bool(s.gemini_api_key), "github_token": bool(s.github_token),
            "autonomy": s.autonomy.value}


@app.post("/runs")
async def create_run(req: RunRequest) -> dict:
    s = get_settings()
    missing = [n for n, v in (("GEMINI_API_KEY", s.gemini_api_key),
                              ("GITHUB_TOKEN", s.github_token)) if not v]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing config: {', '.join(missing)}. Set them in .env.")
    loop = asyncio.get_running_loop()
    cfg = RunConfig(repo=req.repo, issue_number=req.issue, base_branch=req.base,
                    run_tests=req.run_tests, open_pr=req.open_pr, upstream_pr=req.upstream_pr)
    run_id = manager.start(cfg, loop)
    return {"run_id": run_id}


# --- Discovery (search + recommendations). Sync `def` => threadpool offload. --- #
@app.get("/api/search/repos")
def api_search_repos(q: str = "") -> dict:
    if len(q.strip()) < 2:
        return {"repos": []}
    try:
        return {"repos": gh_client().search_repositories(q)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"GitHub search failed: {exc}")


@app.get("/api/search/issues")
def api_search_issues(q: str = "") -> dict:
    if len(q.strip()) < 2:
        return {"issues": []}
    try:
        return {"issues": gh_client().search_issues_kw(q)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Issue search failed: {exc}")


@app.get("/api/repos/{owner}/{repo}/issues")
def api_repo_issues(owner: str, repo: str) -> dict:
    try:
        return {"issues": gh_client().list_issues(f"{owner}/{repo}")}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not list issues: {exc}")


@app.get("/api/recommendations")
def api_recommendations(refresh: bool = False) -> dict:
    global _reco_cache
    if _reco_cache is not None and not refresh:
        return _reco_cache
    try:
        result = gh_client().recommend_issues()
        # Only cache a non-empty result so a transient rate-limit doesn't stick.
        if result.get("issues"):
            _reco_cache = result
        return result
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Recommendations failed: {exc}")


@app.get("/runs/{run_id}")
async def run_status(run_id: str) -> dict:
    state = manager.get(run_id)
    alive = state.thread.is_alive() if state.thread else False
    res = state.result
    return {
        "run_id": run_id,
        "running": alive,
        "pending_checkpoint": state.controller.pending_stage,
        "result": None if res is None else {
            "status": res.status, "pr_url": res.pr_url, "branch": res.branch,
            "test_summary": res.test_summary, "message": res.message,
        },
    }


@app.post("/runs/{run_id}/approve")
async def approve(run_id: str, body: ResolveRequest | None = None) -> dict:
    state = manager.get(run_id)
    ok = state.controller.resolve(approved=True, feedback=(body.feedback if body else ""))
    return {"resolved": ok}


@app.post("/runs/{run_id}/reject")
async def reject(run_id: str, body: ResolveRequest | None = None) -> dict:
    state = manager.get(run_id)
    ok = state.controller.resolve(approved=False, feedback=(body.feedback if body else ""))
    return {"resolved": ok}


@app.websocket("/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    try:
        state = manager.get(run_id)
    except HTTPException:
        await ws.send_json({"type": "error", "message": f"Unknown run '{run_id}'"})
        await ws.close()
        return

    queue = state.bus.subscribe(replay=True)
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event.to_dict())
    except WebSocketDisconnect:
        pass
    finally:
        state.bus.unsubscribe(queue)
