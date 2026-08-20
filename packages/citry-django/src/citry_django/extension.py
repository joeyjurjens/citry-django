"""
Django's syntax inside a Citry component template.

Every ``{% ... %}`` is run by Django's own engine. No tag is named here: the
regions come from Django's lexer, and Django's parser builds their structure.

A block whose interior holds Citry content becomes a `ForeignNode`. It compiles
the block once into a Django template with a marker per run of Citry content,
and at render time Django drives, asking back only for the branches it takes.
That ordering is what makes a guarded component cost nothing when the guard is
false, and what lets `{% with %}` bind names Citry can see.

Segments hand Django finished HTML, because that is what Django's node contract
promises: a tag may rewrite, inspect or cache the text its body produced.
"""

from __future__ import annotations

from typing import Any

from citry.citry_context import CitryContext
from citry.citry_render import CitryRender
from citry.component_render import _render_body
from citry.extension import Extension
from citry.nodes import ForeignNode as CitryForeignNode
from citry.nodes import Node
from django.core.exceptions import ImproperlyConfigured
from django.template import engines
from django.template.backends.django import DjangoTemplates
from django.template.base import DebugLexer, Origin, Template, TokenType
from django.template.context import make_context
from django.template.utils import InvalidTemplateEngineError
from django.utils.safestring import mark_safe

from .expressions import is_django_expression
from .nodes import CitryParser, CitrySegment

#: A sentinel standing in for one Citry segment while Django renders a block.
#: Deliberately mixed-case: a tag that rewrites its body text alters it, which
#: is how `_check_sentinels` notices.
#: Where a template's `{% load %}` tags are kept for its nested compiles.
_LOADS_ATTR = "_citry_django_loads"


class _BlockState:
    """
    What a segment needs while Django renders the block around it.

    Carried on the Django ``Context`` rather than in module or thread-local
    state: every node in the block gets that same instance, a nested block
    builds its own, and template code cannot reach it.
    """

    __slots__ = ("citry_context", "node", "segments")

    def __init__(self, node, citry_context):
        self.node = node
        self.citry_context = citry_context
        self.segments = []


def get_django_engine() -> Any:
    """
    Find the project's Django template engine.

    Not simply ``engines["django"]``: a project using
    ``citry_django.backend.CitryTemplates`` (or any other alias) has no engine
    by that name, so the first ``DjangoTemplates``-based engine is used
    instead. Resolved per call because ``engines`` is populated lazily.
    """
    try:
        return engines["django"]
    except InvalidTemplateEngineError:
        pass

    for engine in engines.all():
        if isinstance(engine, DjangoTemplates):
            return engine

    msg = (
        "citry_django needs a Django template engine (a TEMPLATES entry whose "
        "BACKEND is django.template.backends.django.DjangoTemplates, or a "
        "subclass such as citry_django.backend.CitryTemplates), but none is "
        "configured."
    )
    raise ImproperlyConfigured(msg)


class ForeignNode(Node):
    """A Django block whose interior is Citry's, driven by Django."""

    def __init__(
        self,
        source: str,
        segments: list[list[Any]],
        loads: str = "",
    ) -> None:
        self.source = source
        self.segments = segments
        self.loads = loads
        self._template: Any = None

    def _django_template(self) -> Any:
        """Compile the block once, with a marker where each segment belongs."""
        if self._template is not None:
            return self._template

        pieces = [self.loads, self.source]

        engine = get_django_engine().engine
        source = "".join(pieces)
        nodelist = CitryParser(
            DebugLexer(source).tokenize(), engine, Origin("<citry-django>")
        ).parse()
        for node in nodelist.get_nodes_by_type(CitrySegment):
            node.owner = self

        # Tags reach for `context.template`, so the nodelist needs a carrier.
        carrier = Template("", engine=engine)
        carrier.nodelist = nodelist
        self._template = carrier
        return carrier

    def render(self, context: Any) -> Any:
        """
        Let Django drive the block and return what it produced.

        Each segment hands Django finished HTML, so Django's own output is the
        final text and there is nothing to stitch back together afterwards.
        """
        engine = get_django_engine()
        django_context = make_context(
            dict(context.variables),
            context.variables.get("request"),
            autoescape=engine.engine.autoescape,
        )
        django_context.citry_state = _BlockState(self, context)
        carrier = self._django_template()
        with django_context.bind_template(carrier):
            return mark_safe(carrier.nodelist.render(django_context))

    def collect_fills(self, context: Any, sink: Any) -> None:
        return None

    def __repr__(self) -> str:
        return f"ForeignNode({self.source[:40]!r}, {len(self.segments)} segments)"


def render_segment(foreign: ForeignNode, index: int, django_context: Any) -> str:
    """
    Render one Citry segment to finished HTML.

    Serializing with ``deps_strategy="ignore"`` applies the subtree's identity
    markers while leaving its JS/CSS records unemitted, so they still reach the
    page as a whole. Called once per time Django reaches this point, so a
    Django-side ``{% for %}`` gets one render per iteration.
    """
    from citry.component_render import _settle_render
    from citry.serialize import serialize_render

    state = getattr(django_context, "citry_state", None)
    if state is None:  # pragma: no cover - a marker outside its own block
        return ""
    citry_context = state.citry_context

    # The Django context is the live one, so anything a `{% with %}` or a
    # Django-side `{% for %}` pushed is visible to Citry here.
    variables = dict(citry_context.variables)
    variables.update(django_context.flatten())

    segment_context = CitryContext(
        variables=variables,
        extra=citry_context.extra,
        component=citry_context.component,
        provides=citry_context.provides,
        sandboxed=citry_context.sandboxed,
        ownership=citry_context.ownership,
    )

    parts = _render_body(foreign.segments[index], segment_context)
    settled = _settle_render(CitryRender(parts=parts, context=segment_context), finalize_root=False)
    return serialize_render(settled, deps_strategy="ignore")


