from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from citry import collect_compiled_body_fills, render_compiled_body
from django import template
from django.template import defaulttags
from django.template.base import (
    FilterExpression,
    Node,
    Parser,
    TextNode,
    VariableNode,
    render_value_in_context,
)
from django.template.loader_tags import BlockNode, ExtendsNode
from django.templatetags.cache import CacheNode
from django.templatetags.i18n import LanguageNode
from django.templatetags.l10n import LocalizeNode
from django.templatetags.tz import LocalTimeNode, TimezoneNode
from django.utils.safestring import SafeData, mark_safe

from .context import HOST_PROVIDE, ContextBehavior
from .engine import context_processors
from .events import remember_page_nonce
from .i18n import LOCALE_PROVIDE, locale_context
from .islands import (
    ISLANDS_PROVIDE,
    IslandOptions,
    PendingIslands,
    ensure_csrf_cookie,
    island_csp_nonce,
    refuse_misplaced_islands,
    request_csp_nonce,
    serialize_region,
)
from .page import Assets, slot
from .registry import context_behavior, get_citry_app

# Citry writes the ESC control character in an escaped value as this
# reference (see `CitryVariableNode`).
ESC = "\x1b"
ESC_REFERENCE = "&#27;"


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


class CitryVariableNode(VariableNode):
    """
    A ``{{ ... }}`` inside a Django block, written the way Citry writes a value.

    Citry writes the ESC control character as ``&#27;`` when it escapes a
    value, so a page declared in an encoding such as ISO-2022-JP cannot read
    it as a switch to another character set. Django's escaping leaves ESC as
    is, so the same value would reach the page differently inside a block.
    Only the written output changes: a tag that takes the value as an
    argument resolves it through the parser as before.
    """

    def render(self, context: Any) -> str:
        try:
            value = self.filter_expression.resolve(context)
        except UnicodeDecodeError:  # pragma: no cover - Django's own fallback
            return ""
        output = render_value_in_context(value, context)
        # With autoescape off, the author asked Django not to escape at all.
        if ESC not in output or not context.autoescape or self.is_trusted(value):
            return output
        return mark_safe(output.replace(ESC, ESC_REFERENCE))

    def is_trusted(self, value: Any) -> bool:
        """Whether the author marked this output as HTML, which Citry leaves as written.

        Django's escaping filters (`escape`, `linebreaks`, `urlize` and the
        like) also return safe text, with the value's ESC still in it, so
        only a value that reached the expression already safe, with no
        filter, or an explicit `safe` or `safeseq` counts.
        """
        filters = getattr(self.filter_expression, "filters", ())
        if not filters:
            return hasattr(value, "__html__")
        return any(getattr(func, "__name__", "") in TRUSTING_FILTERS for func, _ in filters)


#: The filters with which an author marks a value as HTML.
TRUSTING_FILTERS = frozenset({"safe", "safeseq"})


def written_as_citry(text: str) -> str:
    """Escaped HTML with ESC written as Citry writes it, still marked as escaped."""
    return mark_safe(text.replace(ESC, ESC_REFERENCE))


def is_escaped_with_esc(value: Any) -> bool:
    """Whether ``value`` is text Django marked as escaped that still holds ESC."""
    return isinstance(value, SafeData) and isinstance(value, str) and ESC in value


class CitryFilterExpression(FilterExpression):
    """
    A filtered value inside a Django block, with ESC written as Citry writes it.

    Django's escaping filters (`escape`, `force_escape`, `urlize` and the
    like) return text marked as escaped with the value's ESC still in it. That
    text can travel on before it is written, through `{% with v=n|escape %}`
    or a tag argument, and the `{{ v }}` that finally writes it would take it
    as the author's HTML. So the escaped text gets `&#27;` as soon as the
    filters return it. A `safe` or `safeseq` filter means the author marked
    the value as HTML, and autoescape off means the author asked for no
    escaping, so both are left as written.
    """

    __slots__ = ()

    def resolve(self, context: Any, ignore_failures: bool = False) -> Any:
        value = super().resolve(context, ignore_failures)
        if not self.filters or not is_escaped_with_esc(value) or not context.autoescape:
            return value
        if any(getattr(func, "__name__", "") in TRUSTING_FILTERS for func, _ in self.filters):
            return value
        return written_as_citry(value)


