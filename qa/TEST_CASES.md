# Test Cases — AI Software Development Agent (Web Dashboard)

App under test: FastAPI dashboard for an autonomous multi-agent dev agent (Gemini-powered).
Frontend: single-page `src/agent/web/static/index.html` (Tailwind CDN + vanilla JS).
Backend: `src/agent/web/app.py`.

Test date: 2026-06-23
Environment: Windows 11, Chrome (headed via Playwright), server at http://127.0.0.1:8000
Config: GEMINI_API_KEY set, GITHUB_TOKEN set, AUTONOMY=checkpoint.

Legend: **A** = automated API test (pytest / httpx), **U** = UI test (headed Chrome), **M** = manual/observational.

---

## 1. Backend / API layer

| ID | Title | Type | Steps | Expected |
|----|-------|------|-------|----------|
| API-01 | Dashboard HTML served | A | GET `/` | 200, body contains "AI Software Development Agent", `Cache-Control: no-store` |
| API-02 | Health reports config | A | GET `/health` | 200, JSON has `gemini_key`, `github_token`, `autonomy` keys |
| API-03 | Start run validates config | A | POST `/runs` with keys absent | 400, detail contains "Missing config" |
| API-04 | Unknown run is 404 | A | GET `/runs/does-not-exist` | 404 |
| API-05 | Short repo query short-circuits | A | GET `/api/search/repos?q=a` | 200, `{"repos": []}` (no token needed) |
| API-06 | Short issue query short-circuits | A | GET `/api/search/issues?q=a` | 200, `{"issues": []}` |
| API-07 | Repo search returns results | A | GET `/api/search/repos?q=fastapi` | 200, non-empty `repos[]` with full_name/stars/language |
| API-08 | Issue keyword search returns results | A | GET `/api/search/issues?q=fix typo` | 200, `issues[]` with repo/number/title |
| API-09 | Repo issues list | A | GET `/api/repos/{owner}/{repo}/issues` | 200, `issues[]` (PRs excluded) |
| API-10 | Recommendations | A | GET `/api/recommendations` | 200, `{languages[], issues[]}` |
| API-11 | Resolve unknown run | A | POST `/runs/xxx/approve` | 404 |
| API-12 | WS rejects unknown run | M | WS `/runs/xxx/stream` | Sends `{type:error}` then closes |

## 2. UI — Page load & layout

| ID | Title | Type | Steps | Expected |
|----|-------|------|-------|----------|
| UI-01 | Page loads, no console errors | U | Navigate to `/` | Title "AI Software Development Agent"; no JS console errors |
| UI-02 | Header + subtitle render | U | Inspect header | H1 with robot emoji; subtitle text present |
| UI-03 | Status badge initial state | U | Inspect `#status` | Text = "idle" |
| UI-04 | Timeline pre-populated | U | Inspect `#timeline` | 10 stages: Planning…PullRequest, all greyed `○` |
| UI-05 | Recommendations panel loads | U | Wait for `#recoList` | Either issue cards render, or graceful message (not stuck on "loading…") |

## 3. UI — Search & selection

| ID | Title | Type | Steps | Expected |
|----|-------|------|-------|----------|
| UI-06 | Tab switch Repos→Issues | U | Click "Issues" tab | Tab highlights indigo; hint + placeholder change |
| UI-07 | Repo search dropdown | U | Type "fastapi" in search | Dropdown shows repo rows (full_name, stars, language) |
| UI-08 | Select repo loads issues | U | Click a repo result | Repo panel shows; issue list loads (or "No open issues") |
| UI-09 | Select issue enables Start | U | Click an issue | Issue highlights; selection bar shows; Start button enabled |
| UI-10 | Start disabled w/o issue | U | Select repo only | Start button disabled |
| UI-11 | Option checkboxes default | U | Inspect checkboxes | Run tests = checked, Open PR = checked, Upstream PR = unchecked |
| UI-12 | Issue keyword search | U | Issues tab, type "typo" | Dropdown shows issue rows |
| UI-13 | Recommendation "Use" populates | U | Click "Use" on a reco | Selection bar reflects repo+issue; scrolls to top |
| UI-14 | Reco category filters | U | Click a filter chip | List filters to that category; chip highlights |
| UI-15 | Dropdown closes on outside click | U | Open dropdown, click elsewhere | Dropdown hides |

## 4. UI — Run lifecycle (guarded: reject at first checkpoint, Open PR off)

| ID | Title | Type | Steps | Expected |
|----|-------|------|-------|----------|
| RUN-01 | Start run connects WS | U | Select safe repo+issue, uncheck Open PR, click Start | Status → "running · {id}"; live log starts filling |
| RUN-02 | Timeline activates stages | U | Observe timeline during run | Stages turn active `◉` / done `●` as events arrive |
| RUN-03 | Checkpoint modal appears | U | Wait for plan checkpoint | Modal opens with stage title + body (plan tasks) |
| RUN-04 | Reject resolves checkpoint | U | Click "Reject" | Modal closes; run ends as rejected; Start re-enabled |
| RUN-05 | No PR side effect | M | After reject | No PR opened (Open PR off + rejected before PR stage) |

## 5. UI — Responsive / robustness

| ID | Title | Type | Steps | Expected |
|----|-------|------|-------|----------|
| RES-01 | Narrow viewport | U | Resize to 390px wide | Layout stacks; no horizontal overflow of key controls |
| RES-02 | XSS-safe rendering | M | (code review) `esc()` applied to repo/issue/title strings | User-supplied strings HTML-escaped |
| RES-03 | Stale-config start error | U | (if keys missing) Start | Inline error logged, Start re-enabled |

---

### Notes on scope & safety
- A full autonomous run would clone a repo, call Gemini, and (if approved) open a real PR. To avoid
  outward-facing side effects, RUN tests **uncheck Open PR** and **reject at the first checkpoint**,
  which exercises the start→WebSocket→event-stream→checkpoint→resolve path without pushing anything.
- API tests with live keys hit real GitHub (rate-limited); transient 502s are noted, not failed.
