from __future__ import annotations

import re
import warnings
from contextvars import ContextVar
from typing import Any

from django.conf import settings
from django.template.backends.django import DjangoTemplates, Template
from django.utils.safestring import mark_safe

from .events import refresh_page_nonce
from .islands import island_ids, request_csp_nonce
from .page import PageAssets, collected
from .partials import PartialResponseWarning, is_partial
from .registry import get_citry_app
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
        # Only the outermost render is the response; a template rendered
        # inside another one is part of that page by design. Tracked apart
        # from `page`, which `CITRY_COLLECT_PAGE_ASSETS = False` turns off.
        outermost = not rendering.get()
        token = rendering.set(True) if outermost else None
        try:
            html = super().render(context, request)
        finally:
            if page is not None:
                page.close()
            if token is not None:
                rendering.reset(token)
        html = collected(html, page)
        if outermost:
            if request is None and isinstance(context, dict):
                request = context.get("request")
            if not is_partial(request):
                refresh_page_nonce(get_citry_app(), request, page_nonce(context, request))
            warn_if_partial_looking(html, request)
        return mark_safe(html)


#: Whether a `PageTemplate` render is running, so a nested one knows it is
#: not the response.
rendering: ContextVar[bool] = ContextVar("citry_django_rendering", default=False)


def page_nonce(context: Any, request: Any) -> str | None:
    """This whole page's CSP nonce, read the way a region reads it."""
    if isinstance(context, dict):
        for key in ("csp_nonce", "CSP_NONCE"):
            if context.get(key) is not None:
                return str(context[key])
    return request_csp_nonce(request)


#: What only a whole page has: a `<body>` or `<html>` start tag, or a
#: doctype. A page may leave out `<body>`, which the browser adds itself.
WHOLE_PAGE = re.compile(r"<(?:body|html)[\s>]|<!doctype", re.IGNORECASE)


def warn_if_partial_looking(html: str, request: Any) -> None:
    """In development, warn when a page response holds an island but looks partial.

    Such a response is usually part of a page that the browser inserts into a
    loaded one, which citry-django could not tell from the request. Its islands
    were then written for a whole page, and their start scripts do not run
    when the HTML is inserted, so they show up and do nothing.
    """
    if not settings.DEBUG or is_partial(request) or WHOLE_PAGE.search(html):
        return
    if not island_ids(html):
        return
    # Python shows a warning once per message and place, and every warning
    # here comes from the same place, so the path tells them apart.
    path = getattr(request, "path", None)
    where = f" ({path})" if path else ""
    warnings.warn(
        f"This response{where} has no <body> but holds a component that needs "
        "Vue, so it looks like part of a page. citry-django wrote it for a whole "
        "page, and its scripts do not start when the HTML is inserted into a page "
        "that is already loaded. If the browser inserts this response into a "
        "page, make the request with htmx, which sends HX-Request, or set "
        "request.citry_partial = True in the view.",
        PartialResponseWarning,
        stacklevel=3,
    )
