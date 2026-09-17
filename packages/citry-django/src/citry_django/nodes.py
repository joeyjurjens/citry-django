from __future__ import annotations

from typing import Any

from citry import collect_compiled_body_fills, render_compiled_body
from django import template
from django.template.base import Parser
from django.utils.safestring import mark_safe

from .context import HOST_PROVIDE, ContextBehavior
from .engine import get_django_engine
from .page import prepared
from .registry import context_behavior, deps_strategy, get_citry_app


class DottedLoop(dict):
    """Django's ``forloop``, readable as ``forloop.counter0`` in Citry too.

    Django builds it as a plain dictionary, so a template resolves
    ``forloop.counter0`` through its key-then-attribute rule. A Citry
    expression attribute is Python, where a dictionary has no attributes, and
    ``c-lazy="forloop['counter0'] > 4"`` was the only way to write it. Still a
    dictionary, so Django's own resolution, ``forloop['counter0']`` and
    ``{{ forloop.counter0 }}`` are all unchanged.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


def django_scope(context: Any) -> dict:
    """The Django context flattened for a Citry region's scope."""
    scope = context.flatten()
    loop = scope.get("forloop")
    if type(loop) is dict:
        scope["forloop"] = DottedLoop(loop)
    return scope


class CitryName:
    """
    Resolves a bare ``{{ name }}`` the way Citry does.

    Django renders an unknown name as the empty string where Citry raises.
    Resolving against the live context keeps both engines' scopes visible, so
    a name bound by ``{% for %}`` or ``{% with %}`` is found as well.
    """

    __slots__ = ("is_var", "name", "var")

    def __init__(self, name: str) -> None:
        self.name = name
        self.var = name  # Django reads `.var` while parsing.
        # Django >= 6.1.1 reads `.is_var` in `Parser.parse`. False is what
        # Django itself computes here: `.var` is a string, not a `Variable`.
        self.is_var = False

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

    @classmethod
    def from_token(cls, parser: Parser, token: template.base.Token) -> CitrySegment:
        """Build one from `{% citryseg N %}`, as Django's tag registry asks."""
        _, index = token.split_contents()
        return cls(int(index))

    def render(self, context: Any) -> str:
        """Render this run and give Django an inert positional marker.

        The live render stays in the block state until Django has selected and
        ordered all occurrences. Called once per time Django reaches this
        point, so a Django-side `{% for %}` gets one render per iteration.
        """
        state = getattr(context, "citry_state", None)
        if state is None:  # pragma: no cover - a marker outside its own block
            return ""
        variables = django_scope(context)
        body = self.owner.segments[self.index]
        if state.mode == "fills":
            collect_compiled_body_fills(
                body, state.citry_context, state.sink, variables_overlay=variables
            )
            return ""
        rendered = render_compiled_body(body, state.citry_context, variables_overlay=variables)
        return mark_safe(state.retain(rendered))

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
        self.tags["citryseg"] = CitrySegment.from_token

    def compile_filter(self, token: str) -> Any:
        expression = token.strip()
        if expression.isidentifier():
            return CitryName(expression)
        return super().compile_filter(token)


class CitryFragment(template.Node):
    """A ``<c-*>`` region found in a Django template, rendered by Citry."""

    def __init__(self, source: str, origin: str = "<django template>") -> None:
        self.source = source
        # Django's Parser overwrites `Node.origin` while attaching source
        # metadata, so keep Citry's string origin under a distinct name.
        self.citry_origin = origin

    def render(self, context: Any) -> str:
        # `flatten` collapses Django's context stack, so a region inside
        # `{% for article in articles %}` sees `article`. The values go in as
        # component inputs so they scope to this region; `request` travels as a
        # render global because nested components need it for Django's
        # `takes_context` tags.
        request = context.get("request")
        processors = self.context_processors(request)
        variables = dict(processors)
        variables.update(
            {key: value for key, value in django_scope(context).items() if isinstance(key, str)}
        )
        # A context processor is ambient in Django -- every template it renders
        # has `user`, `LANGUAGE_CODE` and the rest, whatever called it. So they
        # go in as render globals, which reach a component's own template at
        # any depth.
        #
        # Whether the *view's* context joins them is the project's call: see
        # `context_behavior`. A global is a fallback, so a component's own
        # names still win either way.
        globals_ = (
            dict(variables) if context_behavior() == ContextBehavior.DJANGO else dict(processors)
        )
        if request is not None:
            globals_["request"] = request
        # The host's own context, reachable from any component through
        # `inject(HOST_PROVIDE)`. An extension that has to reach host state -- an
        # asset collector, say -- needs it in nested components too, where the
        # inputs above no longer reach.
        rendered = get_citry_app().render_template(
            prepared(self.source),
            variables,
            template_globals=globals_ or None,
            provides={HOST_PROVIDE: variables},
            origin=self.citry_origin,
        )
        return mark_safe(
            rendered.serialize(
                deps_strategy=deps_strategy(), csp_nonce=self.csp_nonce(context, request)
            )
        )

    def __repr__(self) -> str:
        return f"<CitryFragment {self.source[:40]!r}>"

    @staticmethod
    def context_processors(request: Any) -> dict[str, Any]:
        """What Django's own context processors put in a template's context.

        A host rendered through `RequestContext` has these already and
        `flatten` picks them up. One rendered without it does not, and a
        component cannot tell the difference, so they are asked for here and
        the host's values are layered on top the way `RequestContext` layers
        them.
        """
        if request is None:
            return {}
        values: dict[str, Any] = {}
        for processor in get_django_engine().engine.template_context_processors:
            values.update(processor(request))
        return values

    @staticmethod
    def csp_nonce(context: Any, request: Any) -> str | None:
        """The host response nonce, without depending on a CSP package."""
        for candidate in (context.get("csp_nonce"), context.get("CSP_NONCE")):
            if candidate is not None:
                return str(candidate)
        nonce = getattr(request, "csp_nonce", None) if request is not None else None
        return None if nonce is None else str(nonce)
