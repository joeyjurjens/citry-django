"""A page that holds an island with server events makes Django send the CSRF cookie.

Citry's Events calls pass Django's own CSRF check, which needs the cookie,
and a page without a form never asks Django for it. An island whose render
Citry says needs no token (`needs_csrf_token()`) never makes such a call, so
it leaves the cookie, and the page's cacheability, alone.

Django's CSRF names reach Citry's browser code through Citry's own
`_csrf_cookie` and `_csrf_header` Events settings, which `csrf_settings()`
maps from Django's settings.
"""

from __future__ import annotations

import json
import re

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware

from citry_django import csrf_settings


@pytest.fixture(autouse=True)
def fixtures(component, citry_app):
    # Components with server events need Citry's routes mounted.
    previous = citry_app.mounted_prefix
    citry_app.set_mounted_prefix("/citry")
    yield from _define(component)
    citry_app._mounted_prefix = previous


def _define(component):
    class Events:
        def go(self):
            return None

    component(
        '<b @c-click="go">live</b>',
        name="csrf-live",
        js_data=lambda self, kwargs, slots: {"on": True},
        Events=Events,
    )
    # Needs Vue, has no server events.
    component(
        '<b @click="n++">quiet</b>',
        name="csrf-quiet",
        js_data=lambda self, kwargs, slots: {"n": 0},
    )
    component(
        "<ul>{% for n in ns %}<li><c-csrf-quiet/></li>{% endfor %}</ul>", name="csrf-quiet-loop"
    )
    component("<i>still</i>", name="csrf-still")
    component("<ul>{% for n in ns %}<li><c-csrf-live/></li>{% endfor %}</ul>", name="csrf-loop")
    yield


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
    """What the page's own script tells Citry's runtime about the CSRF token, if anything."""
    match = re.search(r"\}\)\((\{.*?\})\);</script>", html)
    return None if match is None else json.loads(match.group(1))


def block_names(html: str) -> dict | None:
    """The CSRF names Citry wrote into the island's configuration block, if any."""
    match = re.search(r'"csrfNames":(\{[^}]*\})', html)
    return None if match is None else json.loads(match.group(1))


@pytest.fixture
def app_events(citry_app, monkeypatch):
    """Set the test app's Events settings, as a project does when it builds its app."""

    def set_events(events: dict) -> None:
        monkeypatch.setitem(citry_app.settings.extensions_defaults, "events", events)

    return set_events


def partial(rf, nonce=None):
    request = rf.get("/", HTTP_HX_REQUEST="true")
    if nonce is not None:
        request.csp_nonce = nonce
    return request


def test_django_defaults_map_to_nothing(settings):
    assert csrf_settings() == {}


def test_renamed_names_map_to_citrys_settings(settings):
    settings.CSRF_COOKIE_NAME = "mytoken"
    settings.CSRF_HEADER_NAME = "HTTP_X_MY_CSRF"
    assert csrf_settings() == {"_csrf_cookie": "mytoken", "_csrf_header": "X-MY-CSRF"}


@pytest.mark.parametrize("hidden", ["CSRF_USE_SESSIONS", "CSRF_COOKIE_HTTPONLY"])
def test_a_token_no_script_can_read_maps_to_no_cookie(settings, hidden):
    setattr(settings, hidden, True)
    settings.CSRF_COOKIE_NAME = "mytoken"
    assert csrf_settings() == {"_csrf_cookie": None}


def test_citry_accepts_the_mapped_settings(settings):
    from citry import Citry

    settings.CSRF_COOKIE_NAME = "__Host-csrftoken"
    settings.CSRF_HEADER_NAME = "HTTP_X_XSRF_TOKEN"
    Citry(autodiscover=False, extensions_defaults={"events": csrf_settings()})


def test_default_settings_write_no_csrf_script(render_django, rf):
    html = render_django("<c-csrf-live/>", request=rf.get("/"))
    assert "k.configure(c)" not in html
    assert block_names(html) is None


def test_renamed_names_reach_the_configuration_block_without_a_script(
    render_django, rf, settings, app_events
):
    settings.CSRF_COOKIE_NAME = "mytoken"
    settings.CSRF_HEADER_NAME = "HTTP_X_MY_CSRF"
    app_events(csrf_settings())
    html = render_django("<c-csrf-live/>", request=rf.get("/"))
    assert block_names(html) == {"cookie": "mytoken", "header": "X-MY-CSRF"}
    assert configured(html) is None


