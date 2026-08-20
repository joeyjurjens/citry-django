"""
wagtail-block-components, a library whose tags are unusually demanding.

`{% wagtail_block %}` and `{% block_field %}` do not render their bodies at all
in the usual sense. They walk their own `nodelist` looking for specific node
*types*, assemble a raw value from what they find, and hand it to Wagtail's
`to_python()` and `IncludeBlockNode`.

That makes it the sharpest test of the node contract: a stand-in node in the
body would be invisible to a tag that inspects nodes rather than text, so the
field would silently come out empty.
"""

import pytest


@pytest.fixture
def block(render):
    def _render(source, **context):
        return render("{% load wagtail_block_components %}" + source, **context)

    return _render


def test_kwargs_form(block, db):
    out = block('{% wagtail_block "AccordionItemBlock" title="From kwargs" / %}')
    assert "From kwargs" in out


def test_block_field_with_body_content(block, db):
    out = block(
        '{% wagtail_block "AccordionItemBlock" %}'
        '{% block_field "title" %}Question {{ n }}{% endblock_field %}'
        "{% endwagtail_block %}",
        n=1,
    )
    assert "Question 1" in out


def test_block_field_shorthand_with_a_variable(block, db):
    out = block(
        '{% wagtail_block "AccordionItemBlock" %}'
        '{% block_field "title" heading / %}'
        "{% endwagtail_block %}",
        heading="From a variable",
    )
    assert "From a variable" in out


def test_streamblock_with_nested_typed_fields(block, db):
    out = block(
        '{% wagtail_block "AccordionItemBlock" title="T" %}'
        '{% block_field "content" %}'
        '{% block_field "paragraph" %}<p>First</p>{% endblock_field %}'
        '{% block_field "paragraph" %}<p>Second</p>{% endblock_field %}'
        "{% endblock_field %}"
        "{% endwagtail_block %}"
    )
    assert "First" in out and "Second" in out


def test_listblock_repeats_the_same_field(block, db):
    out = block(
        '{% wagtail_block "AccordionBlock" %}'
        '{% block_field "items" %}'
        '{% wagtail_block "AccordionItemBlock" title="One" / %}'
        "{% endblock_field %}"
        '{% block_field "items" %}'
        '{% wagtail_block "AccordionItemBlock" title="Two" / %}'
        "{% endblock_field %}"
        "{% endwagtail_block %}"
    )
    assert "One" in out and "Two" in out
    assert 'class="accordion"' in out


def test_a_citry_component_inside_a_block_field_body(block, component, db):
    """
    The body is part Citry, and the tag still finds its own nodes.

    `{% block_field %}` renders this body with `nodelist.render()`, so the
    adapter's node has to return real text at exactly that point.
    """
    component('<em class="badge">{{ text }}</em>', name="block-badge")
    out = block(
        '{% wagtail_block "AccordionItemBlock" %}'
        '{% block_field "title" %}<c-block-badge text="Cited"/>{% endblock_field %}'
        "{% endwagtail_block %}"
    )
    # `title` is a CharBlock, so Wagtail escapes what it is given. The markup
    # arriving escaped is the proof: the tag was handed the component's real
    # rendered text, not a stand-in and not the source.
    assert "Cited" in out
    assert "&lt;em" in out
    assert "<c-block-badge" not in out


def test_a_block_component_inside_a_citry_loop(block, db):
    # `title=i` is Django's own kwarg syntax, reading the loop variable Citry
    # bound. `c-title` would be Citry element syntax, which a Django tag has no
    # reason to understand.
    out = block(
        '<c-for each="i in items">{% wagtail_block "AccordionItemBlock" title=i / %}</c-for>',
        items=["Alpha", "Beta"],
    )
    assert "Alpha" in out and "Beta" in out
