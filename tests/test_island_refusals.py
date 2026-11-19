"""Places and settings where a Vue island would break without an error.

Vue mounts an island on a `<div>`. The browser moves or drops a `<div>` in
some places, and some asset strategies write no scripts, so the island would
show up in the wrong place or do nothing. citry-django raises instead.
"""

from __future__ import annotations

import pytest

from citry_django.islands import IslandPlacementError, IslandStrategyError, OpenElements


@pytest.fixture(autouse=True)
def fixtures(component):
    # `js_data()` is enough to make Citry hand the component to Vue.
    component(
        '<span class="live">live</span>',
        name="island-live",
        js_data=lambda self, kwargs, slots: {"on": True},
    )
    component('<span class="still">still</span>', name="island-still")


class TestPlacement:
    @pytest.mark.parametrize(
        ("source", "parent"),
        [
            ("<p>Hi <c-island-live/></p>", "p"),
            ("<p><span><c-island-live/></span></p>", "p"),
            ("<table><c-island-live/></table>", "table"),
            ("<table><tbody><c-island-live/></tbody></table>", "tbody"),
            ("<table><tr><c-island-live/></tr></table>", "tr"),
            ("<select><c-island-live/></select>", "select"),
            ("<select><option><c-island-live/></option></select>", "select"),
            ("<svg><g><c-island-live/></g></svg>", "svg"),
            ("{% if show %}<p>{% endif %}<c-island-live/>", "p"),
        ],
    )
    def test_a_host_the_browser_would_move_is_refused(self, render_django, source, parent):
        with pytest.raises(IslandPlacementError, match=f"inside <{parent}>"):
            render_django(source, show=True)

    @pytest.mark.parametrize(
        "source",
        [
            "<ul><li><c-island-live/></li></ul>",
            "<table><tr><td><c-island-live/></td></tr></table>",
            "<p>closed</p><c-island-live/>",
            "<p>closed by the div<div><c-island-live/></div>",
            "<svg><foreignObject><c-island-live/></foreignObject></svg>",
            "<div><button><c-island-live/></button></div>",
        ],
    )
    def test_a_host_where_a_div_may_stand_renders(self, render_django, source):
        assert 'class="live"' in render_django(source)

    def test_a_component_without_vue_may_stand_anywhere(self, render_django):
        html = render_django("<p>Hi <c-island-still/></p><table><c-island-still/></table>")
        assert html.count('class="still"') == 2

    def test_the_message_names_the_template_and_the_way_out(self, render_django):
        with pytest.raises(IslandPlacementError) as error:
            render_django("<p><c-island-live/></p>")
        assert "<string template>" in str(error.value)
        assert "Move the <p> into the component's own template" in str(error.value)


class TestStrategy:
    @pytest.mark.parametrize("strategy", ["simple", "ignore"])
    def test_an_island_without_its_scripts_is_refused(self, render_django, settings, strategy):
        settings.CITRY_DEPS_STRATEGY = strategy
        with pytest.raises(IslandStrategyError, match=f'CITRY_DEPS_STRATEGY = "{strategy}"'):
            render_django("<c-island-live/>")

    @pytest.mark.parametrize("strategy", ["simple", "ignore"])
    def test_a_static_region_keeps_working(self, render_django, settings, strategy):
        settings.CITRY_DEPS_STRATEGY = strategy
        assert 'class="still"' in render_django("<c-island-still/>")


class TestOpenElements:
    """The parser rules the refusals rely on, one case each."""

    @pytest.mark.parametrize(
        ("markup", "stack"),
        [
            ("<div><p>text", ["div", "p"]),
            ("<p>text<ul><li>a<li>b", ["ul", "li"]),
            ("<table><tr><td>a<td>b", ["table", "tr", "td"]),
            ("<table><tr><td>a</td><tr>", ["table", "tr"]),
            ("<br><img src=x><input>", []),
            ('<div title="a > b"><!-- <p> -->', ["div"]),
            ("<script>if (a<p) {}</script><span>", ["span"]),
            ("<select><option>a<option>b", ["select", "option"]),
        ],
    )
    def test_what_is_open_after_markup(self, markup, stack):
        state = OpenElements()
        state.feed(markup)
        assert state.stack == stack
