"""Two Vue islands on one Django page, in a real browser.

Skipped unless Playwright is installed. Set PLAYWRIGHT_CHROMIUM_EXECUTABLE to
use a Chromium build other than the one Playwright expects.
"""

from __future__ import annotations

import os
import re

import pytest

from citry_django.registry import citry_app_source
from events_site.urls import NOTE
from islands import islands, runtime_scripts

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def events_site(settings, monkeypatch):
    settings.CITRY_APP = "events_site.app:app"
    settings.ROOT_URLCONF = "events_site.urls"
    # Playwright's sync API runs an event loop on this thread, and Django
    # refuses database work from a thread with a running loop.
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


@pytest.fixture
def browser_page():
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            )
        except sync_api.Error as error:
            pytest.skip(f"no Chromium for Playwright: {error}")
        try:
            yield browser.new_page()
        finally:
            browser.close()


@pytest.mark.usefixtures("events_site")
def test_two_islands_hydrate_and_answer_server_events(live_server, browser_page):
    page = browser_page
    problems: list[str] = []
    page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: (
            problems.append(f"{message.type}: {message.text}")
            if message.type in {"error", "warning"}
            else None
        ),
    )

    response = page.goto(f"{live_server.url}/page/")
    assert response is not None
    assert response.ok
    html = response.text()
    assert runtime_scripts(html) == 1
    assert len(islands(html)) == 2

    # Both islands mounted as Vue apps on their own hosts.
    mounted = page.evaluate(
        "() => Array.from(document.querySelectorAll('[id^=\"citry-vue-\"]'))"
        ".map((host) => Boolean(host.__vue_app__))"
    )
    assert mounted == [True, True]

    first, second = page.locator(".counter").all()
    # Each island answers its own click with a server event whose Render
    # re-renders the component with Django's request values.
    first.locator("button.bump").click()
    sync_api.expect(first.locator("button.bump")).to_have_text("bumped: 1")
    sync_api.expect(second.locator("button.bump")).to_have_text("second: 0")
    second.locator("button.bump").click()
    sync_api.expect(second.locator("button.bump")).to_have_text("bumped: 1")
    sync_api.expect(first.locator(".path")).to_have_text(re.compile(r"/citry/ext/events/"))

    # Vue adopted the server HTML: no hydration mismatch, and nothing failed.
    assert problems == []


@pytest.mark.usefixtures("events_site")
def test_fills_with_django_tags_hydrate_and_answer_server_events(live_server, browser_page):
    """A modal filled by a Django template, and a panel whose re-render
    rebuilds a fill with Django tags, in a real browser."""
    page = browser_page
    problems: list[str] = []
    page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: (
            problems.append(f"{message.type}: {message.text}")
            if message.type in {"error", "warning"}
            else None
        ),
    )

    response = page.goto(f"{live_server.url}/fills/")
    assert response is not None
    assert response.ok
    assert len(islands(response.text())) == 2
    mounted = page.evaluate(
        "() => Array.from(document.querySelectorAll('[id^=\"citry-vue-\"]'))"
        ".map((host) => Boolean(host.__vue_app__))"
    )
    assert mounted == [True, True]

    modal, panel = page.locator(".modal").first, page.locator(".panel")
    sync_api.expect(modal.locator(".hello")).to_have_text("Hello")
    # The visitor's text is text: Vue never compiled it, and its markup is
    # not markup.
    sync_api.expect(modal.locator(".note")).to_have_text(NOTE)
    assert modal.locator(".note img").count() == 0
    assert page.evaluate("() => window.injected") is None

    # The panel's server event renders Help again, and Django renders the
    # modal's fill again for that request.
    panel.locator("button.bump").click()
    sync_api.expect(panel.locator("button.bump")).to_have_text("1")
    sync_api.expect(panel.locator(".guide")).to_have_text("Read the guide")
    sync_api.expect(panel.locator(".path")).to_have_text(re.compile(r"^/citry/ext/events/"))

    # The modal's own handler returns a new modal without the fill the page
    # wrote, so it shows its fallback.
    modal.locator("button.close").click()
    sync_api.expect(modal.locator("h2")).to_have_text("closed")
    sync_api.expect(modal).to_contain_text("fallback")

    # Vue adopted the server HTML: no hydration mismatch, and nothing failed.
    assert problems == []
