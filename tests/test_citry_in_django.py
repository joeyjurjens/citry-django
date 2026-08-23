"""
Citry regions inside ordinary Django templates.

The contract is one rule, symmetric in both directions::

    `{% ... %}` is Django. `{{ ... }}` and `<c-*>` are Citry.

So these come in two halves: everything Citry allows must work here, because
Citry's own parser compiles the region; and Django's tags must keep working
unchanged on both sides of the boundary.
"""

import pytest

from citry_django.rewrite import rewrite_source


@pytest.fixture(autouse=True)
def _fixtures(component):
    component('<h1 class="title-bar">{{ title }}</h1>', name="title-bar")
    component('<div class="wrapper"><c-slot/></div>', name="wrapper")
    component(
        '<section><header><c-slot name="head"/></header><main><c-slot/></main></section>',
        name="region-panel",
    )
    component('{% load crispy_forms_tags %}<div class="who">{% crispy form %}</div>', name="who")
    component('<b class="tag">{{ label }}</b>', name="tag")
    component('<div class="fb"><c-slot>fallback</c-slot></div>', name="fb")
    component("<section>{{ body }}</section>", name="takesbody")


class TestEverythingCitryAllows:
    def test_loaded_tag_inside_nested_template_input(self, render_django):
        out = render_django(
            "{% load django_bootstrap5 %}"
            "<c-takesbody c-body='<>{% bootstrap_button \"nested\" %}</>'/>"
        )
        assert ">nested</button>" in out

    @pytest.mark.parametrize(
        ("attribute", "context", "expected"),
        [
            ('c-title="6 * 7"', {}, ">42<"),
            ("""c-title="page['name'].upper()\"""", {"page": {"name": "deep"}}, "DEEP"),
            ("""c-title="'yes' if n > 2 else 'no'\"""", {"n": 5}, ">yes<"),
            ('c-title="len(items)"', {"items": [1, 2, 3]}, ">3<"),
        ],
    )
    def test_c_attributes_are_python(self, render_django, attribute, context, expected):
        assert expected in render_django(f"<c-title-bar {attribute}/>", **context)

    def test_interpolation_is_python_inside_a_region(self, render_django):
        """
        `{{ }}` is Citry's *inside* a region; outside one it is still Django's.

        That asymmetry is deliberate: a Django template is Django's file, so its
        existing `{{ page.title }}` keeps meaning what it always meant.
        """
        assert "a, b" in render_django(
            "<c-wrapper>{{ ', '.join(names) }}</c-wrapper>", names=["a", "b"]
        )

    def test_interpolation_outside_a_region_is_django(self, render_django):
        out = render_django("<p>{{ page.title }}</p>", page={"title": "Django's"})
        assert "Django&#x27;s" in out or "Django's" in out

    def test_c_if(self, render_django):
        source = '<c-if cond="n > 2"><b>big</b></c-if>'
        assert ">big<" in render_django(source, n=5)
        assert "big" not in render_django(source, n=1)

    def test_c_if_else_sibling_chain(self, render_django):
        """Siblings must land in one region, or Citry sees a stray `<c-else>`."""
        source = '<c-if cond="flag"><b>yes</b></c-if>\n  <c-else><i>no</i></c-else>'
        assert ">yes<" in render_django(source, flag=True)
        assert ">no<" in render_django(source, flag=False)

    def test_c_for_and_c_empty(self, render_django):
        source = '<c-for each="i in items"><i>{{ i }}</i></c-for><c-empty><em>none</em></c-empty>'
        # render_template() deliberately uses a transparent synthetic root, so
        # its own plain HTML gets no component identity attribute.
        assert render_django(source, items=[1, 2]).count("<i>") == 2
        assert "none" in render_django(source, items=[])

    def test_named_fills(self, render_django):
        out = render_django(
            '<c-region-panel><c-fill name="head">Title</c-fill>'
            '<c-fill name="default">Main</c-fill></c-region-panel>'
        )
        assert "<header>Title</header>" in out and "<main>Main</main>" in out

    def test_default_slot_from_the_element_body(self, render_django):
        out = render_django("<c-wrapper>Body <b>here</b></c-wrapper>")
        assert '<div class="wrapper"' in out and "Body <b>here</b>" in out

    def test_dynamic_component_name(self, render_django):
        """Citry's own answer to a dynamic component, so no extra tag is needed."""
        out = render_django('<c-component c-is="which" label="dyn"/>', which="tag")
        assert '<b class="tag"' in out and "dyn" in out

    def test_nested_and_self_nested_components(self, render_django):
        out = render_django(
            """<c-wrapper><c-wrapper><c-title-bar c-title="'deep'"/></c-wrapper></c-wrapper>"""
        )
        assert out.count('class="wrapper"') == 2 and "deep" in out

    def test_element_key_metadata_attribute(self, render_django):
        out = render_django(
            '<c-for each="i in items"><b #c-key="i">{{ i }}</b></c-for>', items=[1, 2]
        )
        assert "data-citry-key" in out

    def test_slot_fallback(self, render_django):
        assert "fallback" in render_django("<c-fb/>")
        assert "given" in render_django("<c-fb>given</c-fb>")