def test_renamed_names_the_app_does_not_set_are_refused(render_django, rf, settings, app_events):
    """Citry's browser code would read the wrong cookie, and every server
    event would fail Django's check with a 403."""
    settings.CSRF_HEADER_NAME = "HTTP_X_MY_CSRF"
    app_events({})
    with pytest.raises(ImproperlyConfigured, match="'_csrf_header'"):
        render_django("<c-csrf-live/>", request=rf.get("/"))


def test_names_the_app_sets_itself_win(render_django, rf, settings, app_events):
    settings.CSRF_COOKIE_NAME = "mytoken"
    app_events({**csrf_settings(), "_csrf_cookie": "theirs"})
    html = render_django("<c-csrf-live/>", request=rf.get("/"))
    assert block_names(html) == {"cookie": "theirs"}


def test_an_island_without_events_is_not_refused(render_django, rf, settings, app_events):
    settings.CSRF_HEADER_NAME = "HTTP_X_MY_CSRF"
    app_events({})
    assert "citry-vue-" in render_django("<c-csrf-quiet/>", request=rf.get("/"))


def test_a_cookie_a_script_cannot_read_gives_the_runtime_the_token(
    render_django, rf, settings, app_events
):
    settings.CSRF_COOKIE_HTTPONLY = True
    app_events(csrf_settings())
    request = rf.get("/")
    html = render_django("<c-csrf-live/>", request=request)
    assert block_names(html) == {"cookie": None}
    config = configured(html)
    assert config is not None
    assert config["csrf"]["token"]
    assert "cookie" not in config["csrf"]


def test_the_token_is_given_even_when_the_app_maps_nothing(render_django, rf, settings):
    """The token the script gives wins over the cookie Citry would read."""
    settings.CSRF_COOKIE_HTTPONLY = True
    config = configured(render_django("<c-csrf-live/>", request=rf.get("/")))
    assert config is not None
    assert config["csrf"]["token"]


def test_the_script_carries_the_pages_nonce(render_django, rf, settings, app_events):
    settings.CSRF_USE_SESSIONS = True
    app_events(csrf_settings())
    request = rf.get("/")
    request.session = {}
    request.csp_nonce = "abc123"
    html = render_django("<c-csrf-live/>", request=request)
    assert '<script nonce="abc123">(function(c)' in html


def test_an_island_in_a_django_block_gets_the_names_too(render, rf, settings, app_events):
    settings.CSRF_COOKIE_NAME = "mytoken"
    app_events(csrf_settings())
    html = render("<c-csrf-loop c-ns='[1]'/>", request=rf.get("/"))
    assert block_names(html) == {"cookie": "mytoken"}
    assert configured(html) is None


def test_a_partial_without_a_nonce_names_them_in_a_script(render_django, rf, settings, app_events):
    """On a page without a nonce, Citry ignores the names in a fragment's
    block, because injected markup could have written them."""
    settings.CSRF_COOKIE_NAME = "mytoken"
    settings.CSRF_HEADER_NAME = "HTTP_X_MY_CSRF"
    app_events(csrf_settings())
    html = render_django("<c-csrf-live/>", request=partial(rf))
    assert configured(html) == {"csrf": {"cookie": "mytoken", "header": "X-MY-CSRF"}}


def test_a_partial_with_a_nonce_needs_no_script(render_django, rf, settings, app_events):
    settings.CSRF_COOKIE_NAME = "mytoken"
    app_events(csrf_settings())
    html = render_django("<c-csrf-live/>", request=partial(rf, nonce="ownNonce12345"))
    assert configured(html) is None


def test_a_static_region_gets_none(render_django, rf, settings, app_events):
    settings.CSRF_COOKIE_HTTPONLY = True
    app_events(csrf_settings())
    assert configured(render_django("<c-csrf-still/>", request=rf.get("/"))) is None


def test_an_island_without_server_events_does_not_ask(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-quiet/>", request=request)
    assert "citry-vue-" in html
    assert not cookie_sent(request, html)


def test_an_island_without_server_events_in_a_django_block_does_not_ask(render, rf):
    request = rf.get("/")
    html = render("<c-csrf-quiet-loop c-ns='[1]'/>", request=request)
    assert "citry-vue-" in html
    assert not cookie_sent(request, html)


def test_one_island_with_events_among_others_asks(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-quiet/><c-csrf-live/>", request=request)
    assert cookie_sent(request, html)


def test_an_island_without_events_gets_no_csrf_script(render_django, rf, settings, app_events):
    settings.CSRF_COOKIE_HTTPONLY = True
    app_events(csrf_settings())
    assert configured(render_django("<c-csrf-quiet/>", request=rf.get("/"))) is None
