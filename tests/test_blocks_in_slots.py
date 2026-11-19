"""A Wagtail block that a Django template places inside another component's slot.

The block holds a component with Events beside one that takes a slot, so its
render sits inside the slot region of the render around it.
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
    component('<button @c-click="ping">ping</button>', "nested-probe", Events=Events)
    component("<aside><c-slot/></aside>", "nested-slotted")
    component("<aside><c-slot name='toggle'/><c-slot name='default'/></aside>", "nested-fills")
    component(
        "<aside><c-slot name='toggle'/><c-slot name='default'/></aside>",
        "nested-js-fills",
        js="console.log('nested-js-fills')",
    )
    component("<section><c-slot/></section>", "nested-wrapper")


@pytest.mark.parametrize("name", BLOCKS)
def test_a_block_with_events_renders_inside_another_regions_slot(
    components, render_django, rf, name
):
    html = render_django(
        "{% load wagtailcore_tags %}"
        "<html><head><c-css/></head><body>"
        "<c-nested-wrapper>{% include_block value %}</c-nested-wrapper>"
        "<c-js/></body></html>",
        request=rf.get("/"),
        value=Fixture(name).value,
    )

    assert "<section" in html
    assert ("ping</button>" in html) == ("events" in name)
