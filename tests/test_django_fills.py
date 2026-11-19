"""Django content inside an interactive component, such as the fill of a modal.

Inside a Vue app, Citry writes what Django renders as finished blocks of HTML
that Vue inserts and never compiles. HTML it cannot write that way raises
`IslandContentError`, which says what to change in the Django template.
"""

from __future__ import annotations

from typing import Any

import pytest
from citry import Component

from citry_django.content import IslandContentError
from citry_django.registry import citry_app_source
from events_site.app import app


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


app.register(Picture, "fill-picture")
app.register(Linked, "fill-linked")


@pytest.fixture(autouse=True)
def events_site(settings):
    settings.CITRY_APP = "events_site.app:app"
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


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
    ],
)
def test_a_refusal_says_how_to_change_the_django_template(render_django, source, context, says):
    with pytest.raises(IslandContentError) as caught:
        render_django(source, **context)

    assert says in str(caught.value)
    # Citry's own message, with the HTML it refused, stays attached.
    assert caught.value.__cause__ is not None
    assert isinstance(caught.value, ValueError)