def _optional_node(module: Any, name: str) -> tuple[type, ...]:
    # `{% partialdef %}` exists only from Django 6.0 on.
    node = getattr(module, name, None)
    return (node,) if node is not None else ()


#: Django's own tags that write nothing but their children and fixed
#: author text. Their children are compiled by the same parser and handle ESC
#: themselves, and some of them hold HTML the author marked as such (`|safe`,
#: `{% autoescape off %}`), so their output is left as written. Matched by
#: exact type: a subclass may write more than its children.
PASS_THROUGH_TAGS = frozenset(
    {
        defaulttags.AutoEscapeControlNode,
        defaulttags.CommentNode,
        defaulttags.FilterNode,
        defaulttags.ForNode,
        defaulttags.IfChangedNode,
        defaulttags.IfNode,
        defaulttags.SpacelessNode,
        defaulttags.VerbatimNode,
        defaulttags.WithNode,
        *_optional_node(defaulttags, "PartialDefNode"),
        BlockNode,
        ExtendsNode,
        CacheNode,
        LanguageNode,
        LocalizeNode,
        LocalTimeNode,
        TimezoneNode,
    }
)


def render_escaped(node: Node, context: Any, render: Any) -> str:
    """
    Render a tag inside a Django block, with ESC in what it writes written as Citry writes it.

    Every tag that is not plain text, a run of Citry content, a `{{ }}` or one
    of `PASS_THROUGH_TAGS` renders through here: `{% include %}`,
    `{% firstof %}`, `{% translate %}`, any `simple_tag`, `inclusion_tag` or
    `simple_block_tag`, and any third-party tag such as django-components'
    `{% component %}`. Such a tag writes HTML this parser did not compile,
    often escaped by `format_html` or by a template of its own, so its whole
    output is treated as escaped values, even HTML its own code marked safe.
    A tag that stores its result in a variable instead
    (`{% translate "x" as v %}`) has the stored value treated the same way, so
    the `{{ v }}` that writes it later cannot take it as the author's HTML.
    ``render`` is the tag class's own `render`.
    """
    # With autoescape off, the author asked Django not to escape at all.
    if not context.autoescape:
        return render(node, context)
    scope = context.dicts[-1]
    before = dict(scope)
    output = render(node, context)
    # A tag stores its result in the innermost scope (`context[name] = ...`).
    for name, value in scope.items():
        if value is not before.get(name, _UNSET) and is_escaped_with_esc(value):
            scope[name] = written_as_citry(value)
    if ESC not in output:
        return output
    return written_as_citry(output)


_UNSET = object()

#: Each tag class mapped to its subclass that renders through `render_escaped`,
#: made the first time a block uses that tag.
_ESCAPING_CLASSES: dict[type, type] = {}


def escaping_class(node_class: type) -> type:
    """
    A subclass of ``node_class`` that renders through `render_escaped`, made once and reused.

    A node is switched to it in place rather than wrapped, so it keeps its
    own class and identity: `{% resetcycle %}` still finds the cycle it
    names, and a tag that looks for its own node types in its body (such as
    Wagtail's `{% block_field %}` inside `{% wagtail_block %}`) still finds
    them. It adds no slots, so the switch works whatever the class's layout.
    """
    found = _ESCAPING_CLASSES.get(node_class)
    if found is not None:
        return found

    def render(self: Node, context: Any) -> str:
        return render_escaped(self, context, node_class.render)

    namespace = {
        "__slots__": (),
        "__module__": node_class.__module__,
        "__qualname__": node_class.__qualname__,
        "render": render,
        "citry_escapes_output": True,
    }
    made = type(node_class.__name__, (node_class,), namespace)
    return _ESCAPING_CLASSES.setdefault(node_class, made)


def escaping_node(node: Node) -> Node:
    """``node`` as it renders inside a Django block, with ESC written as Citry writes it."""
    if type(node) is VariableNode:
        return CitryVariableNode(node.filter_expression)
    if isinstance(node, (TextNode, CitrySegment, CitryVariableNode)):
        return node
    if type(node) in PASS_THROUGH_TAGS or vars(type(node)).get("citry_escapes_output"):
        return node
    node.__class__ = escaping_class(type(node))
    return node


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


