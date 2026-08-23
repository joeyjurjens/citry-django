"""
Adversarial input, and the boundary between our bugs and Django's own limits.

Each case here was found by throwing awkward templates at the adapter rather
than by reasoning about it. Two were real bugs:

* ``{% comment %}`` was broken. Django implements it with ``skip_past()`` rather
  than ``parse()``, so the span recorder never saw it and the two halves were
  handed to Django as unrelated tags.
* ``{% verbatim %}`` leaked an internal marker, because its body looked like it
  contained Citry content. Django's *lexer* hardcodes verbatim and never
  interprets that body, so Citry must not either.
"""

import threading

import pytest

HANDLED = [
    pytest.param(
        '<div class="{% if a %}on{% endif %}">x</div>',
        {"a": True},
        "on",
        id="django-tag-in-an-attribute-value",
    ),
    pytest.param(
        "<p>write &lt;c-foo/&gt;</p>", {}, "&lt;c-foo/&gt;", id="escaped-c-element-in-prose"
    ),
    pytest.param("<p>{{ s }}</p>", {"s": "héllo 👋 中文"}, "👋", id="unicode-and-emoji"),
    pytest.param("<p>{{ {'a': 1}['a'] }}</p>", {}, ">1<", id="python-dict-subscript"),
    pytest.param(
        "{% if a %}" * 8 + "<b>x</b>" + "{% endif %}" * 8,
        {"a": True},
        "<b",
        id="deeply-nested-blocks",
    ),
    pytest.param(
        "{% comment %}hidden{% endcomment %}<p>shown</p>", {}, "shown", id="django-comment"
    ),
    pytest.param(
        "{% comment %}<c-nope/>{% endcomment %}<p>ok</p>",
        {},
        "ok",
        id="comment-wrapping-citry-syntax",
    ),
    pytest.param(
        "{% if a %}{% comment %}h{% endcomment %}<b>x</b>{% endif %}",
        {"a": True},
        "<b",
        id="comment-inside-a-block",
    ),
    pytest.param("{# citry #}<p>shown</p>", {}, "shown", id="citry-comment"),
    pytest.param("", {}, "", id="empty-template"),
    pytest.param("{% if a %}{% endif %}<p>x</p>", {"a": True}, "<p", id="block-with-empty-body"),
    pytest.param(
        "{% if a %}<b>1</b>{% endif %}{% if a %}<i>2</i>{% endif %}",
        {"a": True},
        "<i",
        id="adjacent-blocks",
    ),
    pytest.param(
        "<div>\r\n{% if a %}\r\n<b>x</b>\r\n{% endif %}\r\n</div>",
        {"a": True},
        "<b",
        id="crlf-line-endings",
    ),
    pytest.param(
        "{% load humanize %}<p>{{ n|intcomma }}</p>",
        {"n": 1234567},
        "1,234,567",
        id="third-party-filter",
    ),
    pytest.param(
        '<p>{{ n|stringformat:"04d" }}</p>', {"n": 3}, "0003", id="filter-argument-with-digits"
    ),
    pytest.param(
        '<script>var a={"k":1};</script>{% if a %}<b>x</b>{% endif %}',
        {"a": True},
        "<b",
        id="json-inside-a-script-tag",
    ),
    pytest.param(
        "<!-- {% if a %}x{% endif %} --><p>y</p>",
        {"a": True},
        "<p",
        id="django-tag-in-an-html-comment",
    ),
    pytest.param(
        "x" * 50_000 + "{% if a %}<b>e</b>{% endif %}", {"a": True}, "<b", id="50kb-text-run"
    ),
]

#: Templates Django itself rejects. We must fail too, not silently differ.
DJANGO_ALSO_REJECTS = [
    pytest.param(
        '{% load django_bootstrap5 %}{% bootstrap_button "a %} b" %}',
        {},
        id="percent-brace-inside-a-tag-string",
    ),
    pytest.param("{% if\n\ta %}<b>x</b>{% endif %}", {"a": 1}, id="newline-inside-a-tag"),
]


@pytest.mark.parametrize(("template", "context", "expected"), HANDLED)
def test_awkward_input_is_handled(render, template, context, expected):
    assert expected in render(template, **context)


