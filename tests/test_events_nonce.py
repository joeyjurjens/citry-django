"""The nonce of the page a server event came from, kept for Citry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from citry import Citry, Component
from django.contrib.sessions.backends.signed_cookies import SessionStore

from citry_django import CitryDjangoExtension, page_csp_nonce
from citry_django.events import SESSION_KEY
from citry_django.registry import citry_app_source


def make_app(monkeypatch, settings, **events) -> Citry:
    import testproject.citry_app as app_module

    app = Citry(
        extensions=[CitryDjangoExtension()],
        extensions_defaults={"events": events} if events else {},
    )

    class Live(Component):
        citry = app

        def js_data(self, kwargs, slots) -> dict:
            return {"on": True}

        template = "<b>live</b>"

    class Still(Component):
        citry = app
        template = "<i>still</i>"

    class Loop(Component):
        citry = app
        template = "<ul>{% for n in ns %}<li><c-live/></li>{% endfor %}</ul>"

    app.register(Live, "live")
    app.register(Still, "still")
    app.register(Loop, "loop")
    monkeypatch.setattr(app_module, "events_nonce_app", app, raising=False)
    settings.CITRY_APP = "testproject.citry_app:events_nonce_app"
    citry_app_source.cache_clear()
    return app


@pytest.fixture(autouse=True)
def clear_app_cache():
    yield
    citry_app_source.cache_clear()


def page_request(rf, nonce: str = "pageNonce"):
    request = rf.get("/")
    request.session = SessionStore()
    request.csp_nonce = nonce
    return request


def test_a_page_with_an_island_keeps_its_nonce(monkeypatch, settings, rf, render_django):
    make_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    request = page_request(rf)
    render_django("<c-live/>", request=request)

    assert request.session[SESSION_KEY] == "pageNonce"
    assert page_csp_nonce(SimpleNamespace(native=request, headers={})) == "pageNonce"


def test_an_island_in_a_django_block_keeps_it_too(monkeypatch, settings, rf):
    app = make_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    request = page_request(rf)
    str(app.get("loop")(ns=[1]).render(template_globals={"request": request}))

    assert request.session[SESSION_KEY] == "pageNonce"


def test_a_static_page_writes_no_session(monkeypatch, settings, rf, render_django):
    make_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    request = page_request(rf)
    render_django("<c-still/>", request=request)

    assert SESSION_KEY not in request.session
    assert not request.session.modified


def test_nothing_is_kept_unless_the_app_asks(monkeypatch, settings, rf, render_django):
    make_app(monkeypatch, settings)
    request = page_request(rf)
    render_django("<c-live/>", request=request)

    assert SESSION_KEY not in request.session


@pytest.mark.parametrize("session", [None, {}, {SESSION_KEY: 42}])
def test_no_kept_nonce_reads_as_none(session):
    native = SimpleNamespace() if session is None else SimpleNamespace(session=session)
    assert page_csp_nonce(SimpleNamespace(native=native, headers={})) is None


def test_citry_accepts_it_as_the_events_setting():
    Citry(extensions_defaults={"events": {"_csp_nonce": page_csp_nonce}})
