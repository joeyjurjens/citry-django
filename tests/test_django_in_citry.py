"""
Django's syntax inside a Citry component template.

Every ``{% ... %}`` is run by Django's real engine, so a tag library the adapter
has never heard of works the way it would in a Django template. The libraries
used here are real, installed packages -- django-bootstrap5, django-crispy-forms,
sorl-thumbnail, django.contrib.humanize -- picked for tag shapes that are
awkward to support. Nothing in the adapter names any of them.
"""

import pytest
from citry import Component
from django import forms


class Contact(forms.Form):
    name = forms.CharField(label="Name")
    email = forms.EmailField(label="Email")


@pytest.fixture(autouse=True)
def _fixtures(component):
    component('<b class="alert">{{ msg }}</b>', name="alert")
    component('<span class="chip">{{ label }}</span>', name="chip")


class TestRealTagLibraries:
    """The adapter names no tag, so an unfamiliar library is not a special case."""

    def test_simple_tag_with_positional_and_keyword_arguments(self, render):
        out = render(
            "{% load django_bootstrap5 %}"
            '<div>{% bootstrap_button "New" button_class="btn-danger" %} {{ title }}</div>',
            title="Post",
        )
        assert 'class="btn btn-danger"' in out and ">New</button>" in out
        assert "Post" in out

    def test_a_filter_from_an_installed_library(self, render):
        assert ">1,234,567<" in render("{% load humanize %}<p>{{ n|intcomma }}</p>", n=1234567)

    def test_takes_context_tag_sees_the_request(self, render, rf):
        """
        `{% crispy %}` renders a whole form through crispy's *own* templates, and
        emits a CSRF token only when there is a real request in the context. The
        token's presence is the proof that one arrived.
        """
        source = "{% load crispy_forms_tags %}{% crispy form %}"
        assert "csrfmiddlewaretoken" in render(source, request=rf.get("/dash/"), form=Contact())
        assert "csrfmiddlewaretoken" not in render(source, form=Contact())

    def test_three_libraries_in_one_component(self, render, rf):
        out = render(
            "{% load django_bootstrap5 %}{% load humanize %}{% load crispy_forms_tags %}"
            '<section>{% bootstrap_button "A" %}'
            "<p>{{ n|intcomma }}</p>"
            "{% crispy form %}</section>",
            request=rf.get("/multi/"),
            n=9999,
            form=Contact(),
        )
        assert "<button" in out and "9,999" in out and "csrfmiddlewaretoken" in out

    def test_tag_in_attribute_position(self, render):
        """Handled with a delegate node rather than a wrapper element."""
        out = render("{% load static %}<a href=\"{% static 'css/demosite.css' %}\">go</a>")
        assert 'href="/static/css/demosite.css"' in out

    def test_tag_inside_a_citry_loop(self, render):
        out = render(
            '{% load django_bootstrap5 %}<ul><c-for each="i in items">'
            '<li>{{ i * 2 }} {% bootstrap_button "n" %}</li></c-for></ul>',
            items=[1, 2, 3],
        )
        assert "<li>2 " in out and "<li>6 " in out
        assert out.count("<button") == 3


class TestInterpolationOwnership:
    """`{{ ... }}` belongs to whichever engine can actually resolve it."""

    def test_registered_filter_goes_to_django(self, render):
        assert ">4th<" in render("{% load humanize %}<p>{{ n|ordinal }}</p>", n=4)

    def test_builtin_filter_with_an_argument_goes_to_django(self, render):
        assert ">007<" in render('<p>{{ n|stringformat:"03d" }}</p>', n=7)

    def test_python_expression_stays_citry(self, render):
        assert ">a, b<" in render("<p>{{ ', '.join(names) }}</p>", names=["a", "b"])

    def test_bitwise_or_stays_citry(self, render):
        """`a | b` is a filter chain only if `b` is a registered filter."""
        assert ">5<" in render("<p>{{ a | b }}</p>", a=4, b=1)

    @pytest.mark.parametrize(
        ("template", "context", "expected"),
        [
            ("<p>{{ d.key }}</p>", {"d": {"key": "v"}}, ">v<"),
            ("<p>{{ d.a.b }}</p>", {"d": {"a": {"b": "deep"}}}, ">deep<"),
            ("<p>{{ xs.0 }}</p>", {"xs": ["a"]}, ">a<"),
        ],
    )
    def test_dotted_paths_follow_django_lookup(self, render, template, context, expected):
        """
        Django's lookup is a superset of Python's: dictionary, then attribute,
        then index. Every Django template writes `{{ d.key }}` for a dict, and
        Python attribute access fails on that, so these are Django's.
        """
        assert expected in render(template, **context)

    def test_dotted_path_on_an_object(self, render):
        obj = type("Obj", (), {"naam": "ada"})()
        assert ">ada<" in render("<p>{{ o.naam }}</p>", o=obj)

    @pytest.mark.parametrize(
        ("template", "context", "expected"),
        [
            ("<p>{{ 6 * 7 }}</p>", {}, ">42<"),
            ("<p>{{ s.upper() }}</p>", {"s": "hi"}, ">HI<"),
            ("<p>{{ n }}</p>", {"n": "x"}, ">x<"),
        ],
    )
    def test_calls_operators_and_bare_names_stay_citry(self, render, template, context, expected):
        assert expected in render(template, **context)


