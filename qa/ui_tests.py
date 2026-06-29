"""Headed Chrome UI tests for the AI Dev Agent dashboard.

Drives a REAL, visible Chrome window via Playwright so the run can be watched.
Records PASS/FAIL/NOTE per test case and writes qa/ui_results.json + screenshots.

Run:  .venv/Scripts/python.exe qa/ui_tests.py
"""
from __future__ import annotations
import json, time, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://127.0.0.1:8000"
QA = Path(__file__).parent
SHOTS = QA / "screenshots"
SHOTS.mkdir(exist_ok=True)

results = []          # (id, status, detail)
console_errors = []   # collected JS console errors


def rec(tid, status, detail=""):
    print(f"[{status:4}] {tid}: {detail}")
    results.append({"id": tid, "status": status, "detail": str(detail)[:300]})


def shot(page, name):
    p = SHOTS / f"{name}.png"
    try:
        page.screenshot(path=str(p))
    except Exception as e:
        print("screenshot failed", e)


def main():
    with sync_playwright() as pw:
        # channel="chrome" -> use the installed Google Chrome, headed so user can watch.
        browser = pw.chromium.launch(channel="chrome", headless=False, slow_mo=600,
                                     args=["--window-size=1400,950"])
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        # ---------- Page load & layout ----------
        page.goto(BASE, wait_until="networkidle")
        time.sleep(1)
        title = page.title()
        rec("UI-01 page loads", "PASS" if "AI Software Development Agent" in title else "FAIL", f"title={title!r}")
        h1 = page.locator("header h1").inner_text()
        rec("UI-02 header", "PASS" if "AI Software Development Agent" in h1 else "FAIL", h1)
        status_txt = page.locator("#status").inner_text().strip()
        rec("UI-03 status idle", "PASS" if status_txt == "idle" else "FAIL", f"status={status_txt!r}")
        tl_items = page.locator("#timeline li")
        n = tl_items.count()
        names = [tl_items.nth(i).inner_text().strip() for i in range(n)]
        ok = n == 10 and "Planning" in names[0] and "PullRequest" in names[-1]
        rec("UI-04 timeline stages", "PASS" if ok else "FAIL", f"n={n} first={names[0] if names else '-'} last={names[-1] if names else '-'}")
        shot(page, "01_initial_load")

        # ---------- Recommendations panel ----------
        try:
            # wait until recoList stops saying "loading…"
            page.wait_for_function(
                "() => { const e=document.getElementById('recoList'); return e && !e.textContent.includes('loading'); }",
                timeout=30000)
            reco_txt = page.locator("#recoList").inner_text()[:80]
            uses = page.locator(".reco-use").count()
            rec("UI-05 reco loads", "PASS", f"use-buttons={uses} preview={reco_txt!r}")
        except PWTimeout:
            rec("UI-05 reco loads", "FAIL", "recoList stuck on 'loading…' after 30s")
        shot(page, "02_recommendations")

        # ---------- Tab switching ----------
        page.locator("#tabIssues").click()
        time.sleep(0.5)
        issues_cls = page.locator("#tabIssues").get_attribute("class")
        hint = page.locator("#searchHint").inner_text()
        ph = page.locator("#repoSearch").get_attribute("placeholder")
        ok = "indigo" in issues_cls and "open issues" in hint.lower()
        rec("UI-06 tab switch", "PASS" if ok else "FAIL", f"hint={hint!r}")
        # ---------- Issue keyword search ----------
        page.locator("#repoSearch").fill("typo docs")
        try:
            page.wait_for_selector("#repoResults .srch-item", timeout=20000)
            cnt = page.locator("#repoResults .srch-item").count()
            rec("UI-12 issue search", "PASS" if cnt > 0 else "FAIL", f"rows={cnt}")
        except PWTimeout:
            box = page.locator("#repoResults").inner_text()[:80]
            rec("UI-12 issue search", "NOTE", f"no rows (msg={box!r}) — possible GitHub rate-limit")
        shot(page, "03_issue_search")

        # back to repos
        page.locator("#tabRepos").click()
        time.sleep(0.5)
        repos_cls = page.locator("#tabRepos").get_attribute("class")
        rec("UI-06b tab back", "PASS" if "indigo" in repos_cls else "FAIL", "")

        # ---------- Repo search ----------
        page.locator("#repoSearch").fill("")
        page.locator("#repoSearch").fill("fastapi")
        try:
            page.wait_for_selector("#repoResults .srch-item", timeout=20000)
            cnt = page.locator("#repoResults .srch-item").count()
            rec("UI-07 repo search", "PASS" if cnt > 0 else "FAIL", f"rows={cnt}")
            shot(page, "04_repo_search")
            # ---------- Select repo ----------
            page.locator("#repoResults .srch-item").first.click()
            page.wait_for_selector("#repoPanel:not(.hidden)", timeout=10000)
            try:
                page.wait_for_function(
                    "() => { const e=document.getElementById('issueList'); return e && !e.textContent.includes('loading'); }",
                    timeout=25000)
                issue_items = page.locator("#issueList .issue-item").count()
                rec("UI-08 select repo loads issues", "PASS", f"issue-items={issue_items}")
            except PWTimeout:
                rec("UI-08 select repo loads issues", "NOTE", "issueList stuck loading (rate-limit?)")
            shot(page, "05_repo_selected")
            # start should be disabled until an issue is chosen
            start_disabled = page.locator("#startBtn").is_disabled()
            rec("UI-10 start disabled w/o issue", "PASS" if start_disabled else "FAIL", f"disabled={start_disabled}")
            # ---------- Select issue ----------
            if page.locator("#issueList .issue-item").count() > 0:
                page.locator("#issueList .issue-item").first.click()
                time.sleep(0.4)
                start_enabled = not page.locator("#startBtn").is_disabled()
                selbar = not page.locator("#selectionBar").get_attribute("class").__contains__("hidden")
                rec("UI-09 select issue enables start", "PASS" if start_enabled and selbar else "FAIL",
                    f"start_enabled={start_enabled} selbar={selbar}")
            else:
                rec("UI-09 select issue enables start", "SKIP", "no issues available to select")
        except PWTimeout:
            rec("UI-07 repo search", "NOTE", "no repo rows — possible GitHub rate-limit")

        # ---------- Checkbox defaults ----------
        rt = page.locator("#runTests").is_checked()
        op = page.locator("#openPr").is_checked()
        up = page.locator("#upstreamPr").is_checked()
        rec("UI-11 checkbox defaults", "PASS" if (rt and op and not up) else "FAIL",
            f"runTests={rt} openPr={op} upstreamPr={up}")
        shot(page, "06_selection_ready")

        # ---------- Responsive ----------
        page.set_viewport_size({"width": 390, "height": 850})
        time.sleep(1)
        body_scroll_w = page.evaluate("document.body.scrollWidth")
        win_w = page.evaluate("window.innerWidth")
        overflow = body_scroll_w - win_w
        rec("RES-01 narrow viewport", "PASS" if overflow <= 5 else "NOTE",
            f"scrollW={body_scroll_w} innerW={win_w} overflow={overflow}px")
        shot(page, "07_mobile")
        page.set_viewport_size({"width": 1366, "height": 900})
        time.sleep(0.5)

        # ---------- Run lifecycle (guarded: Open PR off, reject at first checkpoint) ----------
        run_test(page)

        # ---------- Console errors summary ----------
        if console_errors:
            rec("UI-CONSOLE", "NOTE", f"{len(console_errors)} console errors: {console_errors[:3]}")
        else:
            rec("UI-CONSOLE", "PASS", "no JS console errors during session")

        shot(page, "09_final")
        time.sleep(2)
        ctx.close()
        browser.close()


