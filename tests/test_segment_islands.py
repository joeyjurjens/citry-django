"""Components that need Vue inside a Django block of a component's template.

The text around such a block is Django's, so each child that needs Vue
becomes its own island where it stands, and the rest stays plain HTML.
"""

from __future__ import annotations

import re

import pytest
from django.core.cache import cache

from citry_django.islands import IslandPlacementError, IslandStrategyError
from islands import islands


@pytest.fixture(autouse=True)
def fixtures(component):
    component(
        '<button class="live">{{ label }}</button>',
        name="seg-live",
        js_data=lambda self, kwargs, slots: {"label": "x"},
    )
    component('<i class="still">{{ label }}</i>', name="seg-still", css=".still{color:blue}")
    component(
        """
        <ul>
          {% for label in labels %}
            <li><c-seg-live c-label="label"/></li>
          {% endfor %}
        </ul>
        """,
        name="seg-loop",
    )
    component(
        """
        <div>
          {% if show %}<c-seg-live label="shown"/>{% endif %}
          {% for label in labels %}<c-seg-still c-label="label"/>{% endfor %}
        </div>
        """,
        name="seg-mixed",
    )
    component(
        "<p>{% if show %}<c-seg-live label='in p'/>{% endif %}</p>",
        name="seg-in-p",
    )
    component(
        "<section class='inner'>{% if show %}<c-seg-live label='deep'/>{% endif %}</section>",
        name="seg-inner",
        css=".inner{color:green}",
    )
    component("<div>{% if show %}<c-seg-inner c-show='show'/>{% endif %}</div>", name="seg-outer")


def test_each_iteration_is_its_own_island(render_django):
    html = render_django("<c-seg-loop c-labels=\"['a', 'b', 'c']\"/>")
    found = islands(html)

    assert len(found) == 3
    assert len(found.configs) == 3
    assert len(set(found.hosts)) == 3
    assert len(re.findall(r"<li>(?:(?!</li>).)*?<div id=\"citry-vue-", html, re.S)) == 3


def test_a_child_without_vue_stays_in_the_page(render_django):
    """Its assets are still collected once, with the rest of the page."""
    html = render_django("<c-seg-mixed c-show='True' c-labels=\"['a', 'b']\"/>")

    assert len(islands(html)) == 1
    assert html.count('class="still"') == 2
    assert html.count(".still{color:blue}") == 1


def test_a_branch_not_taken_builds_no_island(render_django):
    html = render_django("<c-seg-mixed c-show='False' c-labels='[]'/>")
    assert len(islands(html)) == 0


def test_a_tag_that_changes_an_island_marker_still_fails(render):
    with pytest.raises(RuntimeError, match="transformed, duplicated, or discarded"):
        render("{% filter upper %}<c-seg-live label='x'/>{% endfilter %}")


def test_a_cached_body_holding_an_island_still_fails(settings, render):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    source = "{% load cache %}{% cache 300 seg %}<c-seg-live label='x'/>{% endcache %}"
    assert len(islands(render(source))) == 1
    with pytest.raises(RuntimeError, match="cannot be restored"):
        render(source)


def test_the_region_nonce_reaches_every_island(render_django):
    html = render_django("<c-seg-loop c-labels=\"['a', 'b']\"/>", csp_nonce="segNonce")
    scripts = re.findall(r"<script\b[^>]*>", html)

    assert len(islands(html)) == 2
    assert scripts
    assert all('nonce="segNonce"' in tag for tag in scripts)


def test_a_request_nonce_reaches_an_island_rendered_without_a_region(render, rf):
    request = rf.get("/")
    request.csp_nonce = "directNonce"
    html = render("<c-seg-loop c-labels=\"['a']\"/>", request=request)

    assert len(islands(html)) == 1
    assert all('nonce="directNonce"' in tag for tag in re.findall(r"<script\b[^>]*>", html))


@pytest.mark.parametrize("strategy", ["simple", "ignore"])
def test_an_island_without_its_scripts_is_refused(render_django, settings, strategy):
    settings.CITRY_DEPS_STRATEGY = strategy
    with pytest.raises(IslandStrategyError):
        render_django("<c-seg-loop c-labels=\"['a']\"/>")


def test_an_island_inside_a_components_p_is_refused(render_django):
    with pytest.raises(IslandPlacementError, match="inside <p>"):
        render_django("<c-seg-in-p c-show='True'/>")


def test_a_static_component_holding_an_island_stays_static(render_django):
    """Only the component that needs Vue becomes an island, at any depth, so
    the static component around it keeps its assets with the page."""
    html = render_django("<c-seg-outer c-show='True'/>")
    found = islands(html)

    assert len(found) == 1
    assert html.count(".inner{color:green}") == 1
    # The inner section is outside the island: Vue owns only the button.
    assert html.index("class='inner'") < html.index('id="citry-vue-')
