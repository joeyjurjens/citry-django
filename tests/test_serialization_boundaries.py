"""Serialization behavior where Django selects structured Citry renders."""

from __future__ import annotations

import json
import re

import pytest
from citry import Citry, Component, Extension
from django.template import engines

from citry_django import CitryDjangoExtension
from citry_django.registry import get_citry_app


def _json_script(html: str, attribute: str) -> dict:
    match = re.search(rf"<script[^>]*{attribute}[^>]*>(.*?)</script>", html, re.S)
    assert match is not None, f"no {attribute} script in output"
    return json.loads(match.group(1))


def test_django_loop_preserves_client_graph_and_serializes_once() -> None:
    class CountSerialize(Extension):
        name = "count_serialization_boundary"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def on_serialize(self, ctx) -> None:
            self.calls.append(ctx.deps_strategy)

    counter = CountSerialize()
    app = Citry(
        extensions=[CitryDjangoExtension(), counter],
        secret="serialization-boundary-test-secret",
    )
    app.set_mounted_prefix("/citry")

    class WidgetState:
        value: str = ""
        _public = ("value",)

    class Widget(Component):
        citry = app
        State = WidgetState
        css = ".boundary-widget{color:red}"
        js = 'console.log("boundary-widget")'

        class Events:
            def save(self, state) -> None:
                return None

        template = '<button class="boundary-widget">{{ value }}</button>'

    app.register(Widget, "serialization-boundary-widget")

    class Page(Component):
        citry = app
        template = """
            <html><head><c-css/></head><body>
              {% for value in values %}
                <c-serialization-boundary-widget c-value="value"/>
              {% endfor %}
              <c-js/>
            </body></html>
        """

    html = str(Page(values=["a", "b"]))
    graph = _json_script(html, "data-citry-graph")
    events = _json_script(html, "data-citry-events")

    assert counter.calls == ["document"]
    assert html.count('class="boundary-widget"') == 2
    assert html.count('data-citry-root=""') == 2
    assert html.count(".boundary-widget{color:red}") == 1
    assert html.count('console.log("boundary-widget")') == 1
    assert events["clientGraphRevision"] == graph["revision"]
    assert len(events["componentInstances"]) == 2


def test_dependency_placeholder_keeps_its_authored_position() -> None:
    app = Citry(extensions=[CitryDjangoExtension()])

    class Widget(Component):
        citry = app
        js = 'console.log("placed-by-placeholder")'
        template = "<b>{{ value }}</b>"

    app.register(Widget, "serialization-placeholder-widget")

    class Page(Component):
        citry = app
        template = """
            <main>
              BEFORE<c-js/>MIDDLE
              {% for value in values %}
                <c-serialization-placeholder-widget c-value="value"/>
              {% endfor %}
              AFTER
            </main>
        """

    html = str(Page(values=["a", "b"]))

    assert html.count('console.log("placed-by-placeholder")') == 1
    assert html.index('console.log("placed-by-placeholder")') < html.index("MIDDLE")


def test_a_django_tag_that_changes_a_reached_marker_fails_loudly() -> None:
    app = Citry(extensions=[CitryDjangoExtension()])

    class Widget(Component):
        citry = app
        template = "<b>unchanged</b>"

    app.register(Widget, "serialization-marker-widget")

    class Page(Component):
        citry = app
        template = """
            {% filter upper %}
              <c-serialization-marker-widget/>
            {% endfilter %}
        """

    with pytest.raises(RuntimeError, match="transformed, duplicated, or discarded"):
        str(Page())


@pytest.mark.parametrize("nonce_source", ["csp_nonce", "CSP_NONCE", "request"])
def test_host_nonce_reaches_strict_citry_serialization(
    monkeypatch,
    nonce_source,
    rf,
    settings,
) -> None:
    import testproject.citry_app as app_module

    app = Citry(
        extensions=[CitryDjangoExtension()],
        security_csp="strict",
    )
    app.set_mounted_prefix("/citry")

    class Interactive(Component):
        citry = app
        template = '<div x-data="{}">interactive</div>'

    app.register(Interactive, "serialization-csp-widget")
    monkeypatch.setattr(app_module, "serialization_csp_app", app, raising=False)
    settings.CITRY_APP = "testproject.citry_app:serialization_csp_app"
    get_citry_app.cache_clear()
    context = {}
    request = None
    if nonce_source == "request":
        request = rf.get("/")
        request.csp_nonce = "requestNonce"
    else:
        context[nonce_source] = "requestNonce"
    try:
        html = (
            engines["citry"]
            .from_string("<c-serialization-csp-widget/>")
            .render(
                context,
                request,
            )
        )
    finally:
        get_citry_app.cache_clear()

    assert 'nonce="requestNonce"' in html
    assert 'src="/citry/ext/events/runtime-csp.js"' in html
