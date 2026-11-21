"""Django 6's own CSP middleware and the nonce citry-django writes on an island.

The policy header names one nonce for the response. Every inline script of an
island has to carry that same nonce, or the browser blocks it. Skipped on
Django versions without `django.middleware.csp`.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client

from citry_django.registry import citry_app_source

csp = pytest.importorskip("django.utils.csp", reason="Django has no built-in CSP before 6.0")


@pytest.fixture
def django_csp(settings):
    settings.CITRY_APP = "events_site.app:app"
    settings.ROOT_URLCONF = "events_site.urls"
    settings.MIDDLEWARE = [
        *settings.MIDDLEWARE,
        "django.middleware.csp.ContentSecurityPolicyMiddleware",
    ]
    settings.SECURE_CSP = {"script-src": [csp.CSP.SELF, csp.CSP.NONCE]}
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


def header_nonce(response) -> str:
    match = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"])
    assert match is not None, response["Content-Security-Policy"]
    return match.group(1)


def inline_script_nonces(html: str) -> list[str | None]:
    """The `nonce` of each inline `<script>` (one with no `src`)."""
    found = []
    for attrs in re.findall(r"<script\b([^>]*)>", html):
        if " src=" in f" {attrs}":
            continue
        match = re.search(r'\bnonce="([^"]*)"', attrs)
        found.append(match.group(1) if match else None)
    return found


@pytest.mark.django_db
@pytest.mark.usefixtures("django_csp")
def test_an_islands_scripts_carry_the_nonce_in_djangos_policy_header():
    response = Client().get("/page/")
    assert response.status_code == 200
    nonce = header_nonce(response)

    scripts = inline_script_nonces(response.content.decode())
    assert scripts, "the page has inline scripts for its islands"
    assert set(scripts) == {nonce}


@pytest.mark.django_db
@pytest.mark.usefixtures("django_csp")
def test_each_response_gets_its_own_nonce():
    first, second = Client().get("/page/"), Client().get("/page/")
    assert header_nonce(first) != header_nonce(second)
    assert set(inline_script_nonces(second.content.decode())) == {header_nonce(second)}


@pytest.mark.django_db
@pytest.mark.usefixtures("django_csp")
def test_a_partial_carries_the_nonce_the_page_sent_not_its_own(settings):
    settings.CITRY_APP = "events_site.app:app"
    page = Client().get("/page/")
    page_nonce = header_nonce(page)

    partial = Client().get("/card/", HTTP_HX_REQUEST="true", HTTP_X_CITRY_PAGE_NONCE=page_nonce)
    # `card` is a view of the test site that applies its own policy only when
    # a test turns that on, so the header here is Django's.
    assert partial.status_code == 200
    own = header_nonce(partial)
    assert own != page_nonce
    scripts = [nonce for nonce in inline_script_nonces(partial.content.decode()) if nonce]
    assert scripts
    assert set(scripts) == {page_nonce}