class CitryDjangoExtension(Extension):
    """
    Install with ``Citry(extensions=[CitryDjangoExtension()])``.

    There is nothing to configure. Which engine owns a given ``{{ ... }}``, and
    whether a Django block hosts Citry content, are both decided from the
    template itself.
    """

    name = "citry_django"

    def on_template_opaque_spans(self, ctx: Any) -> list[tuple[int, int]] | None:
        """
        Claim every span Django owns, using Django's own lexer.

        This is the whole of the adapter's parsing: Django says where its
        syntax is, and Citry keeps it out of its grammar. `{{ ... }}` is
        claimed only when it is Django's (see `expressions.py`), because both
        engines spell interpolation the same way.
        """
        engine = get_django_engine().engine
        tokens = DebugLexer(ctx.content).tokenize()
        libraries = _loaded_libraries(tokens)

        # An attribute value compiles as its own template with no `{% load %}`
        # of its own, so the enclosing template's are kept for it.
        loads = "".join(
            ctx.content[t.position[0] : t.position[1]]
            for t in tokens
            if t.token_type is TokenType.BLOCK and t.contents.split()[:1] == ["load"]
        )
        if loads:
            setattr(ctx.component_class, _LOADS_ATTR, loads)

        spans: list[tuple[int, int]] = []
        verbatim_from: int | None = None
        for token in tokens:
            command = token.contents.split()[:1] if token.token_type is TokenType.BLOCK else []

            # Claimed whole, body included: Django's lexer returns that body as
            # plain text, which Citry would otherwise parse.
            if command == ["verbatim"]:
                verbatim_from = token.position[0]
                continue
            if command == ["endverbatim"] and verbatim_from is not None:
                spans.append((verbatim_from, token.position[1]))
                verbatim_from = None
                continue
            if verbatim_from is not None:
                continue

            if token.token_type is TokenType.TEXT:
                continue
            if token.token_type is TokenType.VAR and not is_django_expression(
                token.contents, engine, libraries
            ):
                continue  # a Citry Python expression
            spans.append(token.position)
        return spans

    def on_template_compiled(self, ctx: Any) -> list[Any] | None:
        loads = "".join(
            node.text
            for node in _walk_foreign(ctx.nodes)
            if node.text.lstrip("{% ").startswith("load")
        ) or getattr(ctx.component_class, _LOADS_ATTR, "")
        return _splice_body(ctx.nodes, loads)


def _loaded_libraries(tokens) -> tuple[str, ...]:
    """Library labels this template loads, so its filters are recognised."""
    labels: list[str] = []
    for token in tokens:
        if token.token_type is not TokenType.BLOCK:
            continue
        words = token.contents.split()
        if words and words[0] == "load":
            labels.extend(words[2:] if "from" in words else words[1:])
    return tuple(dict.fromkeys(label for label in labels if label != "from"))


def _walk_foreign(body: list[Any]):
    """Every Citry ForeignNode in a body, at any depth."""
    for item in body:
        if isinstance(item, CitryForeignNode):
            yield item
        for nested in _nested_bodies(item):
            yield from _walk_foreign(nested)


def _nested_bodies(item: Any):
    """The body lists hanging off a node (component/slot bodies, branches)."""
    body = getattr(item, "body", None)
    if isinstance(body, list):
        yield body
    branches = getattr(item, "branches", None)
    if isinstance(branches, tuple):
        for branch in branches:
            if isinstance(branch, tuple) and len(branch) > 2 and isinstance(branch[2], list):
                yield branch[2]


#: A `{{ ... }}` that is just a name, e.g. `{{ user }}`.
_PLAIN_NAME = str.isidentifier


def _as_django_source(item: Any) -> str | None:
    """
    The Django source for one body item, when it has an exact equivalent.

    A tag may restrict what its body may contain: ``{% blocktranslate %}``
    permits only text and ``{{ name }}`` and rejects block tags at parse time,
    so a body made only of those has to reach Django as source.
    """
    if isinstance(item, str):
        return item
    expression = getattr(item, "expr", None)
    if isinstance(expression, str) and _PLAIN_NAME(expression.strip()):
        return f"{{{{ {expression.strip()} }}}}"
    return None


def _emit_run(pieces: list[str], segments: list[list[Any]], run: list[Any]) -> None:
    """Add one run of Citry content to the Django source being built."""
    equivalents = [_as_django_source(item) for item in run]
    if all(source is not None for source in equivalents):
        pieces.append("".join(equivalents))
        return
    pieces.append(f"{{% citryseg {len(segments)} %}}")
    segments.append(run)


def _splice_body(body: list[Any], loads: str) -> list[Any]:
    """
    Replace a body containing Django tags with a single Django-driven node.

    The body already carries Django's tags as ForeignNode, in the order they
    were written, so the block structure can be rebuilt by handing Django's own
    parser a template made of those tags plus one marker per run of Citry
    content. Django decides what pairs with what; nothing here matches tags.
    """
    for item in body:
        for nested in _nested_bodies(item):
            spliced = _splice_body(nested, loads)
            if spliced is not nested:
                nested[:] = spliced

    if not any(isinstance(item, CitryForeignNode) for item in body):
        return body

    # Alternating: Django source from the foreign tags, Citry runs in between.
    pieces: list[str] = []
    segments: list[list[Any]] = []
    run: list[Any] = []
    for item in body:
        if isinstance(item, CitryForeignNode):
            if run:
                _emit_run(pieces, segments, run)
                run = []
            pieces.append(item.text)
        else:
            run.append(item)
    if run:
        _emit_run(pieces, segments, run)

    return [ForeignNode("".join(pieces), segments, loads)]
