"""
Django syntax inside a dynamic attribute, behind ``django_attrs=True``.

Citry reads ``c-x="..."`` as Python, so ``{{ }}`` and ``{% %}`` are a parse
error there. With the option on, both are taken out of the source before
Citry's parser sees them, by two different routes: a lone dotted path keeps its
value an object, and everything else becomes a string Django renders.
"""

import pytest
from django.template.base import VariableDoesNotExist

from citry_django.django_attrs import django_lookup, rewrite_attrs


@pytest.fixture
def django_attrs(citry_app):
    """Turn the option on for one test."""
    extension = citry_app.extensions.get_extension("citry_django")
    extension.django_attrs = True
    try:
        yield
    finally:
        extension.django_attrs = False


class TestOption:
    """The flag itself. The fixtures below set it on a live instance, which
    would keep passing if the constructor never accepted it."""

    def test_the_extension_takes_it(self):
        from citry_django import CitryDjangoExtension

        assert CitryDjangoExtension(django_attrs=True).django_attrs is True

    def test_it_is_off_unless_asked_for(self):
        from citry_django import CitryDjangoExtension

        assert CitryDjangoExtension().django_attrs is False

    def test_it_sits_beside_the_tokenizer(self):
        from citry_django import CitryDjangoExtension

        extension = CitryDjangoExtension(tokenizer=len, django_attrs=True)
        assert extension.tokenizer is len
        assert extension.django_attrs is True


class TestRewrite:
    """The source transform, which is where the two routes are chosen."""

    def test_a_lone_dotted_path_becomes_a_lookup_call(self):
        assert rewrite_attrs('<c-x c-bind="{{ a.b.c }}" />') == (
            "<c-x c-bind=\"citry_django_lookup(a, 'b.c')\" />"
        )

    def test_a_bare_name_is_left_to_citry(self):
        """Both engines resolve one identically, so Citry's strictness is kept."""
        assert rewrite_attrs('<c-x c-v="{{ a }}" />') == '<c-x c-v="a" />'

    def test_a_tag_loses_the_prefix_and_becomes_an_ordinary_attribute(self):
        assert rewrite_attrs("<c-x c-url=\"{% url 'home' %}\" />") == (
            "<c-x url=\"{% url 'home' %}\" />"
        )

    def test_text_around_the_interpolation_is_a_string_too(self):
        assert rewrite_attrs('<c-x c-class="btn {{ a.b }}" />') == '<c-x class="btn {{ a.b }}" />'

    def test_a_filter_is_a_string(self):
        assert rewrite_attrs('<c-x c-v="{{ a|upper }}" />') == '<c-x v="{{ a|upper }}" />'

    def test_python_is_left_alone(self):
        source = '<c-x c-v="d[\'k\']" c-n="1 + 1" />'
        assert rewrite_attrs(source) == source

    def test_a_static_attribute_is_left_alone(self):
        source = '<c-x v="{{ a.b }}" />'
        assert rewrite_attrs(source) == source

    def test_single_quotes_become_double_so_the_call_can_quote_its_argument(self):
        assert rewrite_attrs("<c-x c-bind='{{ a.b }}' />") == (
            "<c-x c-bind=\"citry_django_lookup(a, 'b')\" />"
        )


class TestLookup:
    """Django's resolution order, on the real object."""

    def test_a_key_wins_over_an_attribute(self):
        class Both(dict):
            b = "attribute"

        assert django_lookup({"o": Both(b="key")}, "o.b") == "key"

    def test_an_attribute_when_there_is_no_key(self):
        class Thing:
            b = "attribute"

        assert django_lookup({"o": Thing()}, "o.b") == "attribute"

    def test_a_numeric_index(self):
        assert django_lookup({"l": ["first", "second"]}, "l.1") == "second"

    def test_a_callable_is_called(self):
        class Thing:
            def b(self):
                return "called"

        assert django_lookup({"o": Thing()}, "o.b") == "called"

    def test_a_chain_walks_every_step(self):
        assert django_lookup({"a": {"b": {"c": 1}}}, "a.b.c") == 1

    def test_a_name_that_is_not_there_raises(self):
        with pytest.raises(VariableDoesNotExist):
            django_lookup({}, "nope")

    def test_a_method_that_alters_data_is_not_called(self):
        """Django's own guard, which is the reason to delegate to it."""

        class Thing:
            def wipe(self):
                return "called"

            wipe.alters_data = True

        assert django_lookup({"t": Thing()}, "t.wipe") == ""


class TestRendering:
    """End to end, through the project's engine."""

    def test_a_value_arrives_as_an_object_not_as_text(self, django_attrs, component, render_django):
        component('<i>{{ value["name"] }}</i>', name="reads-key")
        html = render_django('<c-reads-key c-value="{{ d.icon }}" />', d={"icon": {"name": "star"}})
        assert "star" in html

    def test_a_tag_arrives_as_its_rendered_string(self, django_attrs, component, render_django):
        component("<i>{{ label }}</i>", name="takes-label")
        html = render_django("{% load i18n %}<c-takes-label c-label=\"{% trans 'Menu' %}\" />")
        assert "Menu" in html

    def test_a_dotted_path_resolves_a_dictionary_key(self, django_attrs, component, render_django):
        component("<i>{{ v }}</i>", name="shows-v")
        html = render_django('<c-shows-v c-v="{{ d.k }}" />', d={"k": "found"})
        assert "found" in html

    def test_off_by_default(self, component, render_django):
        """Without the option Citry's parser reaches the `{{ }}` and says so."""
        component("<i>{{ v }}</i>", name="shows-v-off")
        with pytest.raises(ValueError, match="could not read"):
            render_django('<c-shows-v-off c-v="{{ d.k }}" />', d={"k": "found"})
