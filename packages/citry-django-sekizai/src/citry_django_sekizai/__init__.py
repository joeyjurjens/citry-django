"""
Citry's own asset declarations, routed through django-sekizai.

Citry serializes a component's CSS and JS into the page itself. A project that
already runs its assets through Sekizai -- and usually django-compressor behind
it -- wants them in *its* blocks instead, where they can be bundled, minified
and cached with everything else.

This extension reads what Citry already resolved, so a component keeps
declaring its assets exactly as Citry documents. There is no second way to
declare anything::

    from citry import Citry
    from citry_django import CitryDjangoExtension
    from citry_django_sekizai import SekizaiAssets

    app = Citry(extensions=[CitryDjangoExtension(), SekizaiAssets()])

Set ``CITRY_DEPS_STRATEGY = "ignore"`` alongside it, or every asset lands on the
page twice: once from Citry and once from Sekizai.
"""

from __future__ import annotations

import bisect
from typing import Any

from citry.assets import load_css, load_js
from citry.extension import Extension

__all__ = ["SekizaiAssets"]

SEKIZAI_HOLDER = "SEKIZAI_CONTENT_HOLDER"


class SekizaiAssets(Extension):
    """
    Adds each rendering component's assets to a Sekizai block.

    ``css_block`` and ``js_block`` name the blocks to add to, matching whatever
    your base template already renders with ``{% render_block %}``.
    """

    name = "sekizai"

    def __init__(self, *, css_block: str = "css", js_block: str = "js") -> None:
        self._blocks = (
            (css_block, load_css, "style"),
            (js_block, load_js, "script"),
        )

    def on_component_data(self, ctx: Any) -> None:
        # The holder travels through the adapter's `django` provide, which is
        # filled from the host context. A component nested several levels deep
        # reaches it just as the outermost one does.
        holder = (ctx.component.inject("django", None) or {}).get(SEKIZAI_HOLDER)
        if holder is None:
            return

        component = type(ctx.component)
        for block, load, tag in self._blocks:
            content = load(component)
            if not content:
                continue
            markup = f"<{tag}>{content}</{tag}>"
            if markup not in holder[block]:
                # Sorted rather than appended: components render in whatever
                # order the page reaches them, and a stable order is what makes
                # a compressor's cache key stable.
                bisect.insort(holder[block].data, markup)
