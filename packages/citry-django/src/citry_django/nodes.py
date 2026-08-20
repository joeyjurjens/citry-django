"""Django nodes and the parser that builds them."""

from __future__ import annotations

from typing import Any

from django import template
from django.conf import settings
from django.template.base import Parser
from django.utils.safestring import mark_safe

from .registry import get_citry_app

#: Names that cannot be passed to a component: ``self`` is bound by
#: ``Component.__init__`` and ``slots`` is Citry's own keyword for fills.
RESERVED_INPUT_NAMES = frozenset({"self", "slots"})


class CitryName:
    """
    Resolves a bare ``{{ name }}`` the way Citry does.

    Django renders an unknown name as the empty string where Citry raises.
    Resolving against the live context keeps both engines' scopes visible, so
    a name bound by ``{% for %}`` or ``{% with %}`` is found as well.
    """

    __slots__ = ("name", "var")

    def __init__(self, name: str) -> None:
        self.name = name
        self.var = name  # Django reads `.var` while parsing.

    def resolve(self, context: Any, ignore_failures: bool = False) -> Any:
        scope = context.flatten()
        if self.name not in scope:
            msg = f"Unknown variable {self.name!r}"
            raise KeyError(msg)
        return scope[self.name]


class CitrySegment(template.Node):
    """One run of Citry content inside a Django block."""

    def __init__(self, index: int) -> None:
        self.index = index
        self.owner: Any = None  # Bound by ForeignNode once the block compiles.

    def render(self, context: Any) -> str:
        from .extension import render_segment

        return render_segment(self.owner, self.index, context)

    def __repr__(self) -> str:
        return f"<CitrySegment {self.index}>"


class CitryParser(Parser):
    """
    Django's parser, with two additions for the block templates we build.

    ``{% citryseg N %}`` marks where a run of Citry content belongs, and a bare
    ``{{ name }}`` resolves through :class:`CitryName`. Everything else is
    compiled by Django unchanged.
    """

    def __init__(self, tokens: Any, engine: Any, origin: Any) -> None:
        super().__init__(tokens, engine.template_libraries, engine.template_builtins, origin)
        self.tags["citryseg"] = _parse_segment

    def compile_filter(self, token: str) -> Any:
        expression = token.strip()
        if expression.isidentifier():
            return CitryName(expression)
        return super().compile_filter(token)


def _parse_segment(parser: Parser, token: template.base.Token) -> CitrySegment:
    _, index = token.split_contents()
    return CitrySegment(int(index))


class CitryFragment(template.Node):
    """A ``<c-*>`` region found in a Django template, rendered by Citry."""

    def __init__(self, source: str) -> None:
        self.source = source

    def render(self, context: Any) -> str:
        # `flatten` collapses Django's context stack, so a region inside
        # `{% for article in articles %}` sees `article`. The values go in as
        # component inputs so they scope to this region; `request` travels as a
        # render global because nested components need it for Django's
        # `takes_context` tags.
        variables = {
            key: value
            for key, value in context.flatten().items()
            if isinstance(key, str) and key not in RESERVED_INPUT_NAMES
        }
        request = context.get("request")
        # The host's own context, reachable from any component through
        # `inject("django")`. An extension that has to reach host state (a
        # Sekizai holder, say) needs it in nested components too, where the
        # inputs above no longer reach.
        rendered = get_citry_app().render_fragment(
            self.source,
            variables,
            template_globals={"request": request} if request is not None else None,
            provides={"django": variables},
        )
        # Set `CITRY_DEPS_STRATEGY = "ignore"` when the page collects assets
        # itself, through Sekizai or otherwise, so they are not emitted twice.
        strategy = getattr(settings, "CITRY_DEPS_STRATEGY", "document")
        return mark_safe(rendered.serialize(deps_strategy=strategy))

    def __repr__(self) -> str:
        return f"<CitryFragment {self.source[:40]!r}>"
