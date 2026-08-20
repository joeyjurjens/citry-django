"""
Shared fixtures.

Everything renders against the project in ``testproject/``, so a test exercises
the same wiring a real site has: Wagtail, an asset pipeline, third-party tag
libraries, and the Citry app in ``testproject/citry_app.py``.

Components defined inside a test get a generated class name and are registered
under a name the test chooses, so tests stay independent of each other while
still sharing one engine.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

import pytest
from citry import Component
from django.template import engines
from django.test import RequestFactory
from testproject.citry_app import app

_names = itertools.count()

#: Registered components, keyed by name and definition. Citry rejects binding
#: one name to two classes, so a component a test registers is reused when the
#: next test asks for exactly the same thing -- and still rejected when it asks
#: for something different under a name already taken.
_registered: dict[tuple[str, str], type[Component]] = {}

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
        if name and key in _registered:
            return _registered[key]
        cls = type(
            f"T{next(_names)}",
            (Component,),
            {"citry": app, "template": template, **attrs},
        )
        if name:
            app.register(cls, name)
            _registered[key] = cls
        return cls

    return make


@pytest.fixture
def render(component):
    """Render a Citry component template, optionally with a real request."""

    def _render(template: str, *, request=None, **context: Any) -> str:
        cls = component(template)
        if request is not None:
            return str(cls(**context).render(template_globals={"request": request}))
        return str(cls(**context))

    return _render


@pytest.fixture
def render_django():
    """Render a source string through the project's Citry-aware Django engine."""

    def _render(source: str, *, request=None, **context: Any) -> str:
        return engines["citry"].from_string(source).render(context, request)

    return _render


@pytest.fixture
def render_vanilla():
    """Render a source string through a stock Django engine, for comparison."""

    def _render(source: str, **context: Any) -> str:
        return engines["vanilla"].from_string(source).render(context)

    return _render


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
