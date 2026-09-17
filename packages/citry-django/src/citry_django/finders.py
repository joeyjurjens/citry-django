from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any

from django.contrib.staticfiles.finders import FileSystemFinder
from django.core.checks import Warning as CheckWarning
from django.core.files.storage import FileSystemStorage

from .registry import get_citry_app


class ComponentFinder(FileSystemFinder):
    """A component's asset files, served the way Django serves static files.

    A component keeps its stylesheet beside its Python::

        components/details/details.py
        components/details/details.scss

    Citry resolves what a component declares against its own ``dirs``, so
    pointing staticfiles at those same directories is what lets Django resolve
    it too::

        # settings.py
        STATICFILES_FINDERS = [
            "django.contrib.staticfiles.finders.FileSystemFinder",
            "django.contrib.staticfiles.finders.AppDirectoriesFinder",
            "citry_django.finders.ComponentFinder",
        ]

    ```python
    css = styles(["details/details.scss"])
    ```

    One list of directories, so the two cannot drift apart: what Citry can
    resolve, `collectstatic` collects and django-compressor can read.

    Only the suffixes in ``served`` leave those directories. A component's
    `.py` and its `.html` are not static files, and a component directory is
    the one place where they sit beside ones that are. Both that set and the
    rule it feeds are yours to replace::

        class ProjectFinder(ComponentFinder):
            served = ComponentFinder.served | {".ts"}

        class ProjectFinder(ComponentFinder):
            def is_served(self, path):
                return super().is_served(path) and ".private." not in path

    Install a subclass under its own dotted path; nothing here reads a
    setting, so a project that needs something else writes it rather than
    spelling it in `settings.py`.
    """

    #: What a browser can be given. Everything else stays where it is.
    served = frozenset(
        {
            ".css",
            ".scss",
            ".sass",
            ".less",
            ".styl",
            ".js",
            ".mjs",
            ".map",
            ".json",
            ".svg",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".avif",
            ".gif",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".otf",
        }
    )

    def __init__(self, app_names: Any = None, *args: Any, **kwargs: Any) -> None:
        self.locations = [("", str(root)) for root in self.dirs()]
        self.storages = {}
        for _prefix, root in self.locations:
            self.storages[root] = self.storage_for(root)
        super(FileSystemFinder, self).__init__(*args, **kwargs)

    def dirs(self) -> tuple[Any, ...]:
        """The directories to serve: the ones Citry resolves assets against.

        One engine's, by default. A project running several - a theme with a
        framework per site, say - overrides this and returns all of them, so
        the finder does not have to guess which one a request belongs to.
        """
        return tuple(get_citry_app().settings.dirs)

    def storage_for(self, root: str) -> Any:
        storage = FileSystemStorage(location=root)
        storage.prefix = ""
        return storage

    def check(self, **kwargs: Any) -> list[Any]:
        """Django's own checks are about `STATICFILES_DIRS`, which this is not."""
        return [
            CheckWarning(
                f"Citry searches '{root}' for a component's assets, but it does not exist.",
                id="citry_django.W001",
            )
            for _prefix, root in self.locations
            if not os.path.isdir(root)
        ]

    def find(self, path: str, find_all: bool = False, **kwargs: Any) -> Any:
        """Django's own answer for a miss, which is an empty list either way."""
        if not self.is_served(path):
            return []
        return super().find(path, find_all=find_all, **kwargs)

    def list(self, ignore_patterns: Any) -> Any:
        for path, storage in super().list(ignore_patterns):
            if self.is_served(path):
                yield path, storage

    def is_served(self, path: str) -> bool:
        return PurePosixPath(path).suffix.lower() in self.served
