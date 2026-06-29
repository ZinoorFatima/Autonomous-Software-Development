# 🤖 AI Software Development Agent

A portfolio-grade **autonomous, multi-agent software-development agent** (a mini
Devin / OpenHands) powered by the **Gemini API**.

Give it a GitHub issue and it will read it, understand the codebase, plan, write
the code, run the tests, debug failures, review its own work, and open a pull
request — all visible live in a web dashboard, with human approval checkpoints.

```
Issue → Planning → RepoAnalysis → Architect → Backend/Frontend
      → Testing ⇄ Debug → Review + Security → Pull Request
```

## Why this is interesting

It exercises nearly the entire modern agent stack:

| Capability | Where |
|---|---|
| **Planning** | `PlanningAgent` turns an issue into ordered tasks |
| **Memory / context** | repo map + diff threaded through the pipeline |
| **Tool calling** | Gemini function-calling → sandboxed file/search/shell/git tools |
| **Code generation** | `Backend` / `Frontend` coding agents edit the workspace |
| **Environment interaction** | clone repo, run `pytest` in an isolated workspace |
| **Self-correction** | `Testing ⇄ Debug` loop, bounded by `MAX_DEBUG_RETRIES` |
| **Multi-agent orchestration** | `Architect` routes work to specialists; `Review` + `Security` gate it |
| **Long-running workflow** | orchestrator state machine + live event stream |
| **Human-in-the-loop** | approval checkpoints after plan / before commit / before PR |

## Architecture

A central **orchestrator** (`src/agent/orchestrator.py`) drives a pipeline of
specialised Gemini agents over a shared, sandboxed tool layer and a per-run
workspace. Reasoning-heavy agents use a **Gemini Pro** model; high-volume agents
use **Gemini Flash**.

```
                    ┌──────────────────────────┐
   Web Dashboard ◄──► FastAPI + WebSocket layer │
   (start, approve, └────────────┬─────────────┘
    live timeline)                │ events / checkpoints
                                  ▼
                          ┌───────────────┐
                          │  Orchestrator │  state machine + event bus
                          └───────┬───────┘
   Planning · RepoAnalysis · Architect · Backend/Frontend · Testing/Debug ·
   Review · Security · PullRequest   — all share the Tool layer + workspace
```

## Project layout

```
src/agent/
  config.py            # pydantic-settings (.env)
  events.py            # thread-safe event bus
  checkpoints.py       # auto / terminal / web approval gates
  orchestrator.py      # the pipeline state machine
  llm/gemini.py        # Gemini wrapper: tiered models, JSON, tool-loop, retries
  agents/              # Planning, RepoAnalysis, Architect, Backend, Frontend,
                       #   Testing, Debug, Review, Security, PullRequest
  tools/               # files, search, shell (allowlisted), git  + registry
  integrations/        # github.py (issues/PRs), workspace.py (clone/test)
  web/                 # FastAPI app + single-page dashboard
  cli.py               # `ai-dev-agent run` / `serve`
tests/                 # tool, git, orchestrator (fakes), testing-agent, web
```

## Getting your API keys

You need two secrets, both placed in a local `.env` file (copy `.env.example`).
**Never commit `.env` or paste secrets into chat** — it is gitignored for this reason.

### 1. Gemini API key
1. Go to <https://aistudio.google.com/apikey>.
2. **Create API key** → copy it.
3. Put it in `.env` as `GEMINI_API_KEY=...`.

### 2. GitHub Personal Access Token (fine-grained, recommended)
1. Go to <https://github.com/settings/personal-access-tokens/new>.
2. Name it (e.g. `ai-dev-agent`), set an expiration, and under **Repository
   access** choose **Only select repositories** → your demo repo.
3. Under **Repository permissions** set these to **Read and write**:
   **Contents**, **Pull requests**, **Issues**.
4. **Generate token** and copy it (shown once).
5. Put it in `.env` as `GITHUB_TOKEN=...`.

> 🔒 Point the agent at a **fork or throwaway repo you own** for demos — it can
> push commits and open PRs. Mistakes there are harmless.

## Quick start

```bash
python -m venv .venv
# Windows:
./.venv/Scripts/activate
# macOS/Linux:
# source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env            # then fill in the two keys above

# Headless run (CLI)
ai-dev-agent run --repo owner/name --issue 42

# Web dashboard
ai-dev-agent serve              # open http://127.0.0.1:8000
```

In the dashboard you **search GitHub** — by **repository** *or* by **issue
keyword** — pick an open issue, and hit Start. No typing repo names or issue
numbers.

A **"Recommended for you"** panel suggests approachable tickets, ranked by a
heuristic that rewards beginner labels, simple-scope titles, low comment counts,
recency, **small repos**, and **CI presence** (so the agent's test step is more
likely to succeed) — and penalizes hard-scope work. Suggestions draw from your
account's **top languages** and the repos you've **starred**, and can be filtered
by category (**Docs / Bugs / Tests / Features**).

CLI flags: `--auto` (no checkpoints), `--no-tests`, `--no-pr`, `--base <branch>`,
`--upstream-pr` (see fork mode below).

## Contributing to repos you don't own (fork mode)

If your token can't push to the target repo, the agent automatically uses GitHub's
**fork & pull** model (via the API — no browser automation):

1. **Fork** the upstream repo to your account
2. Clone the fork, branch, code, test, commit, **push to your fork**
3. Open the PR

By default it **stops at your fork** — the PR is opened on *your* fork so you can
review/test before bothering upstream maintainers. To propose it to the original
repo, pass `--upstream-pr` (CLI) or tick the box (web); the agent then opens a
cross-repo PR (`yourname:branch → upstream:main`).

> **Token scope:** forking arbitrary OSS repos requires a token that can create &
> push to new repos — use a **classic token with the `repo` scope**, or a
> fine-grained token scoped to **All repositories** (Contents/PRs/Issues R-W). A
> token limited to a few selected repos can read public issues but cannot fork.
>
> **Etiquette:** unsolicited AI-generated PRs are unwelcome on many projects. Use
> fork mode responsibly — keep changes on your fork unless a project explicitly
> invites contributions.

## Configuration (`.env`)

| Var | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio key | — |
| `GITHUB_TOKEN` | Fine-grained PAT (Contents/PRs/Issues R-W) | — |
| `GEMINI_MODEL_PRO` | Reasoning model | `gemini-2.5-pro` |
| `GEMINI_MODEL_FLASH` | High-volume model | `gemini-2.5-flash` |
| `MAX_DEBUG_RETRIES` | Debug-loop bound | `3` |
| `AUTONOMY` | `checkpoint` or `auto` | `checkpoint` |
| `WORKSPACE_ROOT` | Where repos are cloned per run | `workspaces` |

## Security model

- Secrets live only in `.env` (gitignored).
- All file operations are **sandboxed** to the per-run workspace (path-traversal
  rejected).
- Shell execution is restricted to an **allowlist** of programs (`pytest`, `pip`,
  `python`, `git`, …) with **no shell operators** — the execution surface is
  abstracted in `tools/shell.py` so a Docker backend can replace it later.

## Testing

```bash
pytest -q        # tool sandbox, git, orchestrator wiring (fakes), web API
```

The orchestrator test runs the **entire pipeline** with a fake Gemini + fake
GitHub, so it needs no network or keys.

## Roadmap (documented future upgrades)

- **Docker sandbox** in place of the allowlisted local workspace.
- Full **frontend / JS-TS** test runners (currently Python-first).
- Persistent multi-run history (currently in-memory per run).
