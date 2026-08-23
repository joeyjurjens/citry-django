"""
Template loaders that rewrite Citry element syntax as the source is read.

Rewriting at *load* time (rather than per render) means the result is compiled
once and cached by Django's ``cached.Loader`` like any other template, and it
applies to every template Django loads -- including ``base.html`` and templates
shipped by third-party apps.
"""

from __future__ import annotations

from django.template.loaders import app_directories, filesystem

from .rewrite import rewrite_source


class _RewriteMixin:
    def get_contents(self, origin):
        return rewrite_source(super().get_contents(origin), origin=origin.name)


class FilesystemLoader(_RewriteMixin, filesystem.Loader):
    """``DIRS`` loader with Citry element syntax enabled."""


class AppDirectoriesLoader(_RewriteMixin, app_directories.Loader):
    """``APP_DIRS`` loader with Citry element syntax enabled."""
