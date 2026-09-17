import pytest
from citry import Component
from testproject.citry_app import app

from citry_django.registry import citry_app_source

#: What the component below was handed, cleared per test by the fixture.
RECEIVED: list = []


class Probe(Component):
    """Records the input it was handed, so a test can assert on the value
    rather than on how it rendered."""

    citry = app

    class Kwargs:
        thing: object = None

    def template_data(self, kwargs, slots):
        RECEIVED.append(kwargs.thing)
        return {}

    template = "<i></i>"


app.register(Probe, "probe")


@pytest.fixture
def receiver():
    RECEIVED.clear()
    return RECEIVED


class TestWhatAnInputReceives:
    def test_a_dotted_path_arrives_as_the_object(self, receiver, render_django):
        render_django('<c-probe thing="{{ d.k }}" />', d={"k": {"nested": 1}})
        assert receiver == [{"nested": 1}]

    def test_a_bare_name_arrives_as_the_object(self, receiver, render_django):
        render_django('<c-probe thing="{{ n }}" />', n=42)
        assert receiver == [42]

    def test_text_beside_it_makes_a_string(self, receiver, render_django):
        """Nothing else it could be, so the interpolation is rendered."""
        render_django('<c-probe thing="{{ n }}px" />', n=42)
        assert receiver == ["42px"]

    def test_a_filter_makes_a_string(self, receiver, render_django):
        render_django('<c-probe thing="{{ s|upper }}" />', s="hoi")
        assert receiver == ["HOI"]

    def test_a_tag_makes_a_string(self, receiver, render_django):
        render_django("{% load i18n %}<c-probe thing=\"{% trans 'Hoi' %}\" />")
        assert receiver == ["Hoi"]

    def test_a_missing_name_is_djangos_empty_string(self, receiver, render_django):
        """Django's rule, not Citry's: the point of writing `{{ }}` is that the
        path means what it means in Django."""
        render_django('<c-probe thing="{{ nowhere.near }}" />')
        assert receiver == [""]


class TestWhatStaysCitrys:
    def test_a_c_attribute_is_python(self, component, render_django):
        component("<i>{{ label }}</i>", name="py")
        assert "6" in render_django('<c-py c-label="2 * 3" />')

    def test_a_citry_expression_is_not_claimed(self, component, render):
        """Both engines spell interpolation the same way, so a `{{ }}` Django
        cannot parse is Citry's. `len` is one of the engine's globals."""
        assert "3" in render("<p>{{ len(items) }}</p>", items=[1, 2, 3])


class TestConfiguration:
    def test_citry_app_may_name_a_callable(self, settings, monkeypatch):
        """A project with an engine per framework picks one per render."""
        from citry import Citry

        from citry_django import CitryDjangoExtension

        first = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
        second = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
        chosen = [first]

        import testproject.citry_app as app_module

        monkeypatch.setattr(app_module, "pick_engine", lambda: chosen[0], raising=False)
        settings.CITRY_APP = "testproject.citry_app:pick_engine"
        citry_app_source.cache_clear()
        try:
            from citry_django.registry import get_citry_app

            assert get_citry_app() is first
            chosen[0] = second
            assert get_citry_app() is second
        finally:
            citry_app_source.cache_clear()


