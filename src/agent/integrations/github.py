"""GitHub integration via PyGithub: read issues, open pull requests.

Repo identifiers are accepted as either 'owner/name' or a full URL.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Signals used to rank how "approachable" an issue is.
BEGINNER_LABELS = {
    "good first issue", "good-first-issue", "help wanted", "help-wanted", "easy",
    "beginner", "starter", "low-hanging-fruit", "documentation", "docs",
    "first-timers-only", "e-easy", "difficulty: easy",
}
SIMPLE_KW = ("typo", "doc", "docs", "readme", "comment", "rename", "classifier",
             "example", "test", "lint", "format", "spelling", "link", "wording")
HARD_KW = ("refactor", "redesign", "architecture", "rewrite", "security", "migrate",
           "epic", "rfc", "performance", "concurrency", "deadlock", "race condition",
           "proposal", "investigate", "design")


def categorize(title: str, labels: list[str]) -> str:
    """Bucket an issue into docs | bug | test | feature | other."""
    low = {l.lower() for l in labels}
    t = title.lower()
    has = lambda *w: any(x in t for x in w)
    if low & {"documentation", "docs"} or has("doc", "docs", "readme", "typo", "wording", "spelling"):
        return "docs"
    if low & {"bug", "defect", "regression"} or has("[bug]", "fix ", "error", "crash", "broken", "fails", "incorrect"):
        return "bug"
    if any("test" in l for l in low) or has("test", "coverage", "unit test", "e2e"):
        return "test"
    if low & {"enhancement", "feature"} or has("add ", "implement", "support", "feature"):
        return "feature"
    return "other"

from github import Auth, Github
from github.GithubException import GithubException

from agent.config import get_settings


@dataclass
class IssueInfo:
    number: int
    title: str
    body: str
    labels: list[str]
    url: str

    def as_prompt(self) -> str:
        labels = f" [labels: {', '.join(self.labels)}]" if self.labels else ""
        return f"Issue #{self.number}: {self.title}{labels}\n\n{self.body or '(no description)'}"


def _take(paginated: Any, n: int) -> list[Any]:
    """Safely pull up to `n` items from a PyGithub PaginatedList.

    Slicing a PaginatedList (`[:n]`) raises IndexError when it has fewer than `n`
    items, so iterate manually and stop early instead.
    """
    out: list[Any] = []
    try:
        for item in paginated:
            out.append(item)
            if len(out) >= n:
                break
    except Exception:  # noqa: BLE001 - GithubException / IndexError on empty pages
        pass
    return out


def normalize_repo(repo: str) -> str:
    """Accept 'owner/name', 'https://github.com/owner/name(.git)', and return 'owner/name'."""
    repo = repo.strip()
    m = re.search(r"github\.com[:/]+([^/]+/[^/.]+)", repo)
    if m:
        return m.group(1)
    return repo.removesuffix(".git")


class GitHubClient:
    def __init__(self, token: str | None = None, fail_fast: bool = False) -> None:
        settings = get_settings()
        self._token = token or settings.require_github()
        # fail_fast: don't let PyGithub back off 60s on search rate limits — used by
        # the interactive discovery endpoints so the UI stays responsive.
        if fail_fast:
            self._gh = Github(auth=Auth.Token(self._token), retry=0, seconds_between_requests=0)
        else:
            self._gh = Github(auth=Auth.Token(self._token))

    def get_issue(self, repo: str, number: int) -> IssueInfo:
        r = self._gh.get_repo(normalize_repo(repo))
        issue = r.get_issue(number)
        return IssueInfo(
            number=issue.number,
            title=issue.title,
            body=issue.body or "",
            labels=[l.name for l in issue.labels],
            url=issue.html_url,
        )

    def default_branch(self, repo: str) -> str:
        return self._gh.get_repo(normalize_repo(repo)).default_branch

    def login(self) -> str:
        return self._gh.get_user().login

    def can_push(self, repo: str) -> bool:
        """True if the authenticated token has push access to `repo`."""
        try:
            r = self._gh.get_repo(normalize_repo(repo))
        except GithubException:
            return False
        perms = getattr(r, "permissions", None)
        return bool(perms and (perms.push or perms.admin))

    def ensure_fork(self, repo: str, wait_seconds: int = 40) -> str:
        """Fork `repo` to the authenticated account (idempotent) and wait until the
        fork is clonable. Returns the fork's 'owner/name'."""
        upstream = self._gh.get_repo(normalize_repo(repo))
        try:
            fork = upstream.create_fork()  # returns existing fork if already forked
        except GithubException as exc:
            if getattr(exc, "status", None) == 403:
                raise RuntimeError(
                    "Could not create a fork: your token can't fork repos you don't own. "
                    "Forking needs a CLASSIC token with the 'repo' scope (token starts with "
                    "'ghp_'). Fine-grained tokens ('github_pat_…') cannot fork. Create one at "
                    "https://github.com/settings/tokens/new (tick 'repo'), put it in .env, and retry."
                ) from exc
            raise
        full = fork.full_name
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                r = self._gh.get_repo(full)
                if r.default_branch:
                    return full
            except GithubException:
                pass
            time.sleep(2)
        return full

    def authed_clone_url(self, repo: str) -> str:
        """HTTPS clone URL with the token embedded (for push)."""
        full = normalize_repo(repo)
        return f"https://x-access-token:{self._token}@github.com/{full}.git"

    def open_pull_request(
        self, repo: str, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        """Open a PR on `repo`. For a cross-repo (fork) PR, pass head as 'owner:branch'."""
        r = self._gh.get_repo(normalize_repo(repo))
        pr = r.create_pull(title=title, body=body, head=head, base=base)
        return {"number": pr.number, "url": pr.html_url, "title": pr.title}

    # ------------------------------------------------------------------ #
    # Discovery: search + recommendations (for the dashboard)
    # ------------------------------------------------------------------ #
    def search_repositories(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        """Search public repos. Accepts plain text, 'owner/name', or 'user/' prefixes."""
        query = query.strip()
        if not query:
            return []
        # Make a bare "owner/" act as "list this owner's repos".
        if query.endswith("/"):
            query = f"user:{query[:-1]}"
        results = self._gh.search_repositories(query=query, sort="stars", order="desc")
        out: list[dict[str, Any]] = []
        for r in _take(results, limit):
            out.append({
                "full_name": r.full_name,
                "description": (r.description or "")[:140],
                "stars": r.stargazers_count,
                "language": r.language,
                "open_issues": r.open_issues_count,
            })
        return out

    def search_issues_kw(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """Keyword search across open issues on GitHub (pull requests excluded)."""
        query = query.strip()
        if not query:
            return []
        try:
            results = self._gh.search_issues(query=f"{query} is:issue is:open", sort="updated", order="desc")
        except GithubException as exc:
            raise RuntimeError(str(exc)) from exc
        out: list[dict[str, Any]] = []
        for issue in _take(results, limit):
            m = re.search(r"github\.com/([^/]+/[^/]+)/issues/(\d+)", issue.html_url)
            if not m:
                continue
            out.append({
                "repo": m.group(1),
                "number": int(m.group(2)),
                "title": issue.title,
                "labels": [l.name for l in issue.labels][:4],
                "comments": getattr(issue, "comments", 0),
                "url": issue.html_url,
            })
        return out

    def list_issues(self, repo: str, limit: int = 30) -> list[dict[str, Any]]:
        """Open issues for a repo (pull requests excluded)."""
        r = self._gh.get_repo(normalize_repo(repo))
        out: list[dict[str, Any]] = []
        for i in r.get_issues(state="open", sort="updated"):
            if i.pull_request is not None:
                continue
            out.append({
                "number": i.number,
                "title": i.title,
                "labels": [l.name for l in i.labels],
                "comments": i.comments,
                "url": i.html_url,
            })
            if len(out) >= limit:
                break
        return out

    def top_languages(self, scan: int = 30) -> list[str]:
        counts: dict[str, int] = {}
        for r in self._gh.get_user().get_repos()[:scan]:
            if r.language:
                counts[r.language] = counts.get(r.language, 0) + 1
        return sorted(counts, key=counts.get, reverse=True)[:3]

    @staticmethod
    def _score_issue(title: str, labels: list[str], comments: int | None,
                     updated_at: datetime | None) -> tuple[float, str]:
        """Higher score = more approachable. Returns (score, one-line reason)."""
        score = 0.0
        reasons: list[str] = []
        low = {l.lower() for l in labels}
        beginner_hits = low & BEGINNER_LABELS
        if beginner_hits:
            score += 3 * len(beginner_hits)
            reasons.append("beginner-labeled")
        t = title.lower()
        if any(k in t for k in SIMPLE_KW):
            score += 2
            reasons.append("simple scope")
        if any(k in t for k in HARD_KW):
            score -= 3
        if len(title) < 60:
            score += 1
        if comments is not None:
            if comments <= 2:
                score += 1
                reasons.append("undisputed")
            else:
                score -= min(comments - 2, 6) * 0.5
        if updated_at is not None:
            try:
                now = datetime.now(timezone.utc)
                ua = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
                days = (now - ua).days
                if days <= 30:
                    score += 2
                    reasons.append("active")
                elif days <= 120:
                    score += 1
            except Exception:  # noqa: BLE001
                pass
        return score, ", ".join(reasons) or "matches your stack"

    def _candidate(self, issue: Any, language: str, source: str) -> dict[str, Any] | None:
        if getattr(issue, "pull_request", None) is not None:
            return None
        m = re.search(r"github\.com/([^/]+/[^/]+)/issues/(\d+)", issue.html_url)
        if not m:
            return None
        labels = [l.name for l in issue.labels]
        score, reason = self._score_issue(
            issue.title, labels, getattr(issue, "comments", None), getattr(issue, "updated_at", None))
        return {
            "repo": m.group(1),
            "number": int(m.group(2)),
            "title": issue.title,
            "labels": labels[:4],
            "language": language,
            "comments": getattr(issue, "comments", 0),
            "url": issue.html_url,
            "category": categorize(issue.title, labels),
            "repo_size": None,
            "has_ci": None,
            "score": score,
            "reason": reason,
            "source": source,
        }

    def _repo_meta(self, full_name: str) -> dict[str, Any]:
        """Repo size (KB) and whether it has CI workflows — signals that the agent's
        test step is more likely to succeed. Best-effort."""
        try:
            r = self._gh.get_repo(full_name)
            size = r.size
        except GithubException:
            return {"size": None, "has_ci": False}
        has_ci = False
        try:
            contents = r.get_contents(".github/workflows")
            has_ci = bool(contents)
        except GithubException:
            has_ci = False
        return {"size": size, "has_ci": has_ci}

    def recommend_issues(self, limit: int = 9) -> dict[str, Any]:
        """Suggest approachable open issues, ranked by a heuristic score.

        Sources: (a) good-first-issue search in the user's top languages, and
        (b) open beginner-labeled issues in repos the user has starred. Candidates
        are de-duplicated and ranked by `_score_issue`.
        """
        langs = (self.top_languages() or ["python"])[:2]  # cap search calls (rate limits)
        by_url: dict[str, dict[str, Any]] = {}

        # Source A: language search (broad candidate pool, ranked later).
        for lang in langs:
            q = f'label:"good first issue" language:{lang} state:open no:assignee'
            try:
                hits = self._gh.search_issues(query=q, sort="updated", order="desc")
            except GithubException:
                continue
            for issue in _take(hits, 15):
                cand = self._candidate(issue, lang, "language")
                if cand and cand["url"] not in by_url:
                    by_url[cand["url"]] = cand

        # Source B: issues in repos the user has starred (core API, not search-limited).
        try:
            starred = _take(self._gh.get_user().get_starred(), 8)
        except GithubException:
            starred = []
        for repo in starred:
            try:
                issues = repo.get_issues(state="open", labels=["good first issue"])
            except GithubException:
                continue
            for issue in _take(issues, 4):
                cand = self._candidate(issue, repo.language or "", "starred")
                if cand and cand["url"] not in by_url:
                    cand["score"] += 1.5  # interest signal: you starred this repo
                    cand["reason"] = "from a repo you starred, " + cand["reason"]
                    by_url[cand["url"]] = cand

        # Rank, then enrich the strongest candidates with repo size + CI presence
        # (signals that the agent's clone/install/test step is likely to succeed).
        ranked = sorted(by_url.values(), key=lambda c: c["score"], reverse=True)[:16]
        meta_cache: dict[str, dict[str, Any]] = {}
        for c in ranked:
            meta = meta_cache.setdefault(c["repo"], self._repo_meta(c["repo"]))
            c["repo_size"] = meta["size"]
            c["has_ci"] = meta["has_ci"]
            if meta["has_ci"]:
                c["score"] += 2
                c["reason"] += ", has CI"
            size = meta["size"]
            if size is not None:
                if size < 3000:
                    c["score"] += 2
                elif size < 15000:
                    c["score"] += 1
                elif size > 120000:
                    c["score"] -= 1
            if c["category"] == "docs":
                c["score"] += 1  # docs changes need no test deps — safest for the agent
            c["score"] = round(c["score"], 1)
        ranked.sort(key=lambda c: c["score"], reverse=True)
        return {"languages": langs, "issues": ranked}
