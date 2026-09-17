from __future__ import annotations

import itertools
import re
from typing import Any

import pytest
from citry import Component
from django.template import engines
from django.test import RequestFactory
from testproject.citry_app import app

names = itertools.count()

#: Registered components, keyed by name and definition. Citry rejects binding
#: one name to two classes, so a component a test registers is reused when the
#: next test asks for exactly the same thing -- and still rejected when it asks
#: for something different under a name already taken.
REGISTERED: dict[tuple[str, str], type[Component]] = {}

CID = re.compile(r'\s*data-cid-[a-z0-9]+=""')


@pytest.fixture(scope="session")
def citry_app():
    """The project's Citry instance."""
    return app


@pytest.fixture
def component():
    """
    Define a component against the project's engine.

    ``name`` registers it so other templates can reach it as ``<c-name/>``;
    without one the class is returned for direct instantiation.
    """

    def make(template: str, name: str | None = None, **attrs: Any) -> type[Component]:
        key = (name, template)
        if name and key in REGISTERED:
            return REGISTERED[key]
        cls = type(
            f"T{next(names)}",
            (Component,),
            {"citry": app, "template": template, **attrs},
        )
        if name:
            app.register(cls, name)
            REGISTERED[key] = cls
        return cls

    return make


@pytest.fixture
def render(component):
    """Render a Citry component template, optionally with a real request."""

    def render_source(template: str, *, request=None, **context: Any) -> str:
        cls = component(template)
        if request is not None:
            return str(cls(**context).render(template_globals={"request": request}))
        return str(cls(**context))

    return render_source


@pytest.fixture
def render_django():
    """Render a source string through the project's Citry-aware Django engine."""

    def render_source(source: str, *, request=None, **context: Any) -> str:
        return engines["citry"].from_string(source).render(context, request)

    return render_source


@pytest.fixture
def render_vanilla():
    """Render a source string through a stock Django engine, for comparison."""

    def render_source(source: str, **context: Any) -> str:
        return engines["vanilla"].from_string(source).render(context)

    return render_source


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def strip_cids():
    """Drop Citry's identity markers, which plain Django has no reason to emit."""
    return lambda html: CID.sub("", html)


@pytest.fixture
def site(db):
    """A seeded Wagtail site: pages in the tree, and a real image to render."""
    from testproject.seed import seed

    return seed()
