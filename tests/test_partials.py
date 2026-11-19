"""Islands in a partial response: an htmx swap, or a Django template partial.

A partial lands in a page the browser has already loaded, so each island in
it is a Citry fragment: a loader that adds the runtime only when the page
lacks it, and a data block the runtime finds once the HTML is in the page.
The browser half is in `test_browser.py`.
"""

from __future__ import annotations

import json
import re
import warnings

import django
import pytest
from citry import Component
from django.template import engines
from django.test import Client

from citry_django import PartialResponseWarning, page_csp_nonce
from citry_django.events import SESSION_KEY
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


def test_without_citrys_routes_a_partial_keeps_page_islands(
    monkeypatch, settings, rf, render_django
):
    """A fragment loads the runtime by URL. Without the routes the island stays
    a full-page one, which htmx can still run, and development says why."""
    make_app(monkeypatch, settings)
    settings.DEBUG = True
    with pytest.warns(PartialResponseWarning, match=r"citry_django\.urls"):
        html = render_django("<c-live/>", request=htmx_request(rf))
    assert fragments(html) == []
    assert len(islands(html).starts) == 1


def test_a_view_can_say_it_answers_a_whole_page(render_django, rf):
    request = htmx_request(rf)
    request.citry_partial = False
    html = render_django("<c-partial-live/>", request=request)
    assert fragments(html) == []
    assert len(islands(html).starts) == 1


def partial_after_page(rf, render_django, page_source: str = "<c-live/>"):
    """A page with an island kept "pageNonce"; return the same visitor's
    htmx request, whose own response has the nonce "partialNonce"."""
    page = page_request(rf, nonce="pageNonce")
    render_django(page_source, request=page)
    partial = page_request(rf, nonce="partialNonce")
    partial.session = page.session
    partial.META["HTTP_HX_REQUEST"] = "true"
    return partial


def assert_page_nonce(html: str) -> None:
    """Every place a fragment names a nonce names the page's."""
    matches = list(FRAGMENT.finditer(html))
    assert matches
    for match in matches:
        assert 'nonce="pageNonce"' in match.group("attrs")
        assert json.loads(match.group("json"))["vue"]["prepared"]["nonce"] == "pageNonce"
    # The loader's own tag, and the runtime tag it adds.
    assert '<script nonce="pageNonce">' in html
    assert 's.nonce = "pageNonce";' in html
    assert "partialNonce" not in html


def test_an_island_in_a_django_block_carries_the_page_nonce(
    monkeypatch, settings, rf, render_django
):
    mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    partial = partial_after_page(rf, render_django)
    html = render_django("<c-loop c-ns='[1]'/>", request=partial)
    assert_page_nonce(html)
    assert partial.session[SESSION_KEY] == "pageNonce"


def test_a_component_rendered_from_python_carries_the_page_nonce(
    monkeypatch, settings, rf, render_django
):
    app = mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    partial = partial_after_page(rf, render_django)
    html = str(app.get("loop")(ns=[1]).render(template_globals={"request": partial}))
    assert_page_nonce(html)
    assert partial.session[SESSION_KEY] == "pageNonce"


def test_a_nonce_in_the_context_gives_way_to_the_page_nonce(
    monkeypatch, settings, rf, render_django
):
    mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    partial = partial_after_page(rf, render_django)
    html = render_django("<c-live/>", request=partial, csp_nonce="partialNonce")
    assert_page_nonce(html)


def test_a_whole_page_without_an_island_replaces_a_kept_nonce(
    monkeypatch, settings, rf, render_django
):
    """The visitor moved on to a page without an island; a partial lands
    there, so it needs that page's nonce, not the earlier page's."""
    mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    first = page_request(rf, nonce="firstNonce")
    render_django("<c-live/>", request=first)
    plain = page_request(rf, nonce="plainNonce")
    plain.session = first.session
    render_django("<p>No island here.</p>", request=plain)
    assert first.session[SESSION_KEY] == "plainNonce"


def test_a_page_never_reads_the_session_unless_the_app_asks(
    monkeypatch, settings, rf, render_django
):
    """Reading it would add `Vary: Cookie` to every page."""
    mounted_app(monkeypatch, settings)
    plain = page_request(rf, nonce="plainNonce")
    render_django("<p>No island here.</p>", request=plain)
    assert not plain.session.accessed


def test_a_page_without_an_island_starts_no_session(monkeypatch, settings, rf, render_django):
    mounted_app(monkeypatch, settings, _csp_nonce=page_csp_nonce)
    plain = page_request(rf, nonce="plainNonce")
    render_django("<p>No island here.</p>", request=plain)
    assert SESSION_KEY not in plain.session
    assert not plain.session.modified


