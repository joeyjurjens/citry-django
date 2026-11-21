"""Two Vue islands on one Django page, in a real browser.

Skipped unless Playwright is installed. Set PLAYWRIGHT_CHROMIUM_EXECUTABLE to
use a Chromium build other than the one Playwright expects.
"""

from __future__ import annotations

import os
import re

import pytest

from citry_django import csrf_settings
from citry_django.registry import citry_app_source
from events_site.app import app as events_app
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
def browser_context():
    """One visitor: tabs opened from it share cookies."""
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            )
        except sync_api.Error as error:
            pytest.skip(f"no Chromium for Playwright: {error}")
        try:
            yield browser.new_context()
        finally:
            browser.close()


@pytest.fixture
def browser_page(browser_context):
    return browser_context.new_page()


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


@pytest.mark.usefixtures("events_site")
def test_the_runtime_loads_through_the_mount_with_its_integrity(live_server, browser_page):
    """The page links Citry's runtime by content hash with `integrity`, and
    the browser fetches it gzipped through citry-django's mount and runs it.
    A body that differed from the pinned bytes would be refused and leave
    the islands unmounted."""
    page = browser_page
    problems: list[str] = []
    page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: problems.append(message.text) if message.type == "error" else None,
    )
    runtime: list[dict[str, str]] = []
    page.on(
        "response",
        lambda response: (
            runtime.append(response.all_headers())
            if re.search(r"/citry/citry\.[0-9a-f]{64}\.js$", response.url)
            else None
        ),
    )

    response = page.goto(f"{live_server.url}/page/")
    assert response is not None
    assert response.ok
    script = page.locator('script[src^="/citry/citry."]')
    assert script.count() == 1
    assert script.get_attribute("integrity").startswith("sha384-")
    assert script.get_attribute("crossorigin") == "anonymous"

    mounted = page.evaluate(
        "() => Array.from(document.querySelectorAll('[id^=\"citry-vue-\"]'))"
        ".map((host) => Boolean(host.__vue_app__))"
    )
    assert mounted == [True, True]
    assert len(runtime) == 1
    assert runtime[0]["content-encoding"] == "gzip"
    assert runtime[0]["cache-control"] == "public, max-age=31536000, immutable"
    assert problems == []


#: Citry's runtime, as the browser fetches it by content hash.
RUNTIME_URL = re.compile(r"/citry/citry\.[0-9a-f]{64}\.js$")


def watch(page) -> tuple[list[str], list[str]]:
    """Collect the page's errors and warnings, and each runtime fetch."""
    problems: list[str] = []
    runtime: list[str] = []
    page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: (
            problems.append(f"{message.type}: {message.text}")
            if message.type in {"error", "warning"}
            else None
        ),
    )
    page.on(
        "response",
        lambda response: runtime.append(response.url) if RUNTIME_URL.search(response.url) else None,
    )
    return problems, runtime


def mounted_hosts(page) -> list[bool]:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('[id^=\"citry-vue-\"]'))"
        ".map((host) => Boolean(host.__vue_app__))"
    )


def runtime_tags(page) -> int:
    return page.locator('script[src*="/citry/citry."]').count()


def swap_in_a_card(page) -> None:
    """Ask htmx for `/card/` and wait until its island has mounted."""
    page.locator("button.load").click()
    swapped = page.locator("#cards .counter button.bump")
    sync_api.expect(swapped).to_have_text("swapped: 0")
    page.wait_for_function(
        "() => Boolean(document.querySelector('#cards [id^=\"citry-vue-\"]')?.__vue_app__)"
    )


@pytest.mark.usefixtures("events_site")
def test_an_htmx_swap_mounts_an_island_on_a_page_that_has_the_runtime(live_server, browser_page):
    """htmx swaps in a partial holding an island. Its loader finds the
    runtime the page already loaded, and the runtime starts the island."""
    page = browser_page
    problems, runtime = watch(page)

    response = page.goto(f"{live_server.url}/swap/")
    assert response is not None
    assert response.ok
    assert mounted_hosts(page) == [True]

    swap_in_a_card(page)
    assert mounted_hosts(page) == [True, True]
    card = page.locator("#cards .counter")
    card.locator("button.bump").click()
    sync_api.expect(card.locator("button.bump")).to_have_text("bumped: 1")
    sync_api.expect(card.locator(".path")).to_have_text(re.compile(r"^/citry/ext/events/"))
    # The island the page started with still answers on its own.
    first = page.locator(".counter").first
    first.locator("button.bump").click()
    sync_api.expect(first.locator("button.bump")).to_have_text("bumped: 1")

    assert runtime_tags(page) == 1
    assert len(runtime) == 1
    assert problems == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Citry gap: a fragment's loader adds the core runtime but not the i18n "
        "browser plugin, so on a page that has not loaded it the runtime discards "
        "the fragment ('missing or incompatible Citry browser plugin: i18n'). The "
        "test site's app configures i18n."
    ),
)
@pytest.mark.usefixtures("events_site")
def test_an_htmx_swap_loads_the_runtime_into_a_page_without_one(live_server, browser_page):
    """On a page without any island, the partial's loader adds the runtime,
    once, and a second swap reuses it."""
    page = browser_page
    problems, runtime = watch(page)

    response = page.goto(f"{live_server.url}/plain/")
    assert response is not None
    assert response.ok
    assert runtime_tags(page) == 0

    swap_in_a_card(page)
    card = page.locator("#cards .counter")
    card.locator("button.bump").click()
    sync_api.expect(card.locator("button.bump")).to_have_text("bumped: 1")

    # A second swap replaces the island: the old app goes, the new one starts
    # on the runtime already there.
    swap_in_a_card(page)
    assert mounted_hosts(page) == [True]
    page.locator("#cards .counter button.bump").click()
    sync_api.expect(page.locator("#cards .counter button.bump")).to_have_text("bumped: 1")

    assert runtime_tags(page) == 1
    assert len(runtime) == 1
    assert problems == []


