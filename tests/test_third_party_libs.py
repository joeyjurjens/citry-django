"""
Real third-party Django tag libraries, inside Citry components.

The adapter names no tag and knows none of these packages, so each case is
checked against a plain Django engine rendering the same source rather than
against a string somebody typed out.

The libraries were picked for shapes that are awkward to support:

* ``django-compressor`` -- ``{% compress %}`` **reads its own body** to hash and
  rewrite it. Anything less than the body's real text breaks it, which is
  exactly what a stand-in would have been.
* ``django-crispy-forms`` -- ``{% crispy %}`` renders a whole form through the
  library's *own* templates, pulling in a second template pass, and is
  ``takes_context``.
* ``sorl-thumbnail`` -- ``{% thumbnail ... as var %}`` **binds a variable** for
  the length of its body, so the two engines have to share one live scope.
* ``django-widget-tweaks`` -- ``{% render_field %}`` takes a form field plus
  arbitrary keyword arguments.
* ``django-bootstrap5`` -- ordinary simple tags with positional and keyword
  arguments, the commonest shape of all.
* ``django.contrib.humanize`` -- ordinary filters, which have to survive the
  ``{{ }}`` ownership rule.
"""

import pytest
from django import forms


class Contact(forms.Form):
    name = forms.CharField(label="Name")
    email = forms.EmailField(label="Email")


@pytest.fixture
def same(render, render_vanilla, strip_cids):
    """Render through both engines and require the Citry one to match Django."""

    def check(source, **context):
        expected = render_vanilla(source, **context)
        actual = strip_cids(render(source, **context))
        assert actual.strip() == expected.strip()

    return check


@pytest.mark.parametrize(
    ("source", "context"),
    [
        pytest.param(
            "{% load compress %}{% compress css %}"
            '<style type="text/css">.a{color:red}</style>'
            "{% endcompress %}",
            {},
            id="compress-css",
        ),
        pytest.param(
            "{% load crispy_forms_tags %}{% crispy form %}", {"form": Contact}, id="crispy-tag"
        ),
        pytest.param(
            "{% load crispy_forms_filters %}{{ form|crispy }}",
            {"form": Contact},
            id="crispy-filter",
        ),
        pytest.param(
            "{% load widget_tweaks %}{% render_field form.name "
            'class="form-control" placeholder="Your name" %}',
            {"form": Contact},
            id="render_field",
        ),
        pytest.param(
            '{% load widget_tweaks %}{{ form.email|add_class:"x" }}',
            {"form": Contact},
            id="add_class",
        ),
        pytest.param("{% load humanize %}{{ n|intcomma }}", {"n": 1234567}, id="intcomma"),
        pytest.param("{% load humanize %}{{ n|apnumber }}", {"n": 4}, id="apnumber"),
        pytest.param("{% load humanize %}{{ n|ordinal }}", {"n": 23}, id="ordinal"),
        pytest.param(
            '{% load django_bootstrap5 %}{% bootstrap_button "Save" button_type="submit" %}',
            {},
            id="bootstrap_button",
        ),
        pytest.param(
            "{% load django_bootstrap5 %}{% bootstrap_form form %}",
            {"form": Contact},
            id="bootstrap_form",
        ),
    ],
)
def test_matches_a_plain_django_render(same, source, context):
    # Forms are passed as the class so each engine gets its own instance;
    # a shared bound form would compare its own auto-generated ids.
    same(source, **{k: v() if isinstance(v, type) else v for k, v in context.items()})


def test_compress_around_a_citry_expression(render):
    """The body is part Citry, so the tag must still receive real text."""
    out = render(
        "{% load compress %}{% compress css %}"
        '<style type="text/css">.a{color:{{ shade }}}</style>'
        "{% endcompress %}",
        shade="red",
    )
    # Compressor replaced the block with markup it produced itself, which it
    # could only do by hashing the real rendered text.
    assert "<style" in out or "<link" in out
    assert "{{" not in out and "\x00" not in out


def test_library_tag_inside_a_citry_loop(render):
    out = render(
        '{% load humanize %}<ul><c-for each="i in nums"><li>{{ i }}</li></c-for></ul>', nums=[1, 2]
    )
    assert out.count("<li>") == 2


def test_citry_expression_beside_a_library_filter(render):
    out = render(
        "{% load humanize %}<p>{{ ', '.join(names) }}</p><p>{{ n|intcomma }}</p>",
        names=["a", "b"],
        n=9999,
    )
    assert "a, b" in out and "9,999" in out


def test_library_tag_inside_a_nested_component(render, component):
    component(
        '{% load widget_tweaks %}<div class="row">{% render_field field class="fc" %}</div>',
        name="field-row",
    )
    out = render("""<c-field-row c-field="form['name']"/>""", form=Contact())
    assert 'class="fc"' in out and 'class="row"' in out


def test_thumbnail_binds_a_variable_its_body_reads(render, site):
    """
    sorl-thumbnail's block tag binds `th` for the length of its body, and the
    interpolation inside reads it. Django binds names at render time, so this
    only works if Citry reads the live context rather than a snapshot.
    """
    out = render(
        '{% load thumbnail %}{% thumbnail img.file "100x100" as th %}'
        '<img src="{{ th.url }}" width="{{ th.width }}">'
        "{% endthumbnail %}",
        img=site["image"],
    )
    assert "/media/cache/" in out
    assert 'width="100"' in out
