from __future__ import annotations

from collections.abc import Callable
from typing import Any

from citry.ext.dependencies import Script, Style
from django.templatetags.static import static


def styles(*paths: str | list[str] | tuple[str, ...], **attrs: str) -> list[Callable[[], Style]]:
    """
    Static files as Citry dependencies.

    Citry takes a dependency as a ``Style`` or ``Script`` holding a URL. A Django
    project spells the URL of a static file with ``static()``, which respects
    ``STATIC_URL`` and whatever storage the project configured, so these turn the
    paths a project already writes into the objects Citry wants::

        class Card(Component):
            class Dependencies:
                css = styles(["card/card.css"])
                js = scripts(["card/card.js"])

    A stylesheet a browser cannot read on its own - ``.scss``, ``.less`` - needs
    compiling first, which is django-compressor's job and lives with it: see
    ``citry_django_compressor.precompiled_styles``.

    Stylesheets for `paths`, each a static path or a list of them.

        Lists are accepted so a project can keep its paths in constants and hand
        several groups over at once: ``styles(Css.CARD, Css.GRID)``.

    Each path resolves lazily rather than where it is called: a
    ``Dependencies.css = styles([...])`` assignment sits in a component's
    class body, which runs at import time - the same moment ``manage.py``
    (any subcommand, ``collectstatic`` included) first loads the app.
    Resolving ``static()`` there requires the hashed manifest ``collectstatic``
    produces to already exist, which on a fresh ``STATIC_ROOT`` is exactly what
    has not happened yet - defining a component's assets should never be able
    to make `collectstatic` itself unable to run. Citry already invokes a
    callable ``Dependencies`` entry at render time instead of at declaration
    time (see ``citry.ext.dependencies``), so returning one callable per path
    defers the ``static()`` call to then, by which point a real deploy has
    already run ``collectstatic`` once.
    """
    return [_lazy(Style, path, attrs) for path in flatten(paths)]


def scripts(*paths: str | list[str] | tuple[str, ...], **attrs: str) -> list[Callable[[], Script]]:
    """Scripts for `paths`, each a static path or a list of them. Lazy for the
    same reason as `styles` - see its docstring."""
    return [_lazy(Script, path, attrs) for path in flatten(paths)]


def _lazy(build: type[Style] | type[Script], path: str, attrs: dict[str, str]):
    resolved_attrs = dict(attrs)
    return lambda: build(url=static(path), attrs=resolved_attrs)


def flatten(paths: tuple[Any, ...]) -> list[str]:
    """One list of paths from a mix of paths and groups of them."""
    out: list[str] = []
    for path in paths:
        if isinstance(path, str):
            out.append(path)
        else:
            out.extend(path)
    return out
