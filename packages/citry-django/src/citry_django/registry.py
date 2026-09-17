from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .context import ContextBehavior


@cache
def citry_app_source() -> Any:
    """What ``CITRY_APP`` names: an engine, or a callable that picks one."""
    path = getattr(settings, "CITRY_APP", None)
    if not path:
        msg = (
            "settings.CITRY_APP is not set. Point it at your Citry instance, "
            'for example CITRY_APP = "myproject.citry_app:app".'
        )
        raise ImproperlyConfigured(msg)
    return import_object(path, "CITRY_APP")


def get_citry_app() -> Any:
    """
    Resolving the objects a project points the adapter at.

    Rendering a ``<c-*>`` region needs to know which engine to look components up
    in, and reading a template needs the tokenizer that engine's adapter was
    configured with. Point ``settings.CITRY_APP`` at your instance with a dotted
    path, optionally with a ``:attr`` suffix::

        CITRY_APP = "myproject.citry_app:app"

    It may name a callable instead, for a project that renders more than one engine
    and chooses between them per request::

        CITRY_APP = "myproject.citry_app:engine_for_request"

    The callable is resolved once and called on every lookup, so it has to be cheap:
    build the engines at startup and have it select one. A ``Citry`` instance is not
    callable, so the two forms tell themselves apart.

    The engine this render belongs to.

        Called once per ``<c-*>`` region and three more times per template, so the
        import stays behind ``citry_app_source``'s cache and only the selection
        runs each time.
    """
    source = citry_app_source()
    return source() if callable(source) else source


def get_tokenizer() -> Any:
    """
    The callable the project's adapter reads Django's syntax with.

    Every claim about where Django's syntax starts and stops goes through this,
    so it has to be the tokenizer that will actually compile the template.
    """
    return get_citry_app().extensions.get_extension("citry_django").tokenizer


def context_behavior() -> str:
    """How much of the host's context a component's own template may read."""
    extension = get_citry_app().extensions.get_extension("citry_django")
    return getattr(extension, "context_behavior", ContextBehavior.ISOLATED)


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


def deps_strategy() -> str:
    """How a region serializes what Citry collected for it.

    Citry's own setting, named the same way: `"document"` emits the tags and
    the client runtime, `"simple"` the tags alone, `"ignore"` nothing at all.
    A project sets `"ignore"` when something downstream collects the assets
    instead, and then a page loads without its component styles unless that
    something does its job.
    """
    return getattr(settings, "CITRY_DEPS_STRATEGY", "document")
