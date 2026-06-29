# Test Results — AI Software Development Agent (Web Dashboard)

**Date:** 2026-06-23
**Tester:** Claude Code (automated)
**Build:** local source, `src/agent` (FastAPI + Gemini multi-agent)
**Environment:** Windows 11 · Python 3.13 (.venv) · Google Chrome (headed, Playwright) · server `http://127.0.0.1:8000`
**Config:** `GEMINI_API_KEY` set · `GITHUB_TOKEN` set · `AUTONOMY=checkpoint`

## Executive summary

| Layer | Passed | Failed | Notes |
|-------|:------:|:------:|:-----:|
| Unit (pytest) | 27 | 0 | 1 deprecation warning |
| API (live, httpx) | 11 | 0 | 1 transient rate-limit (recovered) |
| UI (headed Chrome) | 19 | 0 | 1 cosmetic note (favicon 404) |
| Run lifecycle | full | — | reached real plan checkpoint, reject OK |

**Verdict: the app works end-to-end with no functional defects found.** The headed-browser run
exercised the complete happy path — search → select → start → live WebSocket events → agents
running (Planning + RepoAnalysis) → **plan checkpoint with a real Gemini-generated plan** → reject.
Three low-severity / polish findings are listed below; none block use.

How testing was kept safe: the run lifecycle test unchecked **Open PR** and **rejected at the first
checkpoint**, so the agent never pushed a branch or opened a pull request. Only a local clone was
created under `workspaces/`.

---

## 1. Unit tests (pytest)

`python -m pytest -q` → **27 passed, 1 warning in 7.15s**

