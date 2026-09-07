"""FRONTEND-OBSERVABILITY-V1.2 browser E2E (Playwright, real Chrome channel).

§19 mandatory sequence: open / -> Overview; click navigation; direct hash;
back/forward; reload on a hash route; auto-refresh preserves route;
console errors == 0.  Serves the SPA from a local ThreadingHTTPServer bound
to REAL campaign artifacts (poc01-execution worktree when present) so the
assertions exercise the same DOM/JS the user sees.

Run: uv run pytest tests/e2e/test_browser_v1_2.py -q
Skips cleanly if Playwright/Chrome is unavailable in the environment.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from trading_bot.frontend_observability import projections
from trading_bot.frontend_observability.server import create_server

REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_REPORTS = REPO_ROOT.parent / "poc01-execution" / "reports"

playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
sync_playwright = playwright.sync_playwright


def _chrome_available() -> bool:
    return Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists()


requires_chrome = pytest.mark.skipif(not _chrome_available(), reason="Chrome channel not installed")


@pytest.fixture(scope="module")
def base_url() -> str:
    """Serve the SPA bound to real campaign artifacts (live worktree preferred)."""
    if (_MAIN_REPORTS / "paper-observation-01").is_dir():
        root = _MAIN_REPORTS
    else:
        pytest.skip("no real campaign artifacts available for browser E2E")
    projections.configure_source(reports_root=root)
    srv = create_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    yield url
    srv.shutdown()
    srv.server_close()
    projections.configure_source(reports_root=None, campaign_api=None)


@pytest.fixture(scope="module")
def ctx(base_url: str):
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page()
        errors: list[str] = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        yield pg, errors, base_url
        b.close()


def _tab(pg: Any) -> str:
    return pg.eval_on_selector("nav a.on", "el=>el.dataset.t")


def _panels(pg: Any) -> list[str]:
    return pg.evaluate("[...document.querySelectorAll('section.on')].map(s=>s.id)")


@requires_chrome
def test_e2e_full_navigation_sequence(ctx) -> None:
    pg, errors, base = ctx

    # 1. open / -> Overview visible
    pg.goto(base + "/", wait_until="networkidle")
    time.sleep(1.0)
    assert _tab(pg) == "overview"
    assert _panels(pg) == ["s-overview"]

    # 2. click through every tab: hash == tab == panel
    for t in ("funnel", "agents", "strategies", "assets", "decisions", "trades", "reports", "replay"):
        pg.click(f'nav a[data-t="{t}"]')
        time.sleep(0.25)
        assert pg.evaluate("location.hash") == f"#{t}", t
        assert _tab(pg) == t, t
        assert _panels(pg) == [f"s-{t}"], t

    # 3. Trades shows >=1 real campaign trade
    pg.click('nav a[data-t="trades"]')
    time.sleep(0.25)
    rows = pg.eval_on_selector_all("#tr-closed table tr", "els=>els.length")
    assert rows >= 2, "real campaign trades must be visible at #trades (header + rows)"

    # 4. browser back -> previous route restored
    pg.go_back()
    time.sleep(0.3)
    assert pg.evaluate("location.hash") == "#replay"
    assert _tab(pg) == "replay"

    # 5. browser forward -> route restored
    pg.go_forward()
    time.sleep(0.3)
    assert pg.evaluate("location.hash") == "#trades"
    assert _tab(pg) == "trades"

    # 6. reload on #trades -> Trades remains active
    pg.reload(wait_until="networkidle")
    time.sleep(1.0)
    assert pg.evaluate("location.hash") == "#trades"
    assert _tab(pg) == "trades"
    assert _panels(pg) == ["s-trades"]

    # 7. manual Refresh preserves route
    pg.click("#refresh")
    time.sleep(0.8)
    assert pg.evaluate("location.hash") == "#trades"
    assert _tab(pg) == "trades"

    # 8. auto-refresh preserves route (wait past the 30s cycle)
    pg.check("#auto")
    h1 = pg.evaluate("location.hash")
    time.sleep(31)
    assert pg.evaluate("location.hash") == h1 == "#trades"
    assert _tab(pg) == "trades"
    pg.uncheck("#auto")

    # 9. console errors == 0 across the whole sequence
    assert errors == [], errors


@requires_chrome
def test_e2e_unknown_hash_falls_back(ctx) -> None:
    pg, errors, base = ctx
    pg.goto(base + "/#bogus", wait_until="domcontentloaded")
    time.sleep(0.8)
    assert pg.evaluate("location.hash") in ("", "#overview")  # replaced safely
    assert _tab(pg) == "overview"
    assert _panels(pg) == ["s-overview"]
    assert errors == []


@requires_chrome
def test_e2e_direct_hash_routes(ctx) -> None:
    pg, errors, base = ctx
    for t in ("strategies", "decisions", "assets"):
        pg.goto(base + "/#" + t, wait_until="networkidle")
        time.sleep(0.8)
        assert pg.evaluate("location.hash") == f"#{t}"
        assert _tab(pg) == t
        assert _panels(pg) == [f"s-{t}"]
    assert errors == []


@requires_chrome
def test_e2e_live_campaign_identity_visible(ctx) -> None:
    pg, errors, base = ctx
    pg.goto(base + "/", wait_until="networkidle")
    time.sleep(1.2)
    badge = pg.text_content("#badge-campaign")
    assert "poc01-paper-observation-01-001" in badge
    assert "ACTIVE" in badge
    assert "REAL PUBLIC MARKET" in pg.text_content("#badge-data")
    assert "LIVE DISABLED" in pg.text_content("#badge-live")
    src = pg.text_content("#src")
    assert "DATA_SOURCE" in src and "REPORTS_ROOT" in src
    assert errors == []


@requires_chrome
def test_e2e_funnel_and_reports_populated(ctx) -> None:
    pg, errors, base = ctx
    pg.goto(base + "/#funnel", wait_until="networkidle")
    time.sleep(1.2)
    scans = pg.eval_on_selector_all("#fun .frow", "els=>els.length")
    assert scans >= 9, "all canonical funnel rows must render"
    pg.goto(base + "/#reports", wait_until="networkidle")
    time.sleep(1.0)
    links = pg.eval_on_selector_all("#rpEl a", "els=>els.map(e=>e.textContent)")
    assert links, "campaign reports must be listed"
    assert any("CAMPAIGN_REPORT" in str(link) for link in links)
    assert all("poc01-paper-observation-01-001" in str(link) for link in links), links
    assert errors == []
