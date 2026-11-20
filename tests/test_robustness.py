import threading

import pytest
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from django.template import engines
from django.utils.safestring import mark_safe
from django_components import Component as DjcComponent
from django_components import registry as djc_registry

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

#: Templates at the edge of Django's own lexer, where the adapter must land on
#: the same side as Django rather than deciding for itself.
MATCHES_DJANGO = [
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


@pytest.mark.parametrize(("template", "context"), MATCHES_DJANGO)
def test_the_edges_of_djangos_lexer_are_djangos_to_decide(
    render, render_vanilla, strip_cids, template, context
):
    """
    Accept exactly what Django accepts, and reject exactly what it rejects.

    Which of the two happens is not the assertion. Something in the template
    stack may move that line -- a replaced tokenizer reads a `%}` inside a
    quoted argument where Django's own lexer does not -- and the adapter has to
    move with it, because deciding for itself is how the two engines drift
    apart.
    """
    try:
        expected = render_vanilla(template, **context)
    except Exception as exc:
        with pytest.raises(type(exc)):
            render(template, **context)
    else:
        assert strip_cids(render(template, **context)).strip() == expected.strip()


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


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("<!--CiTrY-SeGmEnT:0:0-->", id="short"),
        pytest.param("<!--CiTrY-SeGmEnT:0123456789abcdef0123456789abcdef:3-->", id="full-length"),
    ],
)
def test_text_shaped_like_an_internal_comment_is_shown_as_text(
    render, render_vanilla, strip_cids, text
):
    """Data that Django escapes inside a block is only text, whatever it spells.

    Citry hands Django a comment for each run of Citry content and reads it back
    after the block renders. A value that happens to spell such a comment
    reaches the block escaped, so it is the value's text and the page shows it,
    as plain Django does.
    """
    source = '{% for c in cs %}<p>{{ c|default:"" }}</p>{% endfor %}'
    html = strip_cids(render(source, cs=["ok", text]))
    assert render_vanilla(source, cs=["ok", text]).strip() == html.strip()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("{% if 1 %}<p>{{ n }}</p>{% endif %}", id="bare-name"),
        pytest.param("{% if 1 %}<p>{{ n|default:'' }}</p>{% endif %}", id="with-a-filter"),
        pytest.param("{% for x in xs %}<p>{{ x }}</p>{% endfor %}", id="loop-variable"),
        pytest.param(
            "{% load i18n %}{% if 1 %}<p>{% translate n %}</p>{% endif %}", id="translate"
        ),
        pytest.param("{% if 1 %}{% include 'esc/value.html' %}{% endif %}", id="include-name"),
        pytest.param("{% if 1 %}{% include tpl %}{% endif %}", id="include-variable"),
        pytest.param(
            "{% if 1 %}{% include 'esc/value.html' with n=n only %}{% endif %}",
            id="include-with",
        ),
        pytest.param(
            "{% load esc_tags %}{% if 1 %}<p>{% echo n %}</p>{% endif %}", id="simple-tag"
        ),
        pytest.param(
            "{% load esc_tags %}{% if 1 %}{% bold n %}{% endif %}", id="simple-tag-format-html"
        ),
        pytest.param("{% load esc_tags %}{% if 1 %}{% shown n %}{% endif %}", id="inclusion-tag"),
        pytest.param(
            "{% load esc_tags %}{% if 1 %}{% boxed n %}<p>x</p>{% endboxed %}{% endif %}",
            id="simple-block-tag",
        ),
        pytest.param("{% if 1 %}{% firstof n as v %}<p>{{ v }}</p>{% endif %}", id="firstof-as"),
        pytest.param(
            "{% load i18n %}{% if 1 %}{% translate n as v %}<p>{{ v }}</p>{% endif %}",
            id="translate-as",
        ),
        pytest.param(
            "{% load i18n %}{% if 1 %}{% blocktranslate asvar v %}{{ n }}"
            "{% endblocktranslate %}<p>{{ v }}</p>{% endif %}",
            id="blocktranslate-asvar",
        ),
        pytest.param(
            "{% load esc_tags %}{% if 1 %}{% bold n as v %}{{ v }}{% endif %}",
            id="simple-tag-as",
        ),
        pytest.param("{% with v=n|escape %}<p>{{ v }}</p>{% endwith %}", id="escaped-in-with"),
        pytest.param("{% if 1 %}<p>{{ n|force_escape }}</p>{% endif %}", id="escaping-filter"),
        pytest.param("{% if 1 %}{{ n|linebreaks }}{% endif %}", id="html-writing-filter"),
        pytest.param("{% if 1 %}<p>{% firstof n %}</p>{% endif %}", id="firstof"),
        pytest.param("{% for x in xs %}<p>{% cycle n n %}</p>{% endfor %}", id="cycle"),
        pytest.param(
            "{% load i18n %}{% if 1 %}<p>{% blocktranslate %}{{ n }}{% endblocktranslate %}</p>"
            "{% endif %}",
            id="blocktranslate",
        ),
    ],
)
def test_escape_control_character_in_a_django_block_is_written_as_a_reference(render, source):
    """ESC in a value Django writes inside a block reaches the page as `&#27;`, like Citry."""
    tpl = engines["citry"].from_string("<b>{{ n }}</b>").template
    html = render(source, n="\x1b$B", xs=["\x1b$B"], tpl=tpl)
    assert "\x1b" not in html
    assert "&#27;$B" in html


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("{% if 1 %}<p>{{ m }}</p>{% endif %}", id="safe-value"),
        pytest.param("{% if 1 %}<p>{{ n|safe }}</p>{% endif %}", id="safe-filter"),
        pytest.param(
            "{% autoescape off %}{% if 1 %}<p>{{ n }}</p>{% endif %}{% endautoescape %}",
            id="autoescape-off",
        ),
        pytest.param(
            "{% autoescape off %}{% load esc_tags %}{% if 1 %}{% echo n %}{% endif %}"
            "{% endautoescape %}",
            id="tag-with-autoescape-off",
        ),
        pytest.param("{% with v=n|safe %}<p>{{ v }}</p>{% endwith %}", id="safe-in-with"),
        pytest.param(
            "{% load esc_tags %}{% if 1 %}{% for x in xs %}<p>{{ m }}</p>{% endfor %}{% endif %}",
            id="safe-value-in-nested-blocks",
        ),
    ],
)
def test_escape_control_character_in_trusted_html_is_left_as_written(render, source):
    """HTML the author marked as such, which Citry also leaves as written."""
    html = render(source, n="\x1b$B", m=mark_safe("\x1b$B"), xs=[1])
    assert "\x1b$B" in html


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('<c-esclabel label="{{ n|upper }}" />', id="filtered"),
        pytest.param('<c-esclabel label="x {{ n }}" />', id="with-text"),
        pytest.param('<c-esclabel label="{% if 1 %}{{ n }}{% endif %}" />', id="with-a-tag"),
        pytest.param('{% if 1 %}<c-esclabel label="{{ n|lower }}" />{% endif %}', id="in-a-block"),
    ],
)
def test_escape_control_character_in_a_django_component_input_is_written_as_a_reference(
    render, component, source
):
    """A component input written with Django syntax reaches the child as HTML, escaped first."""
    component("<p>{{ label }}</p>", name="esclabel")
    html = render(source, n="\x1b$B")
    assert "\x1b" not in html
    assert "&#27;$" in html