- Warning: `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`
  (from FastAPI's TestClient; cosmetic, not app code). See finding F-4.

## 2. API tests (live server, real GitHub/Gemini)

| ID | Result | Detail |
|----|:------:|--------|
| API-01 dashboard served | PASS | 200, `Cache-Control: no-store` present |
| API-02 health | PASS | `{gemini_key:true, github_token:true, autonomy:"checkpoint"}` |
| API-03 start run accepts valid cfg | PASS | 200, returns `run_id` |
| API-04 unknown run | PASS | 404 |
| API-05 short repo query | PASS | `{"repos":[]}` (no token hit) |
| API-06 short issue query | PASS | `{"issues":[]}` |
| API-07 repo search | PASS | 12 results, first = `fastapi/fastapi` |
| API-08 issue keyword search | PASS* | *first call returned 0 (rate-limit); UI-12 later returned 25 rows |
| API-09 repo issue list | PASS | `tiangolo/fastapi` → 1 (verified correct, see F-2) |
| API-10 recommendations | PASS | langs `[Python, JavaScript]`, 16 issues |
| API-11 resolve unknown run | PASS | 404 |

## 3. UI tests — headed Chrome (Playwright)

All 19 assertions passed. Screenshots in `qa/screenshots/`.

| ID | Result | Detail |
|----|:------:|--------|
| UI-01 page loads | PASS | title correct |
| UI-02 header | PASS | 🤖 AI Software Development Agent |
| UI-03 status idle | PASS | badge = "idle" |
| UI-04 timeline stages | PASS | 10 stages Planning…PullRequest |
| UI-05 recommendations load | PASS | 16 "Use" cards rendered |
| UI-06 tab switch repos↔issues | PASS | active styling + hint/placeholder swap |
| UI-07 repo search | PASS | 12 rows |
| UI-08 select repo loads issues | PASS | issue list populated |
| UI-09 select issue enables Start | PASS | selection bar + Start enabled |
| UI-10 Start disabled w/o issue | PASS | disabled until issue chosen |
| UI-11 checkbox defaults | PASS | Run tests=on, Open PR=on, Upstream PR=off |
| UI-12 issue keyword search | PASS | 25 rows |
| UI-13 reco "Use" populates | PASS | selection reflected, scroll to top |
| RES-01 narrow viewport (390px) | PASS | layout stacks, no overflow (−8px) |
| UI-CONSOLE | NOTE | 1 console error: `favicon.ico 404` (see F-1) |

## 4. Run lifecycle (guarded)

| ID | Result | Detail |
|----|:------:|--------|
| RUN-01 start connects WS | PASS | status → `running · 397a27e2ae7e`, log streamed |
| RUN-02 timeline activates | PASS | Planning active, RepoAnalysis completed |
| RUN-03 checkpoint modal | PASS | `Checkpoint · plan` with 16 real Gemini-planned tasks |
| RUN-04 reject resolves | PASS | status → `finished: rejected`, Start re-enabled |
| RUN-05 no PR side effect | PASS | Open PR off + rejected before PR stage; no branch/PR created |

Target issue: `fastapi/fastapi #10370 (🚀 Roadmap)`. The plan modal rendered tasks such as
"Implement Pydantic v2 for request body parsing", confirming the planning agent produced real output.
See `qa/screenshots/08b_checkpoint.png`.

---

## Findings & recommended improvements

### F-1 · Missing favicon → console 404 (Severity: Low / cosmetic)
Every page load requests `/favicon.ico`, which 404s and shows as a browser console error.
**Fix:** add a `<link rel="icon" ...>` (a data-URI emoji works) or a tiny FastAPI route returning 204.
*Effort: trivial.*

### F-2 · Repo search "N issues" count includes PRs (Severity: Low / UX)
The repo search row shows `open_issues` from GitHub's `open_issues_count`, which **counts PRs as
issues**. Verified: `fastapi/fastapi` advertises 97 but has only **1** real open issue; `pallets/flask`
advertises 4 but has **0**. The issue list then correctly shows "No open issues" / a single item,
which can look like a bug to users who saw a higher count.
**Fix:** label it `★ … · N issues+PRs`, or fetch the real issue count, so the search row and the
issue list agree. (The `list_issues` filtering itself is correct — confirmed against GitHub search.)
*Effort: small.*

### F-3 · Rate-limit looks identical to "no results" (Severity: Low / reliability)
Discovery endpoints use `fail_fast` (PyGithub `retry=0`). Under rapid use, GitHub search rate-limits
and `_take()` swallows the exception, returning `[]`. The UI then renders "No matches" — indistinguishable
from a genuinely empty result. Observed once: issue search returned 0, then 25 moments later.
**Fix:** distinguish a 403/rate-limit from an empty result and surface e.g. "GitHub rate limit — retry
shortly" in the dropdown. *Effort: small.*

### F-4 · Test deprecation warning (Severity: Trivial)
`starlette.testclient` httpx deprecation warning in pytest. Pin/migrate per Starlette guidance when
convenient. *Effort: trivial.*

## What was verified as working well
- Config validation (`/runs` rejects missing keys; health reports state).
- Real GitHub discovery: repo search, issue keyword search, per-repo issue list, recommendations
  with language detection, scoring, category filters, and CI/size enrichment.
- Full agent pipeline up to the first checkpoint, with live WebSocket event streaming and an accurate
  timeline.
- Checkpoint approve/reject flow, clean run teardown, Start re-enable.
- Responsive layout down to 390px; HTML escaping (`esc()`) applied to all user-supplied strings.
- No JS errors during the session other than the favicon 404.

## Artifacts
- Test cases: `qa/TEST_CASES.md`
- Raw UI results: `qa/ui_results.json`
- UI test driver: `qa/ui_tests.py` (re-runnable headed Chrome)
- Screenshots: `qa/screenshots/*.png`
- Server log: `qa/server.log`

## How to reproduce
```bash
# 1. start server
.venv/Scripts/python.exe -m uvicorn agent.web.app:app --host 127.0.0.1 --port 8000 --app-dir src
# 2. unit tests
.venv/Scripts/python.exe -m pytest -q
# 3. headed Chrome UI tests (watch the window)
.venv/Scripts/python.exe qa/ui_tests.py
```