class EscapingParser(Parser):
    """
    Django's parser, writing ESC in escaped values the way Citry does.

    Every `{{ ... }}`, every tag and every filtered value reaches the nodelist
    through `extend_nodelist` or `compile_filter`, including those inside a
    nested `{% if %}` or `{% for %}`, so these two places cover them all.
    """

    def extend_nodelist(self, nodelist: Any, node: Any, token: Any) -> None:
        super().extend_nodelist(nodelist, escaping_node(node), token)

    def compile_filter(self, token: str) -> Any:
        return CitryFilterExpression(token, self)


class CitryParser(EscapingParser):
    """
    Django's parser, with two additions for the block templates we build.

    ``{% citryseg N %}`` marks where a run of Citry content belongs, and a bare
    ``{{ name }}`` resolves through :class:`CitryName`. ESC is written as
    :class:`EscapingParser` writes it; everything else is compiled by Django
    unchanged.
    """

    def __init__(self, tokens: Any, engine: Any, origin: Any) -> None:
        super().__init__(tokens, engine.template_libraries, engine.template_builtins, origin)
        self.tags["citryseg"] = CitrySegment.from_token

    def compile_filter(self, token: str) -> Any:
        expression = token.strip()
        if expression.isidentifier():
            return CitryName(expression)
        return super().compile_filter(token)


class CitryAssetsSlot(template.Node):
    """A `<c-css />` or `<c-js />` in a Django template: where the page's tags go."""

    def __init__(self, kind: str) -> None:
        self.kind = Assets(kind)

    def render(self, context: Any) -> str:
        return mark_safe(slot(self.kind))


class CitryFragment(template.Node):
    """A ``<c-*>`` region found in a Django template, rendered by Citry."""

    def __init__(
        self,
        source: str,
        origin: str = "<django template>",
        *,
        open_elements: Iterable[str] = (),
    ) -> None:
        self.source = source
        # Django's Parser overwrites `Node.origin` while attaching source
        # metadata, so keep Citry's string origin under a distinct name.
        self.citry_origin = origin
        # The HTML elements the template leaves open around this region,
        # outermost first, so an island can refuse a place the browser
        # would move it out of.
        self.open_elements = tuple(open_elements)

    def render(self, context: Any) -> str:
        # `flatten` collapses Django's context stack, so a region inside
        # `{% for article in articles %}` sees `article`. The values go in as
        # component inputs so they scope to this region; `request` travels as a
        # render global because nested components need it for Django's
        # `takes_context` tags.
        request = context.get("request")
        # A host rendered through `RequestContext` has these already and
        # `flatten` picks them up; the host's values are layered on top.
        processors = context_processors(request)
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
        nonce = self.csp_nonce(context, request)
        # The Django blocks inside this region wait here until it has rendered.
        pending = PendingIslands()
        provides = {
            HOST_PROVIDE: variables,
            # Islands built inside a component's Django blocks read this.
            ISLANDS_PROVIDE: IslandOptions(csp_nonce=nonce, request=request, pending=pending),
        }
        app = get_citry_app()
        # Citry content follows the language Django activated for this
        # request, as the Django template around the region does.
        locale = locale_context(app)
        if locale is not None:
            provides[LOCALE_PROVIDE] = locale
        rendered = app.render_template(
            self.source,
            variables,
            template_globals=globals_ or None,
            provides=provides,
            origin=self.citry_origin,
        )
        # Before the region itself: once components in its Django blocks are
        # islands, the region may need no Vue of its own.
        inner_islands = pending.settle(rendered, csp_nonce=nonce, request=request)
        html, island = serialize_region(
            rendered, csp_nonce=nonce, reason=pending.reason, request=request
        )
        refuse_misplaced_islands(html, open_elements=self.open_elements, origin=self.citry_origin)
        if island or inner_islands:
            # An island may hold Events, whose calls need the CSRF cookie and,
            # for HTML a call answers with, this page's nonce.
            ensure_csrf_cookie(request)
            remember_page_nonce(app, request, nonce)
        return mark_safe(html)

    def __repr__(self) -> str:
        return f"<CitryFragment {self.source[:40]!r}>"

    @staticmethod
    def csp_nonce(context: Any, request: Any) -> str | None:
        """The nonce of the page this region lands in, without depending on a CSP package.

        Usually the response's own nonce. A partial response lands in a page
        that is already loaded, so its islands carry that page's nonce
        instead (see `island_csp_nonce`).
        """
        for candidate in (context.get("csp_nonce"), context.get("CSP_NONCE")):
            if candidate is not None:
                return island_csp_nonce(request, str(candidate))
        return island_csp_nonce(request, request_csp_nonce(request))