@pytest.mark.parametrize("a", [True, False])
@pytest.mark.parametrize(
    "source",
    [
        pytest.param("{% if a %}<div>{% endif %}</div>", id="opens-inside-closes-outside"),
        pytest.param("<div>{% if a %}</div>{% endif %}", id="opens-outside-closes-inside"),
    ],
)
def test_a_block_and_an_element_may_interleave(render, render_vanilla, strip_cids, source, a):
    """
    A Django block and an HTML element need not nest inside one another.

    Neither engine sees the other's structure: Citry reads `<div>` and `</div>`
    as a well-formed pair because the claimed ranges between them are just text,
    and Django owns the `{% if %}`/`{% endif %}` pair separately. The two trees
    never have to agree, which is what makes an element boundary a non-issue.

    Compared against plain Django rather than an expected string: matching what
    Django does with degenerate markup is the whole requirement.
    """
    assert strip_cids(render(source, a=a)).strip() == render_vanilla(source, a=a).strip()


def test_a_block_inside_an_attribute_value(render):
    """
    The same freedom applies inside an attribute value, where an element could
    never have gone.

    Output is not compared against Django here, because the two legitimately
    differ when the branch is empty: Citry parses the HTML and normalises
    `class=""` away, where Django, doing plain text substitution, keeps it.
    That is Citry being Citry, and it is the same with no Django in sight.
    """
    source = '<div class="{% if a %}on{% endif %}">x</div>'
    assert 'class="on"' in render(source, a=True)
    assert "class" not in render(source, a=False)


def test_non_ascii_before_django_syntax_keeps_foreign_byte_offsets(render):
    source = 'Příliš 👋 <div class="{% if a %}on{% endif %}">x</div>'
    assert 'class="on"' in render(source, a=True)
    assert "class" not in render(source, a=False)


def test_non_ascii_before_citry_region_keeps_rewrite_byte_offsets(render_django):
    source = 'Příliš 👋 <c-if cond="show"><b>yes</b></c-if> konec'
    assert ">yes<" in render_django(source, show=True)
    assert "yes" not in render_django(source, show=False)


def test_non_ascii_inside_masked_django_token_keeps_rewrite_byte_offsets(render_django):
    source = '{% with label="Příliš 👋" %}<c-if cond="show"><b>yes</b></c-if>{% endwith %}'
    assert ">yes<" in render_django(source, show=True)


def test_verbatim_body_is_never_interpreted(render):
    out = render("{% verbatim %}{{ raw }}{% endverbatim %}<p>after</p>")
    assert "{{ raw }}" in out
    assert "citryseg" not in out, "an internal marker leaked into the page"


@pytest.mark.parametrize(("template", "context"), DJANGO_ALSO_REJECTS)
def test_we_fail_where_django_fails(render, render_vanilla, template, context):
    """Failing the same way as Django is correct; silently differing would not be."""
    with pytest.raises(Exception):  # noqa: B017
        render_vanilla(template, **context)
    with pytest.raises(Exception):  # noqa: B017
        render(template, **context)


def test_concurrent_renders_do_not_leak(citry_app, component):
    """Block state rides on Django's Context object, so threads cannot mix."""
    component('<b class="k">{{ m }}</b>', name="conckid")
    holder = component(
        "{% if a %}<c-conckid c-m='m'/>{% else %}<i>no</i>{% endif %}"
        "{% for x in xs %}<s>{{ x }}</s>{% endfor %}"
    )
    citry_app.initialize()

    bad = []

    def work(n):
        even = n % 2 == 0
        try:
            for _ in range(150):
                out = str(holder(a=even, m=f"m{n}", xs=[f"s{n}"]))
                ok = (f">m{n}</b>" in out) if even else (">no</i>" in out)
                ok = ok and f">s{n}</s>" in out
                ok = ok and not any(
                    f">m{o}</b>" in out or f">s{o}</s>" in out for o in range(8) if o != n
                )
                if not ok:
                    bad.append((n, out[:90]))
                    return
        except Exception as exc:
            bad.append((n, repr(exc)))

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not bad, f"cross-thread leakage: {bad[0]}"
