"""Web API smoke tests (no real run; keys absent in CI)."""
from __future__ import annotations

import agent.config as cfg
from fastapi.testclient import TestClient


def _client(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(cfg, "_settings", None)
    # Build settings with no .env influence
    s = cfg.Settings(_env_file=None)
    monkeypatch.setattr(cfg, "_settings", s)
    from agent.web.app import app
    return TestClient(app)


def test_index_served(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/")
    assert r.status_code == 200
    assert "AI Software Development Agent" in r.text


def test_health(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["gemini_key"] is False
    assert body["github_token"] is False


def test_run_requires_keys(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/runs", json={"repo": "owner/name", "issue": 1})
    assert r.status_code == 400
    assert "Missing config" in r.json()["detail"]


def test_unknown_run_404(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/runs/does-not-exist")
    assert r.status_code == 404


def test_search_short_query_no_token_needed(monkeypatch):
    # Queries under 2 chars short-circuit before hitting GitHub, so no token required.
    client = _client(monkeypatch)
    r = client.get("/api/search/repos?q=a")
    assert r.status_code == 200
    assert r.json() == {"repos": []}


def test_search_requires_token(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/search/repos?q=fastapi")
    assert r.status_code == 400


def test_recommendations_requires_token(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/recommendations")
    assert r.status_code == 400


def test_issue_search_short_query_no_token(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/search/issues?q=a")
    assert r.status_code == 200
    assert r.json() == {"issues": []}


def test_issue_search_requires_token(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/api/search/issues?q=fix+typo")
    assert r.status_code == 400
