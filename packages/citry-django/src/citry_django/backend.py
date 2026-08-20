"""
A Django template backend that understands Citry element syntax.

Swap ``BACKEND`` in ``settings.TEMPLATES`` and ``<c-hero/>`` works in every
Django template::

    TEMPLATES = [{
        "BACKEND": "citry_django.backend.CitryTemplates",
        "DIRS": [...],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [...]},
    }]

This is still Django's own engine -- same lexer, same tags, same inheritance.
The only difference is that the source is rewritten as it is loaded, so a
``<c-component/>`` becomes a tag Django can compile. Nothing else changes, and
templates with no Citry syntax in them are passed through untouched.
"""

from __future__ import annotations

from django.template.backends.django import DjangoTemplates

from .rewrite import rewrite_source

# Django's own defaults, with the rewriting loaders substituted in.
_FILESYSTEM = "citry_django.loaders.FilesystemLoader"
_APP_DIRS = "citry_django.loaders.AppDirectoriesLoader"
_CACHED = "django.template.loaders.cached.Loader"
_TAGS = "citry_django.templatetags.citry"


class CitryTemplates(DjangoTemplates):
    def __init__(self, params):
        params = params.copy()
        options = params.setdefault("OPTIONS", {}).copy()
        params["OPTIONS"] = options

        # The rewriter injects its tag into templates that have no `{% load %}`
        # line of their own, so it has to resolve as a builtin.
        builtins = list(options.get("builtins", []))
        if _TAGS not in builtins:
            builtins.append(_TAGS)
        options["builtins"] = builtins

        # `Engine` builds this list itself, but from its own loader classes and
        # only when `loaders` is absent; the same shape is rebuilt here with
        # the rewriting ones. Setting both `loaders` and `app_dirs` is an error,
        # hence clearing it.
        if "loaders" not in options:
            loaders: list = [_FILESYSTEM]
            if params.get("APP_DIRS"):
                loaders.append(_APP_DIRS)
            options["loaders"] = [(_CACHED, loaders)]
        params["APP_DIRS"] = False

        super().__init__(params)

    def from_string(self, template_code):
        # `from_string` never goes through a loader, so the rewrite has to
        # happen here too -- otherwise Citry syntax would work in a file and
        # silently not in a string.
        return super().from_string(rewrite_source(template_code))