def test_a_safe_value_in_a_django_component_input_is_left_as_written(render, component):
    """`|safe` in a component input is the author's HTML, as in a Django block."""
    component("<p>{{ label }}</p>", name="esclabel")
    html = render('<c-esclabel label="x {{ n|safe }}" />', n="\x1b$B")
    assert "x \x1b$B" in html


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "{% if 1 %}{{ n|json_script:'d' }}{% endif %}", '"\\u001b$B"', id="json_script"
        ),
        pytest.param("{% if 1 %}<p>{{ n|escapejs }}</p>{% endif %}", "\\u001B$B", id="escapejs"),
        pytest.param(
            "{% if 1 %}<p>{{ k }}</p>{% endif %}", "&amp;#27;", id="text-spelling-the-reference"
        ),
        pytest.param(
            "{% if 1 %}<p>{{ n|escape|escape }}</p>{% endif %}", ">&#27;$B<", id="escaped-twice"
        ),
        pytest.param(
            "{% load esc_tags %}{% if 1 %}{% echo k %}{% endif %}", "&amp;#27;", id="tag-text"
        ),
        pytest.param(
            "{% filter force_escape %}{{ n }}{% endfilter %}",
            "&amp;#27;$B",
            id="filter-force-escape",
        ),
    ],
)
def test_escape_control_character_is_written_once(render, source, expected):
    """Each value is escaped once, and JSON and JavaScript escaping are unchanged."""
    html = render(source, n="\x1b$B", k="&#27;")
    assert "\x1b" not in html
    assert expected in html


def test_escape_control_character_in_an_extended_template_is_written_as_a_reference(render):
    """`{% extends %}` writes a parent template Django compiled, like `{% include %}`."""
    base = engines["citry"].from_string("<b>{{ n }}</b>{% block x %}{% endblock %}").template
    html = render(
        "{% extends base %}{% block x %}<u>{{ block.super }}</u>{% endblock %}",
        base=base,
        n="\x1b$B",
    )
    assert "\x1b" not in html
    assert "&#27;$B" in html


def test_escape_control_character_in_a_cached_fragment_is_written_as_a_reference(render):
    """A `{% cache %}` fragment stored by another render is written as escaped values."""
    cache.clear()
    cache.set(make_template_fragment_key("escfrag"), "<p>\x1b$B</p>")
    try:
        html = render(
            "{% load esc_tags %}{% if 1 %}{% django_cache 60 escfrag %}<p>{{ n }}</p>"
            "{% endcache %}{% endif %}",
            n="other",
        )
    finally:
        cache.clear()
    assert "\x1b" not in html
    assert "&#27;$B" in html


@pytest.fixture
def esc_button():
    class EscButton(DjcComponent):
        template = "<button>{{ label }}</button>{% slot 'extra' default %}{% endslot %}"

        def get_template_data(self, args, kwargs, slots, context):
            return {"label": kwargs["label"]}

    djc_registry.register("esc_button", EscButton)
    yield
    djc_registry.unregister("esc_button")


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "{% if 1 %}{% component 'esc_button' label=n %}{% endcomponent %}{% endif %}",
            id="component",
        ),
        pytest.param(
            "{% if 1 %}{% component 'esc_button' label='x' %}"
            "{% fill 'extra' %}<i>{{ n }}</i>{% endfill %}{% endcomponent %}{% endif %}",
            id="component-with-a-fill",
        ),
        pytest.param("{% if 1 %}<p {% html_attrs title=n %}>x</p>{% endif %}", id="html-attrs"),
    ],
)
def test_django_components_tags_in_a_django_block_write_escape_as_a_reference(
    render, esc_button, source
):
    """django-components tags still render inside a block, and their ESC is written as `&#27;`."""
    html = render(source, n="\x1b$B")
    assert "\x1b" not in html
    assert "&#27;$B" in html


def test_a_django_tag_still_receives_the_value_with_its_escape_character(render):
    """Only the written output changes: a tag argument is the value itself."""
    html = render("{% if n == e %}<p>same</p>{% endif %}", n="\x1b$B", e="\x1b$B")
    assert "same" in html
