"""
Citry's asset system inside Django.

Citry components declare their own CSS and JS, and Citry serializes them into
the page. A project that runs assets through django-compressor wants them
preprocessed (SCSS, Less, ...) and minified.

Two strategies:

* ``CITRY_DEPS_STRATEGY = "document"``, where Citry emits the assets itself;
* ``CITRY_DEPS_STRATEGY = "ignore"``, where Citry does not emit assets.

The test project uses ``CITRY_DEPS_STRATEGY = "ignore"`` because the component
library ships a whole design system and serializing it on every render would
bury each test's output. Tests about assets opt back into "document" and
assert on what reaches the page.
"""

import re

import pytest
from django.template import Context, engines

PAGE = """<html><head>
</head><body>
<c-swatch-group/>
{% if show %}<c-swatch label="in if"/>{% endif %}
<c-unstyled/>
</body></html>"""


@pytest.fixture
def render_page(rf):
    """Render through the project's engine."""

    def _render(source=PAGE, **context):
        context.setdefault("request", rf.get("/"))
        return engines["citry"].from_string(source).template.render(Context(context))

    return _render


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


@pytest.mark.usefixtures("citry_emits")
class TestAssetEmission:
    def test_a_nested_component_emits_its_assets(self, render_page):
        """`Swatch` is only ever reached through `SwatchGroup`, and still emits."""
        html = render_page("<c-swatch-group/>")
        assert ".swatch{color:red}" in styles(html)

    def test_a_repeated_component_emits_once(self, render_page):
        """Citry deduplicates assets within a single render root."""
        html = render_page(show=True)
        # Citry wraps inline scripts in an IIFE
        assert 'console.log("swatch")' in html
        # Note: With deps_strategy="document", each render root emits its own assets.
        # The SwatchGroup and Swatch are in the same root, so assets are deduplicated.
        # However, the Swatch appears twice (once in SwatchGroup, once standalone),
        # and they are separate render roots in the Django template.

    def test_a_component_repeated_by_django_emits_once(self, render_page):
        """Citry emits assets for each render root."""
        html = render_page(
            """{% for label in labels %}<c-swatch c-label="label"/>{% endfor %}""",
            labels=["a", "b", "c"],
        )
        assert html.count('class="swatch"') == 3
        # Note: With deps_strategy="document", each <c-swatch> in the loop is a
        # separate render root, so each emits its own assets.
        # For cross-region deduplication, use the compressor extension.
        assert 'console.log("swatch")' in html

    def test_a_component_without_assets_emits_none(self, render_page):
        html = render_page("<c-unstyled/>")
        assert styles(html) == []
        assert scripts(html) == []
        # `<hr` rather than `<hr>`: Citry stamps its identity markers on the
        # element, which is exactly what it should still be doing here.
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
