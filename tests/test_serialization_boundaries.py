from __future__ import annotations

import json
import re

import pytest
from citry import Citry, Component, Extension
from django.template import engines

from citry_django import CitryDjangoExtension
from citry_django.registry import citry_app_source
from islands import islands, runtime_scripts


def json_script(html: str, attribute: str) -> dict:
    match = re.search(rf"<script[^>]*{attribute}[^>]*>(.*?)</script>", html, re.S)
    assert match is not None, f"no {attribute} script in output"
    return json.loads(match.group(1))


def test_django_loop_makes_one_island_per_iteration() -> None:
    """A Django `{% for %}` inside a component repeats an interactive child.

    The text around the loop is Django's, so each child that needs Vue
    becomes its own island where it stands, with no `#c-key`, and the page
    around them stays plain HTML.
    """

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
              <ul>
              {% for value in values %}
                <li><c-serialization-boundary-widget c-value="value"/></li>
              {% endfor %}
              </ul>
              <c-js/>
            </body></html>
        """

    html = str(Page(values=["a", "b"]))
    found = islands(html)

    # One serialize per island, then one for the page around them.
    assert counter.calls == ["document", "document", "document"]
    assert len(found) == 2
    assert len(found.configs) == 2
    assert len(found.starts) == 2
    assert len(set(found.hosts)) == 2
    assert html.count('class="boundary-widget"') == 2
    # Each host sits in its own row, where the loop put the widget.
    assert len(re.findall(r'<li>\s*(?:<[^>]+>\s*)*?<div id="citry-vue-', html)) == 2
    # Each island links its own assets beside itself until Citry can hand
    # them back for the page to collect.
    assert html.count('rel="stylesheet"') == 2
    assert html.split("<body>")[0].count("<link") == 0


def test_dependency_placeholder_keeps_its_authored_position(component, render_django) -> None:
    """Islands inside a component's Django loop send their scripts to the page.

    Each widget is its own island, and the page writes the scripts they share
    once, where the template's `<c-js/>` stands.
    """
    component(
        "<b>{{ value }}</b>",
        name="serialization-placeholder-widget",
        js='console.log("placed-by-placeholder")',
    )
    component(
        """
        <main>
          {% for value in values %}
            <c-serialization-placeholder-widget c-value="value"/>
          {% endfor %}
        </main>
        """,
        name="serialization-placeholder-page",
    )

    html = render_django(
        "BEFORE<c-js/>MIDDLE<c-serialization-placeholder-page c-values=\"['a', 'b']\"/>AFTER"
    )

    assert html.count('console.log("placed-by-placeholder")') == 1
    assert html.index('console.log("placed-by-placeholder")') < html.index("MIDDLE")
    assert runtime_scripts(html) == 1
    found = islands(html)
    assert len(found) == len(found.starts) == 2
    # Each island's own start script moves to the spot too.
    assert html.rindex("startDocument") < html.index("MIDDLE")


def test_a_component_rendered_from_python_writes_tags_beside_each_island(component) -> None:
    """Without a citry-django page, nothing collects the islands' tags.

    Each island inside the component's Django loop writes its own tags
    beside itself, so the runtime is there once per island, and the
    component's own `<c-js/>` does not collect them.
    """
    widget = component(
        "<b>{{ value }}</b>",
        name="serialization-direct-widget",
        js='console.log("direct")',
    )
    del widget
    page = component(
        """
        <main>
          BEFORE<c-js/>MIDDLE
          {% for value in values %}
            <c-serialization-direct-widget c-value="value"/>
          {% endfor %}
        </main>
        """
    )

    html = str(page(values=["a", "b"]))

    assert runtime_scripts(html) == 2
    assert len(islands(html).starts) == 2
    assert "<!--citry-django" not in html


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
    # The nonce is applied while Citry serializes its dependencies, so this is
    # one of the tests that needs Citry emitting them.
    import testproject.citry_app as app_module

    app = Citry(
        extensions=[CitryDjangoExtension()],
        security_csp="strict",
    )
    app.set_mounted_prefix("/citry")

    class Interactive(Component):
        citry = app

        def js_data(self, kwargs, slots) -> dict:
            return {"count": 1}

        template = "<div>interactive</div>"

    app.register(Interactive, "serialization-csp-widget")
    monkeypatch.setattr(app_module, "serialization_csp_app", app, raising=False)
    settings.CITRY_APP = "testproject.citry_app:serialization_csp_app"
    citry_app_source.cache_clear()
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
        citry_app_source.cache_clear()

    # One island, and every script Citry wrote for it carries the nonce,
    # the runtime file included.
    found = islands(html)
    assert len(found) == 1
    assert len(found.configs) == 1
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert sum('src="/citry/citry.' in tag for tag in scripts) == 1
    assert all('nonce="requestNonce"' in tag for tag in scripts)


def locmem(settings) -> None:
    from django.core.cache import cache

    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()


def test_a_cached_body_replayed_later_fails_loudly(settings) -> None:
    """
    A body-caching tag stores the marker, not the markup.

    The markup only exists once the block around it finishes, so what
    `{% cache %}` keeps is the placeholder. On a later hit the body never
    renders, leaving nothing to put back -- and the reached-marker check cannot
    see it, because this render reached no markers at all. Without this guard
    the raw comment goes to the browser.
    """
    locmem(settings)
    app = Citry(extensions=[CitryDjangoExtension()])

    class Widget(Component):
        citry = app
        template = "<b>cached</b>"

    app.register(Widget, "cache-replay-widget")

    class Page(Component):
        citry = app
        template = "{% load cache %}{% cache 300 replay %}<c-cache-replay-widget/>{% endcache %}"

    assert "<b" in str(Page())
    with pytest.raises(RuntimeError, match="cannot be restored"):
        str(Page())


def test_a_cached_region_in_a_django_template_replays(settings) -> None:
    """
    A region in a Django template is finished markup, so a host may store it.

    `{% cache %}` around a region keeps what the region rendered, assets and
    all, and a later hit serves it without rendering anything. Nothing in the
    markup refers back to the page that produced it, which is what makes the
    replay sound -- and hosts do this well beyond `{% cache %}`: a rendered
    base template kept in a module-level dict is the same thing by hand.
    """
    locmem(settings)
    source = "{% load cache %}{% cache 300 region %}<c-swatch label='cached'/>{% endcache %}"

    first = engines["citry"].from_string(source).render({})
    assert 'class="swatch"' in first
    assert engines["citry"].from_string(source).render({}) == first