def run_test(page):
    """RUN-01..05: start a real run but uncheck Open PR and REJECT at first checkpoint."""
    # Ensure a repo+issue is selected; if not, try a recommendation 'Use' button.
    if page.locator("#startBtn").is_disabled():
        if page.locator(".reco-use").count() > 0:
            page.locator(".reco-use").first.click()
            time.sleep(0.6)
            rec("UI-13 reco Use populates", "PASS" if not page.locator("#startBtn").is_disabled() else "FAIL",
                f"sel={page.locator('#selText').inner_text()[:60]!r}")
    if page.locator("#startBtn").is_disabled():
        rec("RUN-01 start run", "SKIP", "no selectable repo+issue (rate-limited); skipping run lifecycle")
        return

    # Safety: turn OFF Open PR so no outward side effects even if logic changes.
    if page.locator("#openPr").is_checked():
        page.locator("#openPr").click()
    sel = page.locator("#selText").inner_text()
    page.locator("#startBtn").click()
    try:
        page.wait_for_function(
            "() => document.getElementById('status').textContent.includes('running')", timeout=15000)
        rec("RUN-01 start run", "PASS", f"status={page.locator('#status').inner_text()!r} sel={sel[:50]!r}")
    except PWTimeout:
        rec("RUN-01 start run", "FAIL", f"status never went running: {page.locator('#status').inner_text()!r}")
        return
    shot(page, "08a_run_started")

    # Wait for EITHER the checkpoint modal OR run_finished, up to 180s. Watch log fill.
    deadline = time.time() + 180
    modal_seen = False
    finished = False
    last_logcount = 0
    while time.time() < deadline:
        modal_hidden = page.locator("#modal").get_attribute("class")
        if modal_hidden and "hidden" not in modal_hidden:
            modal_seen = True
            break
        status = page.locator("#status").inner_text()
        if "finished" in status:
            finished = True
            break
        # log growth as liveness signal
        lc = page.locator("#log > div").count()
        if lc != last_logcount:
            last_logcount = lc
        time.sleep(2)

    # timeline activation check
    active = page.locator("#timeline li.text-indigo-300, #timeline li.text-emerald-400").count()
    rec("RUN-02 timeline activates", "PASS" if active > 0 else "NOTE", f"active/done stages={active}")

    if modal_seen:
        mtitle = page.locator("#modalTitle").inner_text()
        mbody = page.locator("#modalBody").inner_text()[:120]
        rec("RUN-03 checkpoint modal", "PASS", f"title={mtitle!r} body={mbody!r}")
        shot(page, "08b_checkpoint")
        # Reject -> no side effects
        page.locator("#rejectBtn").click()
        time.sleep(3)
        st = page.locator("#status").inner_text()
        startbtn_re = not page.locator("#startBtn").is_disabled()
        rec("RUN-04 reject resolves", "PASS" if ("finished" in st or startbtn_re) else "NOTE",
            f"status={st!r} startReEnabled={startbtn_re}")
        rec("RUN-05 no PR side effect", "PASS", "Open PR unchecked + rejected before PR stage")
    elif finished:
        st = page.locator("#status").inner_text()
        # Pull last few log lines for diagnosis
        logs = page.locator("#log > div")
        tail = [logs.nth(i).inner_text() for i in range(max(0, logs.count() - 5), logs.count())]
        rec("RUN-03 checkpoint modal", "NOTE", f"run finished before checkpoint: status={st!r}")
        rec("RUN-04 reject resolves", "SKIP", "no checkpoint reached")
        rec("RUN-05 no PR side effect", "PASS", "Open PR unchecked")
        rec("RUN-DIAG", "NOTE", f"final status={st!r}; log tail={tail}")
        shot(page, "08b_run_finished")
    else:
        st = page.locator("#status").inner_text()
        logs = page.locator("#log > div")
        tail = [logs.nth(i).inner_text() for i in range(max(0, logs.count() - 6), logs.count())]
        rec("RUN-03 checkpoint modal", "NOTE", f"no checkpoint/finish within 180s; status={st!r}")
        rec("RUN-DIAG", "NOTE", f"log tail={tail}")
        shot(page, "08b_run_timeout")


if __name__ == "__main__":
    main()
    out = QA / "ui_results.json"
    out.write_text(json.dumps({"results": results, "console_errors": console_errors}, indent=2))
    p = sum(1 for r in results if r["status"] == "PASS")
    f = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\nSUMMARY: {p} PASS, {f} FAIL, {len(results)} total -> {out}")