class TestDjangoKeepsWorking:
    def test_region_discovery_tolerates_django_controlled_partial_html(self, render_django):
        source = "{% if open_div %}<div>{% endif %}<c-title-bar c-title=\"'inside'\"/>"

        opened = render_django(source, open_div=True)
        closed = render_django(source, open_div=False)

        assert opened.startswith("<div>") and "inside" in opened
        assert not closed.startswith("<div>") and "inside" in closed

    def test_component_like_text_inside_raw_html_or_an_attribute_stays_literal(self):
        source = '<script>const x = "<c-title-bar/>";</script><div data-x="<c-title-bar/>"></div>'

        assert rewrite_source(source) == source

    def test_tags_outside_a_region(self, render_django):
        out = render_django("{% load django_bootstrap5 %}<div>{% bootstrap_button 'x' %}</div>")
        assert "<button" in out and ">x</button>" in out

    def test_tags_inside_a_region(self, render_django):
        out = render_django(
            '{% load django_bootstrap5 %}<c-wrapper>{% bootstrap_button "in-body" %}</c-wrapper>'
        )
        assert "<button" in out and "in-body" in out

    def test_tag_inside_a_component_template(self, render_django, rf):
        """
        The component's own `{% load %}` travels with it, and so does the
        request: `{% crispy %}` emits a CSRF token only when it finds one.
        """
        from django import forms

        form = type("F", (forms.Form,), {"name": forms.CharField()})()
        out = render_django('<c-who c-form="form"/>', request=rf.get("/here/"), form=form)
        assert 'class="who"' in out and "csrfmiddlewaretoken" in out

    def test_fill_body_may_contain_django_tags(self, render_django):
        out = render_django(
            "{% load django_bootstrap5 %}<c-region-panel>"
            '<c-fill name="head">{% bootstrap_button "H" %}</c-fill>'
            '<c-fill name="default">{% bootstrap_button "B" %}</c-fill></c-region-panel>'
        )
        assert out.count("<button") == 2 and "<header>" in out

    def test_control_flow_around_a_region(self, render_django):
        out = render_django(
            '{% for item in items %}<c-title-bar c-title="item"/>{% endfor %}', items=["a", "b"]
        )
        assert out.count('class="title-bar"') == 2

    def test_loop_variable_reaches_citry(self, render_django):
        out = render_django(
            '{% for item in items %}<c-title-bar c-title="item.upper()"/>{% endfor %}',
            items=["a", "b"],
        )
        assert ">A<" in out and ">B<" in out

    def test_with_block_around_a_region(self, render_django):
        assert "scoped" in render_django(
            '{% with n="scoped" %}<c-title-bar c-title="n"/>{% endwith %}'
        )

    def test_if_around_a_region(self, render_django):
        source = """{% if show %}<c-title-bar c-title="'shown'"/>{% endif %}"""
        assert "shown" in render_django(source, show=True)
        assert "shown" not in render_django(source, show=False)

    def test_region_inside_a_django_block(self, render_django):
        source = "{% if on %}<c-wrapper>shown</c-wrapper>{% endif %}"
        assert 'class="wrapper"' in render_django(source, on=True)
        assert "card" not in render_django(source, on=False)

    def test_inheritance_and_blocks_are_untouched(self, render_django):
        assert render_django("A[{% block c %}base{% endblock %}]B") == "A[base]B"


class TestRewriter:
    def test_a_template_without_citry_syntax_is_byte_for_byte(self):
        source = "{% load django_bootstrap5 %}<div>{% bootstrap_button 'x' %}</div>"
        assert rewrite_source(source) == source

    def test_verbatim_is_left_alone(self, render_django):
        out = render_django('{% verbatim %}<c-title-bar title="raw"/>{% endverbatim %}')
        assert '<c-title-bar title="raw"/>' in out

    def test_attribute_value_containing_quotes_and_angle_brackets(self, render_django):
        """
        Double quotes and a `>` inside a single-quoted attribute: neither may
        terminate the tag early. Re-quoting this into a Django tag argument is
        exactly what the region's hex encoding avoids.
        """
        assert "a &gt; b" in render_django("""<c-title-bar c-title='"a > b"'/>""")

    def test_an_unclosed_element_is_reported(self, render_django):
        """
        Citry's parser decides what is well-formed, so a malformed element is an
        error naming the problem rather than markup silently leaking as text.
        """
        with pytest.raises(ValueError, match="could not read") as exc:
            render_django("<c-wrapper>never closed")
        assert "well-formed" in str(exc.value)

    def test_an_unknown_component_names_the_problem(self, render_django):
        with pytest.raises(Exception, match="does-not-exist"):
            render_django("<c-does-not-exist/>")
