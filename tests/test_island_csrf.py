"""A page that holds an island makes Django send the CSRF cookie.

Citry's Events calls pass Django's own CSRF check, which needs the cookie,
and a page without a form never asks Django for it.
"""

from __future__ import annotations

import pytest
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware


@pytest.fixture(autouse=True)
def fixtures(component):
    component(
        "<b>live</b>",
        name="csrf-live",
        js_data=lambda self, kwargs, slots: {"on": True},
    )
    component("<i>still</i>", name="csrf-still")
    component("<ul>{% for n in ns %}<li><c-csrf-live/></li>{% endfor %}</ul>", name="csrf-loop")


def cookie_sent(request, html: str) -> bool:
    """Whether Django's CSRF middleware would set the cookie on this response."""
    middleware = CsrfViewMiddleware(lambda request: HttpResponse(html))
    response = middleware(request)
    return "csrftoken" in response.cookies


def test_a_region_with_an_island_asks_for_the_token(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-live/>", request=request)
    assert cookie_sent(request, html)


def test_a_static_region_does_not(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-still/>", request=request)
    assert not cookie_sent(request, html)


def test_an_island_in_a_django_block_asks_for_the_token(render, rf):
    request = rf.get("/")
    html = render("<c-csrf-loop c-ns='[1]'/>", request=request)
    assert cookie_sent(request, html)


def test_the_token_is_not_written_into_the_page(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-live/>", request=request)
    assert request.META["CSRF_COOKIE"] not in html


def test_an_island_in_a_django_block_of_a_region_asks_for_the_token(render_django, rf):
    """The region itself needs no Vue here; only the islands its Django
    block builds once the region has rendered do."""
    request = rf.get("/")
    html = render_django("<c-csrf-loop c-ns='[1]'/>", request=request)
    assert cookie_sent(request, html)


def configured(html: str) -> dict | None:
    """What the page tells Citry's runtime about the CSRF token, if anything."""
    import json
    import re

    match = re.search(r"\}\)\((\{.*?\})\);</script>", html)
    return None if match is None else json.loads(match.group(1))


def test_default_settings_write_no_csrf_script(render_django, rf):
    html = render_django("<c-csrf-live/>", request=rf.get("/"))
    assert "k.configure(c)" not in html


def test_a_renamed_cookie_and_header_are_given_to_the_runtime(render_django, rf, settings):
    settings.CSRF_COOKIE_NAME = "mytoken"
    settings.CSRF_HEADER_NAME = "HTTP_X_MY_CSRF"
    html = render_django("<c-csrf-live/>", request=rf.get("/"))
    assert configured(html) == {"csrf": {"header": "X-MY-CSRF", "cookie": "mytoken"}}


def test_a_cookie_a_script_cannot_read_gives_the_runtime_the_token(render_django, rf, settings):
    settings.CSRF_COOKIE_HTTPONLY = True
    request = rf.get("/")
    html = render_django("<c-csrf-live/>", request=request)
    config = configured(html)
    assert config is not None
    assert config["csrf"]["token"]
    assert "cookie" not in config["csrf"]


def test_the_script_carries_the_pages_nonce(render_django, rf, settings):
    settings.CSRF_USE_SESSIONS = True
    request = rf.get("/")
    request.session = {}
    request.csp_nonce = "abc123"
    html = render_django("<c-csrf-live/>", request=request)
    assert '<script nonce="abc123">(function(c)' in html


def test_an_island_in_a_django_block_gets_it_too(render, rf, settings):
    settings.CSRF_COOKIE_NAME = "mytoken"
    html = render("<c-csrf-loop c-ns='[1]'/>", request=rf.get("/"))
    assert configured(html) == {"csrf": {"cookie": "mytoken"}}


def test_a_static_region_gets_none(render_django, rf, settings):
    settings.CSRF_COOKIE_NAME = "mytoken"
    assert configured(render_django("<c-csrf-still/>", request=rf.get("/"))) is None
