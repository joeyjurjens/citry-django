"""A block with Events, placed by a Django template inside another region's slot.

Citry 0.5.1 refused to serialize this, and citry-django patched it. Citry 1.0
renders it as is, so the patch is gone and this checks it stays that way.
"""

from __future__ import annotations

import pytest
from wagtail.blocks import StructBlock

BLOCKS = [
    "events_only",
    "slotted_only",
    "events_then_slotted",
    "slotted_then_events",
    "events_then_fills",
    "fills_then_events",
    "events_then_js_fills",
    "js_fills_then_events",
]


class Events:
    def ping(self):
        return None


class Fixture:
    """The block a Django template places inside another component's slot."""

    def __init__(self, name):
        class NestedBlock(StructBlock):
            class Meta:
                template = f"nested_blocks/{name}.html"

        self.value = NestedBlock().to_python({})


@pytest.fixture
def mounted(citry_app):
    previous = citry_app.mounted_prefix
    citry_app.set_mounted_prefix("/citry")
    yield
    citry_app._mounted_prefix = previous


@pytest.fixture
def components(component, mounted):
    component('<button @c-click="ping">ping</button>', "patch-probe", Events=Events)
    component("<aside><c-slot/></aside>", "patch-slotted")
    component("<aside><c-slot name='toggle'/><c-slot name='default'/></aside>", "patch-fills")
    component(
        "<aside><c-slot name='toggle'/><c-slot name='default'/></aside>",
        "patch-js-fills",
        js="console.log('patch-js-fills')",
    )
    component("<section><c-slot/></section>", "patch-wrapper")


@pytest.mark.parametrize("name", BLOCKS)
def test_a_block_with_events_renders_inside_another_regions_slot(
    components, render_django, rf, name
):
    html = render_django(
        "{% load wagtailcore_tags %}"
        "<html><head><c-css/></head><body>"
        "<c-patch-wrapper>{% include_block value %}</c-patch-wrapper>"
        "<c-js/></body></html>",
        request=rf.get("/"),
        value=Fixture(name).value,
    )

    assert "<section" in html
    assert ("ping</button>" in html) == ("events" in name)
