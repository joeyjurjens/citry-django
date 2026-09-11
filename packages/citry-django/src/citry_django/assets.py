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
"""

from __future__ import annotations

from typing import Any

from citry.ext.dependencies import Script, Style
from django.templatetags.static import static


def styles(*paths: str | list[str] | tuple[str, ...], **attrs: str) -> list[Style]:
    """Stylesheets for `paths`, each a static path or a list of them.

    Lists are accepted so a project can keep its paths in constants and hand
    several groups over at once: ``styles(Css.CARD, Css.GRID)``.
    """
    return [Style(url=static(path), attrs=dict(attrs)) for path in flatten(paths)]


def scripts(*paths: str | list[str] | tuple[str, ...], **attrs: str) -> list[Script]:
    """Scripts for `paths`, each a static path or a list of them."""
    return [Script(url=static(path), attrs=dict(attrs)) for path in flatten(paths)]


def flatten(paths: tuple[Any, ...]) -> list[str]:
    """One list of paths from a mix of paths and groups of them."""
    out: list[str] = []
    for path in paths:
        if isinstance(path, str):
            out.append(path)
        else:
            out.extend(path)
    return out
