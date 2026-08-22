"""
Citry's asset system inside Django, both the way Citry means it and the way a
Django project usually wants it.

Citry components declare their own CSS and JS, and Citry serializes them into
the page. A project that already runs assets through Sekizai and
django-compressor wants them in *its* blocks instead, so both routes have to
work:

* the default, where Citry emits the assets itself;
* ``CITRY_DEPS_STRATEGY = "ignore"`` plus the optional ``citry-django-sekizai``
  package, which reads the same declarations through :mod:`citry.assets`.

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
<c-asset-group/>
{% if show %}<c-button label="in if"/>{% endif %}
<c-plain/>
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


def styles(html):
    return re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)


def scripts(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


def test_citry_emits_its_own_assets_by_default(render_page):
    html = render_page(show=True)
    assert ".btn{color:red}" in html
    assert ".asset-group{border:1px solid}" in html
    assert 'console.log("btn")' in html


@pytest.mark.usefixtures("sekizai_only")
class TestThroughSekizai:
    def test_assets_land_in_their_blocks(self, render_page):
        html = render_page(show=True)
        head = html.split("</head>")[0]
        assert styles(head) == [".asset-group{border:1px solid}", ".btn{color:red}"]
        assert scripts(html) == ['console.log("btn")']

    def test_a_nested_component_reaches_the_holder(self, render_page):
        """`Button` is only ever reached through `AssetGroup`, and still contributes."""
        html = render_page("""{% load sekizai_tags %}{% render_block "css" %}<c-asset-group/>""")
        assert ".btn{color:red}" in styles(html)

    def test_a_repeated_component_contributes_once(self, render_page):
        html = render_page(show=True)
        assert scripts(html).count('console.log("btn")') == 1
        assert styles(html).count(".btn{color:red}") == 1

    def test_a_component_repeated_by_django_contributes_once(self, render_page):
        html = render_page(
            """{% load sekizai_tags %}{% render_block "css" %}
            {% for label in labels %}<c-button c-label="label"/>{% endfor %}
            {% render_block "js" %}""",
            labels=["a", "b", "c"],
        )
        assert html.count('class="btn"') == 3
        assert scripts(html).count('console.log("btn")') == 1
        assert styles(html).count(".btn{color:red}") == 1

    def test_citry_emits_nothing_of_its_own(self, render_page):
        """With the strategy off, every asset on the page came through Sekizai."""
        html = render_page("<c-asset-group/><c-button label='loose'/>")
        assert styles(html) == []
        assert scripts(html) == []

    def test_a_component_without_assets_is_skipped(self, render_page):
        html = render_page("""{% load sekizai_tags %}{% render_block "css" %}<c-plain/>""")
        # `<hr` rather than `<hr>`: Citry stamps its identity markers on the
        # element, which is exactly what it should still be doing here.
        assert styles(html) == []
        assert "<hr" in html

    def test_the_markup_itself_is_unaffected(self, render_page):
        html = render_page(show=True)
        assert html.count('class="asset-group"') == 1
        assert html.count('class="btn"') == 2


def test_a_django_tag_between_two_regions_survives(render_page):
    """
    Regions either side of a `{% if %}` must not merge across it.

    They are separated only by a Django tag, and merging them would swallow the
    `{% endif %}` into Citry's source and orphan the tag.
    """
    assert 'class="btn"' in render_page(show=True)
    assert 'class="btn">in if' not in render_page(show=False)
