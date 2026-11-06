"""End-to-end: real uvicorn server in DEMO mode + headless Chromium driving the frontend."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("CHROMIUM_PATH") or next(
    (str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    tmp = tmp_path_factory.mktemp("e2e")
    env = {**os.environ, "DEMO_MODE": "true", "PORT": str(port), "HOST": "127.0.0.1",
           "USER_WATCHLIST_FILE": str(tmp / "wl.json"), "ANTHROPIC_API_KEY": ""}
    proc = subprocess.Popen([sys.executable, str(ROOT / "run.py")], env=env, cwd=str(tmp),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(base + "/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("server did not start: " + proc.stdout.read().decode()[-2000:])
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        kwargs = {"executable_path": CHROMIUM} if CHROMIUM else {}
        try:
            b = p.chromium.launch(**kwargs)
        except Exception as exc:  # no browser installed on this machine
            pytest.skip(f"Chromium unavailable: {exc}")
        yield b
        b.close()


def _page(browser, viewport):
    page = browser.new_page(viewport=viewport)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    return page, errors


def test_watchlist_renders_from_api_and_shows_demo_label(server, browser):
    page, errors = _page(browser, {"width": 1400, "height": 900})
    page.goto(server + "/#/watchlist")
    page.wait_for_selector("#wl-table tbody tr[data-sym]")
    rows = page.locator("#wl-table tbody tr[data-sym]")
    assert rows.count() == 22
    assert "DEMO" in page.locator("#mode-badge").inner_text()
    assert "DEMO MODE" in page.locator(".banner").first.inner_text()
    api_top = httpx.get(server + "/api/watchlist").json()["rows"][0]["symbol"]
    assert rows.first.get_attribute("data-sym") == api_top
    page.click("[data-group=technical]")
    assert page.locator("th[data-sort=hh_15m]").count() == 1
    page.select_option("#f-signal", "BUY")
    assert all(page.locator("#wl-table tbody tr[data-sym] .pill").all_inner_texts()[i] == "BUY"
               for i in range(page.locator("#wl-table tbody tr[data-sym] .pill").count()))
    page.wait_for_selector("#live-badge:not(.hidden)", timeout=10000)
    assert not errors, errors


def test_stock_page_chart_scores_and_ai(server, browser):
    page, errors = _page(browser, {"width": 1400, "height": 900})
    page.goto(server + "/#/stock/INFY")
    page.wait_for_selector("#chart-box canvas")
    page.wait_for_function("document.getElementById('chart-src').textContent.includes('bars')")
    assert page.locator(".bar-row").count() == 9
    page.locator(".bar-row").first.click()
    assert page.locator("table.factors:not(.hidden)").count() >= 1
    page.click("[data-tf='15m']")
    page.wait_for_function("document.getElementById('chart-src').textContent.includes('bars')")
    page.click("#ai-run")
    page.wait_for_selector(".ai-section.ai")
    text = page.locator("#ai-body").inner_text()
    assert "DEMO DATA" in text and "CALCULATED DATA" in text and "AI INTERPRETATION" in text
    assert not errors, errors


def test_mobile_layout_uses_cards(server, browser):
    page, errors = _page(browser, {"width": 390, "height": 844})
    page.goto(server + "/#/watchlist")
    page.wait_for_selector("#wl-cards .mcard")
    assert page.locator("#wl-cards .mcard").count() == 22
    assert not page.locator("#wl-table").is_visible()
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"horizontal overflow: {width}px"
    page.locator("#wl-cards .mcard").first.click()
    page.wait_for_selector("#chart-box canvas")
    assert not errors, errors


def test_settings_page_shows_status_without_secrets(server, browser):
    page, errors = _page(browser, {"width": 1200, "height": 900})
    page.goto(server + "/#/settings")
    page.wait_for_selector("#settings")
    body = page.locator("main").inner_text()
    assert "disabled (decision support only)" in body
    assert not errors, errors


@pytest.fixture(scope="module")
def split_origin(tmp_path_factory):
    """Frontend on one origin, API on another - the same shape as the Android app talking to a PC server."""
    api_port, web_port = _free_port(), _free_port()
    tmp = tmp_path_factory.mktemp("split")
    env = {**os.environ, "DEMO_MODE": "true", "PORT": str(api_port), "HOST": "127.0.0.1",
           "USER_WATCHLIST_FILE": str(tmp / "wl.json"), "CORS_ORIGINS": f"http://localhost:{web_port}"}
    api = subprocess.Popen([sys.executable, str(ROOT / "run.py")], env=env, cwd=str(tmp),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen([sys.executable, "-m", "http.server", str(web_port), "--bind", "127.0.0.1",
                            "--directory", str(ROOT / "frontend")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{api_port}/health", timeout=1)
            httpx.get(f"http://127.0.0.1:{web_port}/index.html", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.25)
    yield f"http://127.0.0.1:{api_port}", f"http://localhost:{web_port}"
    for p in (api, web):
        p.terminate()
        p.wait(timeout=10)


def test_remote_api_base_like_android(split_origin, browser):
    api, web = split_origin
    page, errors = _page(browser, {"width": 390, "height": 844})
    page.add_init_script(f"localStorage.setItem('swing.prefs.v1', JSON.stringify({{apiBase: '{api}', liveQuotes: true}}))")
    page.goto(web + "/index.html#/watchlist")
    page.wait_for_selector("#wl-cards .mcard")
    assert page.locator("#wl-cards .mcard").count() == 22
    page.wait_for_selector("#live-badge.live", timeout=10000)
    assert not errors, errors


def test_cors_rejects_unknown_origin(split_origin):
    api, _ = split_origin
    r = httpx.get(api + "/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
