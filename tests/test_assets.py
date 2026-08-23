"""
Citry's asset system inside Django, both the way Citry means it and the way a
Django project usually wants it.

Citry components declare their own CSS and JS, and Citry serializes them into
the page. A project that already runs assets through Sekizai and
django-compressor wants them in *its* blocks instead, so both routes have to
work:

* ``CITRY_DEPS_STRATEGY = "document"``, where Citry emits the assets itself;
* ``CITRY_DEPS_STRATEGY = "ignore"`` plus the optional ``citry-django-sekizai``
  package, which reads the same declarations through :mod:`citry.assets`.

Both are set explicitly here. The test project turns Citry's own emission off,
because the component library it builds on ships a whole design system and
serializing it on every render would bury each test's output.

The second route invents no way of declaring assets. It reads exactly what Citry
already resolved, so a component stays a plain Citry component.
"""

import re

import pytest
from django.template import engines
from sekizai.context import SekizaiContext

PAGE = """{% load sekizai_tags %}<html><head>
{% render_block "css" %}
</head><body>
<c-swatch-group/>
{% if show %}<c-swatch label="in if"/>{% endif %}
<c-unstyled/>
{% render_block "js" %}
</body></html>"""


@pytest.fixture
def render_page(rf):
    """Render through the project's engine with a Sekizai context."""

    def _render(source=PAGE, **context):
        context.setdefault("request", rf.get("/"))
        return engines["citry"].from_string(source).template.render(SekizaiContext(context))

    return _render


@pytest.fixture
def sekizai_only(settings):
    """Stop Citry emitting assets, leaving the contrib extension to place them."""
    settings.CITRY_DEPS_STRATEGY = "ignore"


@pytest.fixture
def citry_emits(settings):
    """Let Citry serialize its own dependencies, as it does out of the box."""
    settings.CITRY_DEPS_STRATEGY = "document"


def styles(html):
    return re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)


def scripts(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


@pytest.mark.usefixtures("citry_emits")
def test_citry_emits_its_own_assets(render_page):
    html = render_page(show=True)
    assert ".swatch{color:red}" in html
    assert ".swatch-group{border:1px solid}" in html
    assert 'console.log("swatch")' in html


@pytest.mark.usefixtures("sekizai_only")
class TestThroughSekizai:
    def test_assets_land_in_their_blocks(self, render_page):
        html = render_page(show=True)
        head = html.split("</head>")[0]
        assert styles(head) == [".swatch-group{border:1px solid}", ".swatch{color:red}"]
        assert scripts(html) == ['console.log("swatch")']

    def test_a_nested_component_reaches_the_holder(self, render_page):
        """`Button` is only ever reached through `AssetGroup`, and still contributes."""
        html = render_page("""{% load sekizai_tags %}{% render_block "css" %}<c-swatch-group/>""")
        assert ".swatch{color:red}" in styles(html)

    def test_a_repeated_component_contributes_once(self, render_page):
        html = render_page(show=True)
        assert scripts(html).count('console.log("swatch")') == 1
        assert styles(html).count(".swatch{color:red}") == 1

    def test_a_component_repeated_by_django_contributes_once(self, render_page):
        html = render_page(
            """{% load sekizai_tags %}{% render_block "css" %}
            {% for label in labels %}<c-swatch c-label="label"/>{% endfor %}
            {% render_block "js" %}""",
            labels=["a", "b", "c"],
        )
        assert html.count('class="swatch"') == 3
        assert scripts(html).count('console.log("swatch")') == 1
        assert styles(html).count(".swatch{color:red}") == 1

    def test_citry_emits_nothing_of_its_own(self, render_page):
        """With the strategy off, every asset on the page came through Sekizai."""
        html = render_page("<c-swatch-group/><c-swatch label='loose'/>")
        assert styles(html) == []
        assert scripts(html) == []

    def test_a_component_without_assets_is_skipped(self, render_page):
        html = render_page("""{% load sekizai_tags %}{% render_block "css" %}<c-unstyled/>""")
        # `<hr` rather than `<hr>`: Citry stamps its identity markers on the
        # element, which is exactly what it should still be doing here.
        assert styles(html) == []
        assert "<hr" in html

    def test_the_markup_itself_is_unaffected(self, render_page):
        html = render_page(show=True)
        assert html.count('class="swatch-group"') == 1
        assert html.count('class="swatch"') == 2


def test_a_django_tag_between_two_regions_survives(render_page):
    """
    Regions either side of a `{% if %}` must not merge across it.

    They are separated only by a Django tag, and merging them would swallow the
    `{% endif %}` into Citry's source and orphan the tag.
    """
    assert 'class="swatch"' in render_page(show=True)
    assert 'class="swatch">in if' not in render_page(show=False)
