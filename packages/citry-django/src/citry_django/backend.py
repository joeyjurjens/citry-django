from __future__ import annotations

from typing import Any

from django.template.backends.django import DjangoTemplates, Template
from django.utils.safestring import mark_safe

from .page import PageAssets, collected
from .rewrite import rewrite_source

TAGS_MODULE = "citry_django.templatetags.citry"


class _RewriteMixin:
    """Rewrites Citry element syntax as a loader reads a template."""

    def get_contents(self, origin: Any) -> str:
        return rewrite_source(super().get_contents(origin), origin=origin.name)


def enable_rewriting(loaders: Any) -> None:
    """
    Teach every configured loader to rewrite, whoever wrote it.

    Django resolves ``get_contents`` on the loader that finally reads the file,
    so rewriting is added there rather than by substituting loader classes. A
    project that configures its own ``loaders`` -- for a component library, a
    pattern library, or just to control caching -- keeps them and gets Citry
    syntax in the templates they load.
    """
    for loader in loaders:
        nested = getattr(loader, "loaders", None)
        if nested:
            enable_rewriting(nested)
        elif not isinstance(loader, _RewriteMixin):
            cls = type(loader)
            loader.__class__ = type(f"Rewriting{cls.__name__}", (_RewriteMixin, cls), {})


class CitryTemplates(DjangoTemplates):
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

    This is still Django's own engine: same lexer, same tags, same inheritance. The
    only difference is that source is rewritten as it is read, so ``<c-component/>``
    becomes a tag Django can compile. A template with no Citry syntax in it is
    returned unchanged.
    """

    def __init__(self, params: dict) -> None:
        params = params.copy()
        options = params.setdefault("OPTIONS", {}).copy()
        params["OPTIONS"] = options

        # The rewriter injects its tag into templates that have no `{% load %}`
        # line of their own, so it has to resolve as a builtin.
        builtins = list(options.get("builtins", []))
        if TAGS_MODULE not in builtins:
            builtins.append(TAGS_MODULE)
        options["builtins"] = builtins

        super().__init__(params)
        enable_rewriting(self.engine.template_loaders)

    def from_string(self, template_code: str) -> Any:
        # `from_string` never reaches a loader, so it rewrites here as well.
        source = rewrite_source(template_code, origin="<string template>")
        return PageTemplate(super().from_string(source).template, self)

    def get_template(self, template_name: str) -> Any:
        return PageTemplate(super().get_template(template_name).template, self)


class PageTemplate(Template):
    """One page render, and the assets its Citry regions placed.

    A region keeps its own assets and says where they are, so its HTML stands
    on its own; the page reads those spots once the whole template is rendered.
    Where the tags end up is the host template's business: `<c-css />` and
    `<c-js />` name the spot, and without them they stay where Citry put them.
    """

    def render(self, context: Any = None, request: Any = None) -> str:
        page = PageAssets.open()
        try:
            html = super().render(context, request)
        finally:
            if page is not None:
                page.close()
        return mark_safe(collected(html, page))