@pytest.fixture
def csp(settings):
    """A nonce-based Content Security Policy on the test site's pages.

    The live server built its middleware when it started, so the site's views
    apply the policy themselves (see `events_site.urls.with_csp`).
    """
    settings.EVENTS_SITE_CSP = True


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("events_site", "csp")
def test_an_htmx_swap_under_a_csp_carries_the_page_nonce(live_server, browser_page):
    """The partial's own response has a nonce of its own, which no page in
    the browser has. Its island carries the nonce of the page it lands in,
    which citry-django kept when it rendered that page, so the runtime
    starts it and the browser runs its loader."""
    page = browser_page
    problems, runtime = watch(page)

    response = page.goto(f"{live_server.url}/swap/")
    assert response is not None
    assert response.ok
    policy = response.all_headers()["content-security-policy"]
    assert "'nonce-" in policy
    assert mounted_hosts(page) == [True]

    swap_in_a_card(page)
    card = page.locator("#cards .counter")
    card.locator("button.bump").click()
    sync_api.expect(card.locator("button.bump")).to_have_text("bumped: 1")

    assert runtime_tags(page) == 1
    assert len(runtime) == 1
    # A refused nonce shows up here: the browser blocking the loader, or the
    # runtime refusing the island's data block.
    assert problems == []


@pytest.mark.usefixtures("events_site")
@pytest.mark.parametrize(
    "overrides",
    [
        {"CSRF_COOKIE_NAME": "mytoken", "CSRF_HEADER_NAME": "HTTP_X_MY_CSRF"},
        {"CSRF_COOKIE_HTTPONLY": True},
    ],
    ids=["renamed", "httponly"],
)
def test_server_events_pass_django_csrf_when_its_settings_are_not_the_defaults(
    live_server, browser_page, settings, overrides, monkeypatch
):
    """Citry's runtime reads the default cookie and header unless the app's
    Events settings name others, and an event Django refuses would never
    re-render. The app maps Django's settings with `csrf_settings()`, as a
    project does when it builds its app."""
    for name, value in overrides.items():
        setattr(settings, name, value)
    events = {**events_app.settings.extensions_defaults["events"], **csrf_settings()}
    monkeypatch.setitem(events_app.settings.extensions_defaults, "events", events)
    page = browser_page
    statuses: list[int] = []
    page.on(
        "response",
        lambda response: (
            statuses.append(response.status) if "/ext/events/" in response.url else None
        ),
    )

    response = page.goto(f"{live_server.url}/page/")
    assert response is not None
    assert response.ok
    first = page.locator(".counter").first
    first.locator("button.bump").click()
    sync_api.expect(first.locator("button.bump")).to_have_text("bumped: 1")
    assert statuses
    assert set(statuses) == {200}


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("events_site", "csp")
def test_an_htmx_swap_in_an_older_tab_carries_that_tabs_nonce(live_server, browser_context):
    """Two tabs of one visitor, each with its own nonce. The session keeps one
    nonce, the last page's, so a swap in the first tab used to be written with
    the second tab's nonce and the first tab's CSP refused it. The page sends
    its own nonce with the request now."""
    first = browser_context.new_page()
    problems, _ = watch(first)
    first.goto(f"{live_server.url}/swap/")
    assert mounted_hosts(first) == [True]

    # The same visitor (one cookie jar) opens the page again in another tab.
    second = browser_context.new_page()
    second.goto(f"{live_server.url}/swap/")
    assert mounted_hosts(second) == [True]

    swap_in_a_card(first)
    card = first.locator("#cards .counter")
    card.locator("button.bump").click()
    sync_api.expect(card.locator("button.bump")).to_have_text("bumped: 1")
    assert problems == []