class TestCitryFeaturesSurvive:
    def test_slots_and_fills_with_django_tags_inside(self, render, component):
        component(
            '<div class="panel"><header><c-slot name="head"/></header><c-slot/></div>', name="panel"
        )
        out = render(
            "{% load django_bootstrap5 %}"
            '<c-panel><c-fill name="head">{% bootstrap_button "H" %}</c-fill>'
            '<c-fill name="default">{{ body }} {% bootstrap_button "B" %}</c-fill></c-panel>',
            body="text",
        )
        assert "<header>" in out and out.count("<button") == 2 and "text" in out

    def test_slot_fallback(self, render, component):
        component("<div><c-slot>fallback</c-slot></div>", name="withdefault")
        assert "fallback" in render("<c-withdefault/>")

    def test_default_slot_from_a_component_body(self, render, component):
        component('<div class="card"><c-slot/></div>', name="card2")
        out = render('{% load django_bootstrap5 %}<c-card2>{% bootstrap_button "in" %}</c-card2>')
        assert 'class="card"' in out and "<button" in out

    def test_fill_inside_a_django_block_reaches_its_slot(self, render, component):
        component('<div class="box"><c-slot/></div>', name="box")
        source = "{% if on %}<c-box>shown</c-box>{% else %}<i>off</i>{% endif %}"
        assert 'class="box"' in render(source, on=True)
        assert ">off<" in render(source, on=False)

    def test_django_block_selects_citry_fills(self, render, component):
        component(
            '<div><header><c-slot name="head">fallback head</c-slot></header>'
            "<main><c-slot>fallback body</c-slot></main></div>",
            name="hostfills",
        )
        source = (
            "<c-hostfills>{% if on %}"
            '<c-fill name="head">selected head</c-fill>'
            '<c-fill name="default">selected body</c-fill>'
            "{% endif %}</c-hostfills>"
        )

        selected = render(source, on=True)
        fallback = render(source, on=False)

        assert "selected head" in selected and "selected body" in selected
        assert "fallback head" in fallback and "fallback body" in fallback

    def test_control_flow_and_expressions_unaffected(self, render):
        out = render(
            '<c-for each="i in items"><c-if cond="i > 1"><b>{{ i * 10 }}</b></c-if></c-for>',
            items=[1, 2, 3],
        )
        assert ">20<" in out and ">30<" in out and ">10<" not in out


class TestInterleaving:
    """Neither engine could do these alone."""

    def test_django_if_wrapping_a_component(self, render):
        source = '{% if show %}<c-alert msg="hi"/>{% endif %}'
        on = render(source, show=True)
        assert '<b class="alert"' in on and "hi" in on
        assert "alert" not in render(source, show=False)

    def test_django_if_else_around_citry_content(self, render):
        source = '{% if staff %}<c-alert msg="admin"/>{% else %}<c-chip label="public"/>{% endif %}'
        assert "admin" in render(source, staff=True)
        assert "public" in render(source, staff=False)

    def test_third_party_block_tag_wrapping_citry(self, render, site):
        """
        sorl-thumbnail's `{% thumbnail %}` binds a variable for the length of its
        body. The component inside renders, *and* the interpolation reads the
        variable the tag bound -- so the two engines share one live scope.
        """
        out = render(
            '{% load thumbnail %}{% thumbnail img.file "100x100" as th %}'
            '<img src="{{ th.url }}"><c-alert msg="inside"/>'
            "{% endthumbnail %}",
            img=site["image"],
        )
        assert "/media/cache/" in out
        assert '<b class="alert"' in out and "inside" in out

    def test_citry_loop_inside_a_django_block(self, render, site):
        out = render(
            '{% load thumbnail %}{% thumbnail img.file "50x50" as th %}'
            '<c-for each="i in items"><c-chip c-label="i"/></c-for>'
            "{% endthumbnail %}",
            img=site["image"],
            items=["aa", "bb", "cc"],
        )
        assert out.count('class="chip"') == 3
        assert all(x in out for x in ("aa", "bb", "cc"))

    def test_django_block_inside_a_citry_loop(self, render):
        out = render(
            '{% load django_bootstrap5 %}<ul><c-for each="i in items">'
            '<li>{% if i %}{% bootstrap_button "on" %}{% endif %}{{ i }}</li>'
            "</c-for></ul>",
            items=[1, 0, 2],
        )
        assert out.count("<button") == 2
        assert "<li>0</li>" in out

    @pytest.mark.parametrize(
        ("outer", "inner", "present"),
        [(True, True, True), (True, False, False), (False, True, False)],
    )
    def test_nested_django_blocks_around_citry(self, render, outer, inner, present):
        out = render(
            '{% if outer %}{% if inner %}<c-alert msg="deep"/>{% endif %}{% endif %}',
            outer=outer,
            inner=inner,
        )
        assert ("deep" in out) is present


