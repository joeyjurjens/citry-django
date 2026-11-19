"""A component that a server event re-renders gets what a region gets on the page."""

from __future__ import annotations

import json
import re

import pytest
from citry.ext.events import EventRequest
from citry.ext.events.tokens import mint_state_token
from django.test import Client
from django.utils import translation

from citry_django import render_inputs
from citry_django.registry import citry_app_source
from events_site.app import Counter, app

pytestmark = pytest.mark.urls("events_site.urls")


@pytest.fixture(autouse=True)
def events_site(settings):
    settings.CITRY_APP = "events_site.app:app"
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


def bump(client: Client, **headers) -> dict:
    """Post one `bump` call for `Counter`, as the browser runtime would."""
    call = {
        "componentClassId": Counter.class_id,
        "handlerName": "bump",
        "callerRenderId": "inputs_i1",
        "args": {},
        "stateToken": mint_state_token(
            Counter.State(),
            class_id=Counter.class_id,
            secret=app.settings.secret,
            max_age=None,
            max_bytes=8192,
        ),
    }
    body = json.dumps({"protocol": "citry-events/1", "requestId": "r1", "calls": [call]})
    response = client.post(
        f"/citry/ext/events/e/{Counter.class_id}/bump",
        data=body,
        content_type="application/citry-events+json",
        headers={"X-Citry-Events": "1", **headers},
    )
    assert response.status_code == 200, response.content
    return json.loads(response.content)["results"][0]


def rendered_text(html: str) -> list[str]:
    """The text values a Vue re-render carries for its template, in order.

    Without the browser runtime's headers, Citry answers with a fresh island
    whose content is data for Vue to render, so the values are read there.
    """
    found: list[str] = []

    def walk(value):
        if isinstance(value, dict):
            prepared = value.get("preparedData")
            if isinstance(prepared, dict):
                found.extend(v for k, v in prepared.items() if k != "calls")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for match in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.S):
        walk(json.loads(match.group(1)))
    return found


@pytest.mark.django_db
def test_a_re_render_reads_request_context_processors_and_locale(settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, "django.middleware.locale.LocaleMiddleware"]
    # LocaleMiddleware activates the language for this thread; the override
    # puts the previous one back for the tests that follow.
    with translation.override(settings.LANGUAGE_CODE):
        result = bump(Client(), **{"Accept-Language": "de"})

    [action] = result["actions"]
    assert action["action"] == "render"
    # Label, count, locale, request.path, user.is_authenticated, and whether
    # a context processor's value reached inject("django").
    assert rendered_text(action["html"]) == [
        "bumped",
        "1",
        "de",
        f"/citry/ext/events/e/{Counter.class_id}/bump",
        "False",
        "True",
    ]


@pytest.mark.django_db
def test_the_locale_is_djangos_active_language(rf):
    request = rf.get("/")
    with translation.override("de"):
        inputs = render_inputs(EventRequest(native=request))

    assert inputs["provides"]["citry_i18n"].locale == "de"
    assert inputs["template_globals"]["request"] is request


def test_only_request_and_context_processors_are_given(rf):
    request = rf.get("/")
    inputs = render_inputs(EventRequest(native=request))

    assert set(inputs) == {"template_globals", "provides"}
    assert set(inputs["provides"]) == {"django", "citry_i18n"}
    processors = set(inputs["provides"]["django"])
    assert set(inputs["template_globals"]) == processors | {"request"}


def test_a_request_that_is_not_djangos_gets_no_request_values():
    inputs = render_inputs(EventRequest(native=object()))

    assert inputs["template_globals"] == {}
    assert inputs["provides"]["django"] == {}
