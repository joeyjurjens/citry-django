import re

import pytest

#: Django constructs that must not change what Citry emits inside them.
#:
#: A tag that wraps its body in markup of its own is deliberately absent: it
#: moves the component *root element*, so the identity markers legitimately land
#: somewhere else. That is correct behaviour, not a leak.
TRANSPARENT = [
    pytest.param("{% if yes %}", "{% endif %}", id="if"),
    pytest.param("{% if no %}skip{% else %}", "{% endif %}", id="if-else"),
    pytest.param('{% with q="v" %}', "{% endwith %}", id="with"),
    pytest.param("{% for _ in one %}", "{% endfor %}", id="for"),
    pytest.param("{% spaceless %}", "{% endspaceless %}", id="spaceless"),
]

#: Citry payloads exercising the things that live in the render tree.
PAYLOADS = [
    pytest.param("<i>x</i>", id="plain-element"),
    pytest.param('<c-leaf m="x"/>', id="component"),
    pytest.param("<c-mid/>", id="nested-components"),
    pytest.param("<c-slotted>body</c-slotted>", id="component-with-slot"),
    pytest.param('<c-for each="i in two"><c-leaf c-m="i"/></c-for>', id="component-in-a-loop"),
    pytest.param('<c-if cond="yes"><c-leaf m="c"/></c-if>', id="component-behind-c-if"),
    pytest.param("<c-css/><c-leaf m='s'/>", id="css-dependency"),
]

CONTEXT = {"yes": True, "no": False, "one": [1], "two": ["a", "b"]}

CID = re.compile(r"data-cid-[a-z0-9]+")


@pytest.fixture(autouse=True)
def fixtures(component):
    component('<b class="leaf">{{ m }}</b>', name="leaf", css=".leaf{color:red}")
    component('<span class="inner"><c-leaf m="deep"/></span>', name="mid")
    component('<div class="slotted"><c-slot/></div>', name="slotted")


def normalize(html):
    """
    Replace generated component ids with their order of appearance.

    Ids are generated per render, so the test is about how many identity markers
    there are and where they sit, not what they are called.
    """
    seen = {}
    return CID.sub(lambda m: f"data-cid-{seen.setdefault(m.group(0), len(seen))}", html).strip()


@pytest.mark.parametrize("payload", PAYLOADS)
@pytest.mark.parametrize(("opening", "closing"), TRANSPARENT)
def test_a_transparent_block_does_not_change_citrys_output(render, payload, opening, closing):
    standalone = normalize(render(payload, **CONTEXT))
    wrapped = normalize(render(f"{opening}{payload}{closing}", **CONTEXT))
    assert wrapped == standalone