class TestPageAssets:
    """What every region on one page asked for, placed once."""

    def test_a_components_assets_reach_the_page(self, component, render_django):
        component("<div>x</div>", name="page-css", css=".x{color:red}")
        html = render_django("<c-page-css />")
        assert ".x{color:red}" in html

    def test_two_regions_share_one_runtime(self, component, render_django):
        """The whole reason the page places them: a runtime per region is a
        runtime too many, and the second would re-register the first's."""
        component("<div>a</div>", name="page-a", css=".a{}", js="plain()")
        component("<div>b</div>", name="page-b", css=".b{}", js="plain()")
        html = render_django("<c-page-a /><p>between</p><c-page-b />")
        assert ".a{}" in html
        assert ".b{}" in html
        assert html.count("<script") == 1

    def test_a_region_outside_a_page_places_its_own(self, component, render_django):
        """A page is one backend render; without one there is nothing to wait
        for, so Citry's own default applies."""
        component("<i>x</i>", name="solo", css=".solo{}")
        rendered = app.render_template("<c-solo />", {})
        assert ".solo{}" in rendered.serialize()

    def test_a_placeholder_decides_where_they_land(self, component, render_django):
        """`<c-css/>` names the spot, and the whole page's assets go there.

        A Django template renders each region separately, so a `<c-css/>` in
        the head is a render of its own and knows nothing of the component in
        the body. The page is what brings the two together.
        """
        component("<div>x</div>", name="page-head", css=".head{}")
        html = render_django("<head><c-css /></head><body><c-page-head /></body>")
        assert ".head{}" in html.split("</head>")[0]

    def test_a_nonce_does_not_stop_the_page_collecting(self, component, render_django):
        """What Citry emits depends on the request, and nothing here reads it.

        A nonce changes every tag Citry writes. The page finds them by the
        spots a region marked, not by matching the markup it expected, so a
        host with a Content-Security-Policy collects like any other.
        """
        component("<div>x</div>", name="page-nonce", css=".nonce{}", js="plain()")
        html = render_django(
            "<head><c-css /></head><body><c-page-nonce /><c-page-nonce /></body>",
            csp_nonce="r4nd0m",
        )
        head, body = html.split("</head>")
        assert 'nonce="r4nd0m"' in head
        assert ".nonce{}" in head
        assert body.count("<script") == 1

    def test_a_stored_region_carries_its_own_assets(self, component, render_django):
        """A region's markup stands on its own, so a host may keep it.

        This is the whole reason a region places its assets rather than handing
        them over: `{% cache %}`, a rendered base template in a module-level
        dict, a fragment stored and sent back later. What the host kept works
        on the page it is rendered into.
        """
        component("<div>x</div>", name="page-stored", css=".stored{}")
        stored = render_django("<c-page-stored />")
        assert ".stored{}" in stored


class TestPageAssetsNesting:
    """What the page collects when the regions are not one flat row."""

    def test_components_nested_three_deep_all_reach_the_page(self, component, render_django):
        """One region, three components: what the innermost asked for goes too.

        Nesting here is Citry's own. The region is one render however deep it
        goes, so this is really a check that nothing is lost on the way out.
        """
        component("<i>deep</i>", name="nest-inner", css=".inner{}")
        component("<span><c-nest-inner /></span>", name="nest-middle", css=".middle{}")
        component("<div><c-nest-middle /></div>", name="nest-outer", css=".outer{}")

        head = render_django("<head><c-css /></head><body><c-nest-outer /></body>").split(
            "</head>"
        )[0]
        assert ".inner{}" in head
        assert ".middle{}" in head
        assert ".outer{}" in head

    def test_two_regions_sharing_a_nested_component_place_it_once(self, component, render_django):
        """The repeat the page exists to drop, found two levels down."""
        component("<i>x</i>", name="share-inner", css=".shared{}")
        component("<span><c-share-inner /></span>", name="share-a")
        component("<div><c-share-inner /></div>", name="share-b")

        html = render_django(
            "<head><c-css /></head><body><c-share-a /><p>between</p><c-share-b /></body>"
        )
        assert html.count(".shared{}") == 1

    def test_an_included_template_collects_into_the_same_page(self, component, render_django):
        """`{% include %}` renders its own template, not its own page.

        It goes through the engine rather than the backend, so no page opens
        for it and the regions in it belong to the page that included them.
        """
        component("<i>x</i>", name="include-partial-component", css=".partial{}", js="plain()")
        component("<b>y</b>", name="include-host-component", css=".host{}", js="plain()")

        html = render_django(
            "<head><c-css /></head><body><c-include-host-component />"
            '{% include "testproject/page_assets_partial.html" %}</body>'
        )
        head = html.split("</head>")[0]
        assert ".host{}" in head
        assert ".partial{}" in head
        assert html.count("<script") == 1

    def test_a_region_rendered_per_iteration_places_its_assets_once(self, component, render_django):
        """One region, rendered as many times as Django reaches it."""
        component("<li>x</li>", name="loop-item", css=".loop{}")

        html = render_django(
            "<head><c-css /></head><body><ul>"
            "{% for n in items %}<c-loop-item />{% endfor %}</ul></body>",
            items=[1, 2, 3],
        )
        assert html.count(".loop{}") == 1
        assert html.count("<li ") == 3

    def test_a_component_behind_a_django_tag_reaches_the_page(self, component, render_django):
        """A Django tag inside a component's own template still renders Citry.

        That path is `CitrySegment`, not a region of its own, so what it
        renders belongs to the region around it.
        """
        component("<i>x</i>", name="tagged-inner", css=".tagged{}")
        component("{% if show %}<c-tagged-inner />{% endif %}", name="tagged-outer")

        html = render_django('<head><c-css /></head><body><c-tagged-outer c-show="True" /></body>')
        assert ".tagged{}" in html.split("</head>")[0]
