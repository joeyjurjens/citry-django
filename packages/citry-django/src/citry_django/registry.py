"""
Resolving the objects a project points the adapter at.

Rendering a ``<c-*>`` region needs to know which engine to look components up
in, and reading a template needs the tokenizer that engine's adapter was
configured with. Point ``settings.CITRY_APP`` at your instance with a dotted
path, optionally with a ``:attr`` suffix::

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
    return import_object(path, "CITRY_APP")


def get_tokenizer() -> Any:
    """
    The callable the project's adapter reads Django's syntax with.

    Every claim about where Django's syntax starts and stops goes through this,
    so it has to be the tokenizer that will actually compile the template.
    """
    return get_citry_app().extensions.get_extension("citry_django").tokenizer


def django_attrs_enabled() -> bool:
    """Whether the adapter may take Django syntax out of a ``c-`` attribute.

    Publishes the lookup those rewrites call, too. Not done when the extension
    is created: ``Citry(extensions=[...], template_globals={...})`` assigns the
    globals afterwards, which would drop it.
    """
    app = get_citry_app()
    extension = app.extensions.get_extension("citry_django")
    if not getattr(extension, "django_attrs", False):
        return False
    from .django_attrs import LOOKUP_GLOBAL, django_lookup

    app.template_globals.setdefault(LOOKUP_GLOBAL, django_lookup)
    return True


def import_object(path: str, setting: str) -> Any:
    module_path, _, attr = path.partition(":")
    if not attr:
        module_path, _, attr = path.rpartition(".")

    try:
        module = import_module(module_path)
    except ImportError as exc:
        msg = (
            f"settings.{setting} points at {path!r}, "
            f"but {module_path!r} could not be imported: {exc}"
        )
        raise ImproperlyConfigured(msg) from exc

    try:
        return getattr(module, attr)
    except AttributeError as exc:
        msg = (
            f"settings.{setting} points at {path!r}, but {module_path!r} has no attribute {attr!r}."
        )
        raise ImproperlyConfigured(msg) from exc
