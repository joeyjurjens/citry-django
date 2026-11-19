"""Django content inside an interactive component, such as the fill of a modal.

Inside a Vue app, Citry writes what Django renders as finished blocks of HTML
that Vue inserts and never compiles, on the page and when a server event
renders the component again. HTML it cannot write that way raises
`IslandContentError`, which says what to change in the Django template.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from citry import Component
from django.test import Client

from citry_django.content import IslandContentError
from citry_django.registry import citry_app_source
from events_site.app import app
from islands import islands, runtime_scripts

pytestmark = pytest.mark.urls("events_site.urls")


class Picture(Component):
    """An interactive component whose slot sits inside an `<svg>`."""

    citry = app

    def js_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        return {"size": 1}

    template = """
        <svg class="picture"><c-slot /></svg>
    """


class Linked(Component):
    """An interactive component whose own template mixes Vue and Django syntax."""

    citry = app

    def js_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        return {"label": "now"}

    template = """
        <a :title="label">{% now "Y" %}</a>
    """


class Linky(Component):
    """An interactive component whose own template has a Django tag and no Vue syntax."""

    citry = app

    def js_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        return {"ready": True}

    template = """
        <a class="linky" href="{% url 'page' %}">page</a>
    """


class Tick(Component):
    """A small interactive component."""

    citry = app

    class Kwargs:
        label: str = ""

    def js_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        return {"label": kwargs.label}

    def template_data(self, kwargs: Any, slots: Any) -> dict[str, Any]:
        return {"label": kwargs.label}

    template = """
        <button class="tick">{{ label }}: 0</button>
    """


class Still(Component):
    """A component without Vue, with a Django tag and its own CSS."""

    citry = app
    css = ".fill-still{color:green}"
    template = """
        <i class="fill-still">{% if True %}still{% endif %}</i>
    """


app.register(Picture, "fill-picture")
app.register(Linked, "fill-linked")
app.register(Linky, "fill-linky")
app.register(Still, "fill-still")
app.register(Tick, "fill-tick")


@pytest.fixture(autouse=True)
def events_site(settings):
    settings.CITRY_APP = "events_site.app:app"
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


# --- What works ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "count", "shown"),
    [
        pytest.param("<p>host</p><c-modal title='t'>hello</c-modal>", 1, "hello", id="plain-fill"),
        pytest.param(
            "{% load i18n %}<c-modal title='t'>{% translate 'Hello' %}</c-modal>",
            1,
            "Hello",
            id="value-tag-in-fill",
        ),
        pytest.param(
            "<c-modal title='t'>{% if True %}<b>yes</b>{% endif %}</c-modal>",
            1,
            "<b>yes</b>",
            id="if-in-fill",
        ),
        pytest.param(
            "<c-modal title='t'><ul>{% for x in xs %}<li>{{ x }}</li>{% endfor %}</ul></c-modal>",
            1,
            "<li>b</li>",
            id="for-in-fill",
        ),
        pytest.param(
            "<ul>{% for x in xs %}<li><c-modal c-title='x'>a</c-modal></li>{% endfor %}</ul>",
            2,
            "<h2>b</h2>",
            id="for-around-the-region",
        ),
        pytest.param("<c-fill-linky/>", 1, 'href="/page/"', id="url-tag-in-own-template"),
        pytest.param(
            "<c-modal title='t'>{% if True %}<c-fill-still/>{% endif %}</c-modal>",
            1,
            "still",
            id="static-component-in-fill",
        ),
        pytest.param(
            "<c-modal title='t'>{% if True %}<b>x</b>{% endif %}"
            "<c-fill-tick label='in'/></c-modal>",
            1,
            "in: 0",
            id="interactive-component-beside-django-html",
        ),
        pytest.param(
            "<c-modal title='t'>{% if True %}<c-fill-tick label='in'/>{% endif %}</c-modal>",
            1,
            "in: 0",
            id="interactive-component-in-a-django-block",
        ),
    ],
)
def test_django_content_in_an_interactive_component(render_django, source, count, shown):
    html = render_django(source, xs=["a", "b"])
    found = islands(html)

    assert len(found) == len(found.configs) == count
    assert runtime_scripts(html) == 1
    assert shown in html


def test_an_interactive_component_inside_a_fill_joins_the_app_around_it(render_django):
    """A second Vue app inside the first would not mount, so there is one."""
    html = render_django(
        "<c-modal title='t'>{% if True %}<c-fill-tick label='in'/>{% endif %}</c-modal>"
    )
    [host] = islands(html).hosts

    assert html.index(f'id="citry-vue-{host}"') < html.index("in: 0")


def test_a_static_component_in_a_fill_loads_its_css_with_the_app(render_django):
    """Its CSS joins the island's one stylesheet, served from Citry's routes."""
    html = render_django(
        "<head><c-css/></head><body>"
        "<c-modal title='t'>{% if True %}<c-fill-still/><c-fill-still/>{% endif %}</c-modal>"
        "</body>"
    )
    head = html.split("</head>")[0]

    assert html.count('class="fill-still"') == 2
    assert head.count('rel="stylesheet"') == 1
    assert ".fill-still" not in html


def test_vue_syntax_that_django_writes_stays_data(render_django):
    """Django escaped the visitor's text, and Vue never compiles it: Citry
    hands it to the browser as data, never as part of the template."""
    note = "{{ 1 + 1 }} <b v-html='x' @click='y'>z</b>"
    html = render_django(
        "<c-modal title='t'>{% if True %}<p>{{ note }}</p>{% endif %}</c-modal>", note=note
    )
    [configuration] = islands(html).configs

    assert "{{ 1 + 1 }} &lt;b v-html=&#x27;x&#x27;" in html
    holders = list(paths_holding(configuration, "1 + 1"))
    assert holders
    assert all("opaqueHtml" in path for path in holders)


def paths_holding(value: Any, text: str, path: tuple = ()) -> Any:
    """The key paths in `value` whose string holds `text`."""
    if isinstance(value, str):
        if text in value:
            yield path
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from paths_holding(item, text, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from paths_holding(item, text, (*path, index))


# --- A server event renders the component again ---------------------------------


@pytest.mark.django_db
def test_a_server_event_renders_django_tags_in_a_fill_again():
    """The panel's handler returns the panel, so Citry renders it again,
    with Help and the Django tags in the modal Help fills."""
    client = Client()
    page = client.get("/fills/")
    assert page.status_code == 200
    configuration = panel_configuration(page.content.decode())
    manifest = configuration["manifest"]
    owner = next(
        item
        for item in manifest["occurrences"]
        if item.get("eventContext", {}).get("componentClassId", "").startswith("Panel_")
    )
    context = owner["eventContext"]
    call = {
        "componentClassId": context["componentClassId"],
        "handlerName": "bump",
        "args": {},
        "callerRenderId": context["serverRenderId"],
        "stateToken": context["stateToken"],
        "sendSequence": 1,
    }
    envelope = {
        "protocol": "citry-events/1",
        "requestId": "r1",
        "calls": [call],
        "capabilities": {
            "actions": ["render"],
            "swaps": ["morph"],
            "renderers": ["vue-prepared/1"],
        },
    }
    response = client.post(
        configuration["endpoint"],
        data=json.dumps(envelope),
        content_type="application/citry-events+json",
        headers={
            "X-Citry-Events": "1",
            "X-Citry-Vue-App": manifest["appId"],
            "X-Citry-Vue-Occurrence": owner["id"],
            "X-Citry-Vue-Revision": "0",
        },
    )

    assert response.status_code == 200, response.content
    [result] = json.loads(response.content)["results"]
    [action] = result["actions"]
    assert action["renderer"] == "vue-prepared/1"
    blocks = [
        record["html"]
        for occurrence in action["prepared"]["occurrences"]
        for record in occurrence["preparedData"].get("opaqueHtml", {}).values()
    ]
    # The fill Help wrote, rendered by Django again for this request.
    assert any('<span class="guide">Read the guide</span>' in block for block in blocks)
    # `request` is the server event's own request, which render_inputs gives.
    assert any('<i class="path">/citry/ext/events/' in block for block in blocks)


def panel_configuration(html: str) -> dict:
    """The configuration of the island that holds the panel."""
    for match in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.S):
        configuration = json.loads(match.group(1))
        if "Panel_" in match.group(1):
            return configuration
    raise AssertionError(html)


# --- What Citry refuses -------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "context", "says"),
    [
        pytest.param(
            "<c-modal title='t'>{{ opened|safe }}</c-modal>",
            {"opened": "<div>left open"},
            "wrote HTML that is not complete",
            id="unbalanced",
        ),
        pytest.param(
            "<c-modal title='t'>{% if True %}<script>run()</script>{% endif %}</c-modal>",
            {},
            "Move the script into the component's js",
            id="script",
        ),
        pytest.param(
            "<c-modal title='t'>{% if True %}<noscript>x</noscript>{% endif %}</c-modal>",
            {},
            "Move the <noscript> onto the page",
            id="noscript",
        ),
        pytest.param(
            "<c-fill-picture>{% if True %}<circle r='1'></circle>{% endif %}</c-fill-picture>",
            {},
            "inside <svg>, <math>",
            id="svg",
        ),
        pytest.param(
            "<c-fill-linked/>",
            {},
            "Linked uses Vue syntax (':title' on <a>)",
            id="vue-syntax-beside-django-tags",
        ),
        pytest.param(
            "<c-modal title='t'><div>{% if True %}<c-fill-tick label='in'/>{% endif %}</div>"
            "</c-modal>",
            {},
            # Citry names the component only when it is not wrapped in a run
            # of Citry content, as a Django block wraps it here.
            "Something that needs Vue sits inside an HTML element",
            id="interactive-component-inside-a-django-element",
        ),
    ],
)
def test_a_refusal_says_how_to_change_the_django_template(render_django, source, context, says):
    with pytest.raises(IslandContentError) as caught:
        render_django(source, **context)

    assert says in str(caught.value)
    # Citry's own message, with the HTML it refused, stays attached.
    assert caught.value.__cause__ is not None
    assert isinstance(caught.value, ValueError)