class TestTheDevelopmentWarning:
    def test_a_page_response_without_a_body_warns(self, settings, rf, render_django):
        settings.DEBUG = True
        with pytest.warns(PartialResponseWarning, match=r"\(/cards/\).*HX-Request"):
            render_django("<c-partial-live/>", request=rf.get("/cards/"))

    def test_it_warns_without_page_collection_too(self, settings, rf, render_django):
        settings.DEBUG = True
        settings.CITRY_COLLECT_PAGE_ASSETS = False
        with pytest.warns(PartialResponseWarning):
            render_django("<c-partial-live/>", request=rf.get("/"))

    @pytest.mark.parametrize(
        "source",
        [
            "<body><c-partial-live/></body>",
            # The browser adds a <body> that the page leaves out.
            "<!doctype html><title>t</title><c-partial-live/>",
            "<c-partial-still/>",
        ],
    )
    def test_a_whole_page_or_a_static_one_does_not(self, settings, rf, render_django, source):
        settings.DEBUG = True
        with warnings.catch_warnings():
            warnings.simplefilter("error", PartialResponseWarning)
            render_django(source, request=rf.get("/"))

    def test_a_partial_does_not(self, settings, rf, render_django):
        settings.DEBUG = True
        with warnings.catch_warnings():
            warnings.simplefilter("error", PartialResponseWarning)
            render_django("<c-partial-live/>", request=htmx_request(rf))

    def test_nor_does_production(self, settings, rf, render_django):
        settings.DEBUG = False
        with warnings.catch_warnings():
            warnings.simplefilter("error", PartialResponseWarning)
            render_django("<c-partial-live/>", request=rf.get("/"))


class TestServerEventsFromAFragment:
    """An island that htmx swapped in sends its server events like any other:
    Django's CSRF check and Citry's State token still decide."""

    @pytest.fixture(autouse=True)
    def site_urls(self, settings):
        settings.ROOT_URLCONF = "events_site.urls"

    def call(self, client: Client, html: str, *, csrf: str | None, token: str | None = None):
        [fragment] = fragments(html)
        prepared = fragment["prepared"]
        owner = next(item for item in prepared["manifest"]["occurrences"] if "eventContext" in item)
        context = owner["eventContext"]
        envelope = {
            "protocol": "citry-events/1",
            "requestId": "r1",
            "calls": [
                {
                    "componentClassId": context["componentClassId"],
                    "handlerName": "bump",
                    "args": {},
                    "callerRenderId": context["serverRenderId"],
                    "stateToken": token or context["stateToken"],
                    "sendSequence": 1,
                }
            ],
            "capabilities": {
                "actions": ["render"],
                "swaps": ["morph"],
                "renderers": ["vue-prepared/1"],
            },
        }
        headers = {
            "X-Citry-Events": "1",
            "X-Citry-Vue-App": fragment["appId"],
            "X-Citry-Vue-Occurrence": owner["id"],
            "X-Citry-Vue-Revision": "0",
        }
        if csrf is not None:
            headers["X-CSRFToken"] = csrf
        return client.post(
            prepared["endpoint"],
            data=json.dumps(envelope),
            content_type="application/citry-events+json",
            headers=headers,
        )

    @pytest.fixture
    def swapped(self, db):
        client = Client(enforce_csrf_checks=True)
        response = client.get("/card/", headers={"HX-Request": "true"})
        assert response.status_code == 200
        # The partial asks Django for the token, so its cookie comes along.
        assert "csrftoken" in response.cookies
        return client, response.content.decode(), response.cookies["csrftoken"].value

    def test_a_call_with_the_csrf_token_runs(self, swapped):
        client, html, csrf = swapped
        response = self.call(client, html, csrf=csrf)
        assert response.status_code == 200
        [result] = json.loads(response.content)["results"]
        assert result["ok"], result

    def test_a_call_without_it_is_refused(self, swapped):
        client, html, _ = swapped
        assert self.call(client, html, csrf=None).status_code == 403

    def test_a_forged_state_token_is_refused(self, swapped):
        client, html, csrf = swapped
        [fragment] = fragments(html)
        owner = next(
            item
            for item in fragment["prepared"]["manifest"]["occurrences"]
            if "eventContext" in item
        )
        genuine = owner["eventContext"]["stateToken"]
        forged = genuine[:-4] + ("AAAA" if not genuine.endswith("AAAA") else "BBBB")
        response = self.call(client, html, csrf=csrf, token=forged)
        [result] = json.loads(response.content)["results"]
        assert not result["ok"]