class TestDjangoScopeIsLive:
    """
    Django drives the block and hands control back per segment, so Citry reads
    the live context rather than a snapshot taken before the block ran.
    """

    def test_with_block_binding(self, render):
        assert ">5<" in render("{% with n=5 %}<p>{{ n }}</p>{% endwith %}")

    def test_loop_variable(self, render):
        out = render("{% for x in items %}<i>{{ x }}</i>{% endfor %}", items=["a", "b"])
        assert out.count("<i ") == 2 and ">a<" in out and ">b<" in out

    def test_loop_drives_components(self, render):
        out = render('{% for x in items %}<c-alert c-msg="x"/>{% endfor %}', items=["a", "b"])
        assert out.count('class="alert"') == 2 and ">a<" in out and ">b<" in out

    def test_python_expression_still_reaches_citry_in_a_block(self, render):
        assert ">42<" in render("{% if on %}<b>{{ 6 * 7 }}</b>{% endif %}", on=True)


class TestBodyConsumingTags:
    """
    Django's contract is that a node returns the text its body produced, so the
    adapter hands over finished HTML rather than a stand-in. That is what lets a
    third-party tag nobody has seen do whatever it does with its body.
    """

    def test_filter_tag_rewrites_the_body(self, render):
        out = render("{% load humanize %}{% filter intcomma %}{{ n }}{% endfilter %}", n=1234567)
        assert "1,234,567" in out

    def test_ifchanged_compares_the_body(self, render):
        out = render(
            "{% for x in n %}{% ifchanged %}{{ x }}{% endifchanged %}{% endfor %}", n=[1, 1, 2]
        )
        assert out.strip() == "12"

    @pytest.mark.parametrize(
        ("source", "context", "expected"),
        [
            ("{% blocktranslate %}Hi {{ n }}{% endblocktranslate %}", {"n": "Jo"}, "Hi Jo"),
            (
                "{% blocktranslate %}{{ a }} and {{ b }}{% endblocktranslate %}",
                {"a": "x", "b": "y"},
                "x and y",
            ),
            (
                "{% blocktranslate with v=n %}Hi {{ v }}{% endblocktranslate %}",
                {"n": "Jo"},
                "Hi Jo",
            ),
        ],
    )
    def test_blocktranslate(self, render, source, context, expected):
        """
        `{% blocktranslate %}` parses its body at compile time and permits only
        text and `{{ name }}`, rejecting any block tag outright -- so a callback
        marker cannot go there. A bare name has an exact Django spelling and both
        engines resolve it from the same variables, so it is handed over as
        source instead.
        """
        assert render("{% load i18n %}" + source, **context).strip() == expected


class TestRegionBookkeeping:
    def test_block_inside_a_nested_child_component(self, render, component):
        """
        Regression: a `{% if %}` inside a *child* component used to emit every
        branch at once. Each render gets its own `context.extra`, so the child's
        region table has to be merged upward or the markers never resolve.
        """
        component(
            '{% if flag %}<b class="yes">on</b>{% else %}<i class="no">off</i>{% endif %}',
            name="inner",
        )
        source = '<div class="outer"><c-inner c-flag="flag"/></div>'

        on = render(source, flag=True)
        assert 'class="yes"' in on and 'class="no"' not in on

        off = render(source, flag=False)
        assert 'class="no"' in off and 'class="yes"' not in off

    def test_blocks_in_sibling_components_do_not_collide(self, render, component):
        """Region ids are unique across sibling renders, not per component."""
        component('{% if a %}<b class="s1">1</b>{% endif %}', name="sib1")
        component('{% if b %}<i class="s2">2</i>{% endif %}', name="sib2")
        out = render('<c-sib1 c-a="a"/><c-sib2 c-b="b"/>', a=True, b=False)
        assert 'class="s1"' in out and 'class="s2"' not in out

    def test_a_guarded_component_is_not_rendered(self, render, citry_app):
        """Django evaluates the block, so a false branch costs nothing."""
        rendered = []

        class Spy(Component):
            citry = citry_app
            template = "<b>spy</b>"

            def template_data(self, kwargs, slots):
                rendered.append(1)
                return {}

        citry_app.register(Spy, "spy")

        source = "{% if show %}<c-spy/>{% endif %}"
        assert "spy" not in render(source, show=False)
        assert not rendered, "the guarded component was rendered anyway"
        assert "spy" in render(source, show=True)


class TestSafety:
    def test_user_data_is_not_executed_as_django_source(self, render):
        """
        Citry-rendered content reaches Django as a bound variable, not as source.
        If it were spliced into the template string, this `{% %}` coming out of
        *data* would be executed.
        """
        out = render(
            "{% load django_bootstrap5 %}{% if on %}<p>{{ bio }}</p>{% endif %}",
            on=True,
            bio='{% bootstrap_button "pwned" %}',
        )
        assert "<button" not in out
        assert "bootstrap_button" in out and "pwned" in out

    def test_escaping_still_applies_inside_a_block(self, render):
        out = render(
            "{% if on %}<p>{{ evil }}</p>{% endif %}", on=True, evil="<script>alert(1)</script>"
        )
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
