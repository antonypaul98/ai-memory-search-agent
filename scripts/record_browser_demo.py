#!/usr/bin/env python3
"""Record a real Chromium session exercising an unmocked local Memory Agent."""
import json
import os
import shutil
import sys
import time
import traceback
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
ROOT = Path("artifacts/browser-demo")
TITLE = "TEST DATA — Recovering From Agent Tool Failures"
ID = "demo-agent-tool-recovery"
SEARCH = "agent tool timeout retry with exponential backoff"
ASK = "What should an agent do after a tool timeout?"

def wait_for_server():
    for _ in range(60):
        try:
            with urllib.request.urlopen(BASE + "/api/v1/ready", timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise AssertionError("FastAPI /ready did not return 200")

def main():
    if os.getenv("MEMORY_AGENT_DEMO_E2E") != "1":
        raise RuntimeError("Refusing to record outside isolated demo mode")
    for directory in [ROOT, ROOT/"screenshots", ROOT/"raw"]:
        directory.mkdir(parents=True, exist_ok=True)
    results, errors, output_video = [], [], None

    def verify(name, fn):
        try:
            fn()
            results.append({"step": name, "pass": True})
            print("PASS", name, flush=True)
        except Exception as error:
            results.append({"step": name, "pass": False, "reason": str(error)})
            errors.append(f"{name}: {error}")
            print("FAIL", name, str(error)[:300], flush=True)
            return False

    try:
        verify("Server readiness", wait_for_server)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(ROOT/"raw"),
                record_video_size={"width": 1440, "height": 900},
            )
            page = context.new_page()
            video = page.video
            try:
                def dashboard():
                    page.goto(BASE + "/#dashboard", wait_until="domcontentloaded")
                    page.locator("#view-dashboard .stat-card").first.wait_for(timeout=35000)
                    assert page.locator("#view-dashboard .stat-card").count() >= 3
                    page.screenshot(path=str(ROOT/"screenshots"/"01-dashboard.png"))
                    page.wait_for_timeout(1600)
                verify("Dashboard displayed from running API", dashboard)

                def retrieve():
                    response = page.request.get(BASE + "/api/v1/intelligence/retrieve", params={"q": SEARCH, "limit": 10}, timeout=120000)
                    assert response.ok, f"HTTP {response.status}: {response.text()[:200]}"
                    hits = response.json()["results"]
                    assert any(hit["result"]["video_id"] == ID for hit in hits), f"Expected evidence absent: {hits[:1]}"
                verify("Actual semantic retrieval finds stored vector", retrieve)

                def ui_search():
                    page.locator('.nav-link[data-route="search"]').click()
                    page.locator("#search-q").fill(SEARCH)
                    page.locator("#search-btn").click()
                    page.locator("#search-results .result-card", has_text=TITLE).first.wait_for(timeout=35000)
                    page.screenshot(path=str(ROOT/"screenshots"/"02-semantic-search.png"))
                    page.wait_for_timeout(2300)
                verify("Browser search renders matched passage", ui_search)

                def detail():
                    page.locator("#search-results .result-card", has_text=TITLE).first.locator("button[data-open]").click()
                    page.locator("#view-memory h2", has_text=TITLE).first.wait_for(timeout=35000)
                    assert "automated fixture" in page.locator("#view-memory").inner_text().lower()
                    page.screenshot(path=str(ROOT/"screenshots"/"03-memory-detail.png"))
                    page.wait_for_timeout(2100)
                verify("Source detail resolves persisted memory", detail)

                def chat_api():
                    response = page.request.post(BASE + "/api/v1/chat", data={"question": ASK, "top_k": 6}, timeout=120000)
                    assert response.ok, f"HTTP {response.status}: {response.text()[:200]}"
                    body = response.json()
                    assert body.get("grounded") is True, f"Ungrounded answer: {body.get('answer', '')[:150]}"
                    assert any(hit.get("video_id") == ID for hit in body.get("sources", [])), "No cited source ID"
                verify("Backend grounded answer includes actual citation", chat_api)

                def ui_ask():
                    page.locator('.nav-link[data-route="ask"]').click()
                    page.locator("#ask-q").fill(ASK)
                    page.locator("#ask-btn").click()
                    page.locator("#ask-answer .answer-card").wait_for(timeout=35000)
                    assert TITLE in page.locator("#ask-answer").inner_text(), "Fixture absent from evidence list"
                    assert page.locator("#ask-answer .answer-body").inner_text().strip()
                    page.screenshot(path=str(ROOT/"screenshots"/"04-ask-cited-answer.png"))
                    page.wait_for_timeout(2800)
                verify("Browser Ask shows answer and source evidence", ui_ask)
            except Exception:
                errors.append(traceback.format_exc()[-4000:])
                try:
                    page.screenshot(path=str(ROOT/"screenshots"/"ERROR.png"))
                except Exception:
                    pass
            finally:
                context.close()
                try:
                    path = Path(video.path())
                    dest = ROOT / "memory-agent-browser-demo.webm"
                    shutil.copy2(path, dest)
                    output_video = str(dest)
                except Exception as exc:
                    errors.append("Video flush failed: " + str(exc))
                browser.close()
    except Exception:
        errors.append(traceback.format_exc()[-4000:])
    if not output_video or not Path(output_video).is_file() or Path(output_video).stat().st_size <= 0:
        errors.append("No non-empty browser recording")
    passed = len(results) == 7 and all(r["pass"] for r in results) and not errors
    report = {
        "passed": passed, "checks": results, "errors": errors,
        "video": output_video, "data": "isolated synthetic fixtures, NOT live YouTube",
        "browser": "real Playwright Chromium", "backend": "unmocked local FastAPI and persisted Chroma",
        "limitations": ["no live YouTube network ingest", "no Watch Later OAuth", "no Mac camera",
                        "flat retrieval only; hierarchical path is not covered"],
    }
    (ROOT/"results.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    lines = ["# Memory Agent recorded browser test", "", "PASS" if passed else "FAIL",
             "", "Real Chromium + real backend; synthetic clearly labeled source fixtures.", "",
             *[("- PASS " if x["pass"] else "- FAIL ") + x["step"] for x in results],
             "", "Not tested: live YouTube ingest, OAuth, physical Mac, hierarchical pipeline."]
    if errors:
        lines += ["", "## Error", "See results.json for traceback."]
    (ROOT/"RESULTS.md").write_text("\n".join(lines)+"\n", encoding="utf8")
    print("\n".join(lines), flush=True)
    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())
