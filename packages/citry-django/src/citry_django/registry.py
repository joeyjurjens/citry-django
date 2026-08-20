"""
Locating the project's ``Citry`` instance from Django.

Rendering a ``<c-*>`` region needs to know which engine to look components up
in.
Point ``settings.CITRY_APP`` at it with a dotted path, optionally with a
``:attr`` suffix::

    CITRY_APP = "myproject.citry_app:app"
"""

from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@cache
def get_citry_app() -> Any:
    path = getattr(settings, "CITRY_APP", None)
    if not path:
        msg = (
            "settings.CITRY_APP is not set. Point it at your Citry instance, "
            'for example CITRY_APP = "myproject.citry_app:app".'
        )
        raise ImproperlyConfigured(msg)

    module_path, _, attr = path.partition(":")
    if not attr:
        module_path, _, attr = path.rpartition(".")

    try:
        module = import_module(module_path)
    except ImportError as exc:
        msg = (
            f"settings.CITRY_APP points at {path!r}, "
            f"but {module_path!r} could not be imported: {exc}"
        )
        raise ImproperlyConfigured(msg) from exc

    try:
        return getattr(module, attr)
    except AttributeError as exc:
        msg = (
            f"settings.CITRY_APP points at {path!r}, but {module_path!r} has no attribute {attr!r}."
        )
        raise ImproperlyConfigured(msg) from exc
