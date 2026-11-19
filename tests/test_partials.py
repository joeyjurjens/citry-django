"""Islands in a partial response: an htmx swap, or a Django template partial.

A partial lands in a page the browser has already loaded, so each island in
it is a Citry fragment: a loader that adds the runtime only when the page
lacks it, and a data block the runtime finds once the HTML is in the page.
The browser half is in `test_browser.py`.
"""

from __future__ import annotations

import json
import re

import django
import pytest
from citry import Component
from django.template import engines

from citry_django import page_csp_nonce
from citry_django.events import SESSION_KEY
from citry_django.islands import IslandStrategyError
from citry_django.registry import citry_app_source
from events_site.app import app as site_app
from islands import islands, runtime_scripts
from test_events_nonce import make_app, page_request

#: The data block the runtime starts a fragment from, and its JSON.
FRAGMENT = re.compile(
    r'<script type="application/json" data-citry-vue-fragment(?P<attrs>[^>]*)>'
    r"(?P<json>.*?)</script>",
    re.S,
)


class PartialLive(Component):
    citry = site_app

    def js_data(self, kwargs, slots) -> dict:
        return {"on": True}

    template = """
        <b>live</b>
    """


class PartialStill(Component):
    citry = site_app
    template = """
        <i>still</i>
    """
    css = """
        .still { color: red; }
    """


class PartialLoop(Component):
    citry = site_app
    template = """
        <ul>{% for n in ns %}<li><c-partial-live/></li>{% endfor %}</ul>
    """


site_app.register(PartialLive, "partial-live")
site_app.register(PartialStill, "partial-still")
site_app.register(PartialLoop, "partial-loop")


@pytest.fixture(autouse=True)
def mounted_site(settings):
    """A fragment loads Citry's files by URL, so its app has mounted routes."""
    settings.CITRY_APP = "events_site.app:app"
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


def mounted_app(monkeypatch, settings, **events):
    app = make_app(monkeypatch, settings, **events)
    app.set_mounted_prefix("/citry")
    return app


def fragments(html: str) -> list[dict]:
    return [json.loads(match.group("json"))["vue"] for match in FRAGMENT.finditer(html)]


def htmx_request(rf, **extra):
    return rf.get("/cards/", HTTP_HX_REQUEST="true", **extra)


def test_an_htmx_request_gets_each_island_as_a_fragment(render_django, rf):
    html = render_django("<c-partial-live/>", request=htmx_request(rf))

    [fragment] = fragments(html)
    assert fragment["protocol"] == "citry-vue-fragment/1"
    assert f'<div id="citry-vue-{fragment["appId"]}"' in html
    # No page tags: no runtime script and no start script to run on load,
    # and nothing between citry-django's comments for a page to move.
    assert runtime_scripts(html) == 0
    assert islands(html).starts == []
    assert "<!--citry-django:" not in html


def test_a_view_can_ask_for_a_partial_itself(render_django, rf):
    request = rf.get("/cards/")
    request.citry_partial = True
    assert len(fragments(render_django("<c-partial-live/>", request=request))) == 1


def test_a_page_request_still_gets_a_page_island(render_django, rf):
    html = render_django("<c-partial-live/>", request=rf.get("/"))
    assert fragments(html) == []
    assert len(islands(html).starts) == 1


def test_htmx_boost_and_other_header_values(render_django, rf):
    # A boosted link is an htmx request too; its answer is swapped into the
    # body of the page already loaded.
    boosted = rf.get("/", HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true")
    assert len(fragments(render_django("<c-partial-live/>", request=boosted))) == 1
    # Only htmx's own value counts.
    other = rf.get("/", HTTP_HX_REQUEST="1")
    assert fragments(render_django("<c-partial-live/>", request=other)) == []


def test_islands_in_a_django_block_are_fragments_too(render_django, rf):
    html = render_django("<c-partial-loop c-ns='[1, 2]'/>", request=htmx_request(rf))
    assert len(fragments(html)) == 2
    assert islands(html).starts == []


def test_a_static_region_keeps_its_tags_in_a_partial(render_django, rf):
    html = render_django("<c-partial-still/><c-partial-still/>", request=htmx_request(rf))
    assert fragments(html) == []
    assert html.count(".still { color: red; }") == 1


@pytest.mark.skipif(django.VERSION < (6, 0), reason="template partials are new in Django 6.0")
def test_a_template_partial_holds_a_fragment(rf):
    template = engines["citry"].get_template("partials/page.html#card")
    html = template.render({}, htmx_request(rf))

    assert html.startswith('<section class="card">')
    assert len(fragments(html)) == 1
    assert runtime_scripts(html) == 0


def test_a_partial_carries_the_nonce_of_the_page_it_lands_in(
    monkeypatch, settings, rf, render_django
):
    mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    page = page_request(rf, nonce="pageNonce")
    render_django("<c-live/>", request=page)

    # The same visitor's htmx request, with the nonce of its own response.
    partial = page_request(rf, nonce="partialNonce")
    partial.session = page.session
    partial.META["HTTP_HX_REQUEST"] = "true"
    html = render_django("<c-live/>", request=partial)

    [match] = FRAGMENT.finditer(html)
    assert 'nonce="pageNonce"' in match.group("attrs")
    assert json.loads(match.group("json"))["vue"]["prepared"]["nonce"] == "pageNonce"
    assert "partialNonce" not in html
    # A partial is not a page, so the page's nonce stays the kept one.
    assert page.session[SESSION_KEY] == "pageNonce"


def test_a_partial_without_a_kept_nonce_uses_its_own(monkeypatch, settings, rf, render_django):
    mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    partial = page_request(rf, nonce="partialNonce")
    partial.META["HTTP_HX_REQUEST"] = "true"
    html = render_django("<c-live/>", request=partial)

    assert 'nonce="partialNonce"' in html
    assert SESSION_KEY not in partial.session


def test_a_kept_nonce_is_used_only_when_the_app_asks(monkeypatch, settings, rf, render_django):
    mounted_app(monkeypatch, settings)
    partial = page_request(rf, nonce="partialNonce")
    partial.session[SESSION_KEY] = "staleNonce"
    partial.META["HTTP_HX_REQUEST"] = "true"
    html = render_django("<c-live/>", request=partial)

    assert "staleNonce" not in html


def test_a_partial_needs_citrys_routes(monkeypatch, settings, rf, render_django):
    make_app(monkeypatch, settings)
    with pytest.raises(IslandStrategyError, match=r"citry_django\.urls"):
        render_django("<c-live/>", request=htmx_request(rf))
