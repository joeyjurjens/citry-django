"""
Django's syntax inside a Citry component template.

Every ``{% ... %}`` is run by Django's own engine. No tag is named here: the
regions come from Django's lexer, and Django's parser builds their structure.

A block whose interior holds Citry content becomes a `ForeignNode`. It compiles
the block once into a Django template with a marker per run of Citry content,
and at render time Django drives, asking back only for the branches it takes.
That ordering is what makes a guarded component cost nothing when the guard is
false, and what lets `{% with %}` bind names Citry can see.

Segments hand Django inert markers while retaining their structured
``CitryRender`` values. Once Django has selected, ordered, and repeated the
markers, the adapter rebuilds one structured Citry render for the enclosing
serializer. A tag that alters or discards a reached marker fails loudly.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from secrets import token_hex
from threading import RLock
from typing import Any, cast

from citry import (
    CitryRender,
    CompiledBody,
    collect_compiled_body_fills,
    render_compiled_body,
)
from citry.extension import Extension, ForeignSpan, ForeignSpanSet
from citry.nodes import ForeignHtmlAttr as CitryForeignHtmlAttr
from citry.nodes import ForeignNode as CitryForeignNode
from citry.nodes import HtmlAttr, Node
from django.core.exceptions import ImproperlyConfigured
from django.template import engines
from django.template.backends.django import DjangoTemplates
from django.template.base import DebugLexer, Origin, Template, TokenType
from django.template.context import make_context
from django.template.exceptions import TemplateSyntaxError
from django.template.utils import InvalidTemplateEngineError
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .expressions import is_django_expression
from .nodes import CitryParser, CitrySegment
from .registry import get_tokenizer

_SEGMENT_MARKER_LABEL = "CiTrY-SeGmEnT"

#: Any segment marker, whatever render produced it. Used to catch a marker that
#: outlived the render it belonged to, which a body-caching tag will do.
_ANY_SEGMENT_MARKER = re.compile(
    rf"(?:<!--|&lt;!--){re.escape(_SEGMENT_MARKER_LABEL)}:(?P<nonce>[0-9a-f]+):\d+(?:-->|--&gt;)"
)


class _BlockState:
    """
    What a segment needs while Django renders the block around it.

    Carried on the Django ``Context`` rather than in module or thread-local
    state: every node in the block gets that same instance, a nested block
    builds its own, and template code cannot reach it.
    """

    __slots__ = ("citry_context", "mode", "node", "nonce", "renders", "sink")

    def __init__(
        self,
        node: ForeignNode,
        citry_context: Any,
        *,
        mode: str = "render",
        sink: Any = None,
    ) -> None:
        self.node = node
        self.citry_context = citry_context
        self.nonce = token_hex(16)
        self.renders: list[CitryRender] = []
        self.mode = mode
        self.sink = sink

    def retain(self, rendered: CitryRender) -> str:
        """Retain one live render and return its exact marker for Django."""
        index = len(self.renders)
        self.renders.append(rendered)
        return self._marker(index)

    def _marker(self, index: int) -> str:
        return f"<!--{_SEGMENT_MARKER_LABEL}:{self.nonce}:{index}-->"

    def restore(self, html: str) -> CitryRender:
        """Replace Django's intact markers with their structured renders."""
        raw_prefix = f"<!--{_SEGMENT_MARKER_LABEL}:{self.nonce}:"
        raw_suffix = "-->"
        escaped_prefix = str(escape(raw_prefix))
        escaped_suffix = str(escape(raw_suffix))
        pattern = re.compile(
            rf"(?P<raw>{re.escape(raw_prefix)}(?P<raw_index>\d+){re.escape(raw_suffix)})"
            rf"|(?P<escaped>{re.escape(escaped_prefix)}(?P<escaped_index>\d+)"
            rf"{re.escape(escaped_suffix)})"
        )
        occurrences: list[tuple[int, int, int, bool]] = []
        seen: list[int] = []
        for match in pattern.finditer(html):
            raw_index = match.group("raw_index")
            index = int(raw_index if raw_index is not None else match.group("escaped_index"))
            seen.append(index)
            occurrences.append((match.start(), match.end(), index, raw_index is None))
        if sorted(seen) != list(range(len(self.renders))):
            msg = (
                "Django transformed, duplicated, or discarded a reached Citry segment marker. "
                "Tags around Citry components must preserve their rendered body positions."
            )
            raise RuntimeError(msg)

        self._reject_markers_from_another_render(html)

        parts: list[Any] = []
        cursor = 0
        for start, end, index, was_escaped in sorted(occurrences):
            if start > cursor:
                parts.append(html[cursor:start])
            rendered = self.renders[index]
            if was_escaped:
                parts.append(str(escape(rendered.serialize(deps_strategy="ignore"))))
            else:
                parts.append(rendered)
            cursor = end
        if cursor < len(html):
            parts.append(html[cursor:])
        return CitryRender(parts=parts, context=self.citry_context)

    def _reject_markers_from_another_render(self, html: str) -> None:
        """
        Refuse a marker that belongs to a render which has already finished.

        A tag that stores its rendered body and replays it later, as any
        fragment cache does, stores the marker rather than the markup: the
        markup only exists once this block finishes. On a later hit the body
        never renders, so there is nothing to put back and the marker would
        reach the browser as a visible comment. The integrity check above cannot
        see it: that one knows only this render's markers, and on a cache hit
        there are none.
        """
        stale = {
            match.group("nonce")
            for match in _ANY_SEGMENT_MARKER.finditer(html)
            if match.group("nonce") != self.nonce
        }
        if not stale:
            return
        msg = (
            "A Django tag replayed a cached body that contains Citry content from an "
            "earlier render, which cannot be restored. Cache the component instead of "
            "the markup around it: give it a nested `class Cache:` and let Citry cache "
            "its output, or move the tag so it does not enclose Citry content."
        )
        raise RuntimeError(msg)


def _explain_tokenizer_disagreement(exc: TemplateSyntaxError) -> TemplateSyntaxError:
    """
    Say why Django's parser rejected tags Django's own lexer produced.

    Which byte ranges belong to Django is decided by the extension's
    `tokenizer`, Django's own lexer unless the project passed another. If
    something else compiles the template and it ends tags somewhere else, the
    parser is handed a fragment of a tag, and the error that surfaces explains
    nothing on its own.
    """
    return TemplateSyntaxError(
        f"{exc} -- Django's parser rejected a tag that the configured tokenizer "
        "produced. This usually means your templates are compiled by a different "
        "tokenizer, so its idea of where a tag stops differs from the one read "
        "here. Pass that tokenizer to CitryDjangoExtension(tokenizer=...)."
    )


def _django_lexer(source: str) -> list[Any]:
    return DebugLexer(source).tokenize()


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
        segments: list[CompiledBody],
        loads: str = "",
        origin: str = "<citry-django>",
    ) -> None:
        self.source = source
        self.segments = segments
        self.loads = loads
        self.origin = origin
        self._template: Any = None
        self._template_lock = RLock()

    def _django_template(self) -> Any:
        """Compile the block once, with a marker where each segment belongs."""
        if self._template is not None:
            return self._template
        with self._template_lock:
            if self._template is None:
                pieces = [self.loads, self.source]

                engine = get_django_engine().engine
                source = "".join(pieces)
                origin = Origin(self.origin, template_name=self.origin)
                try:
                    nodelist = CitryParser(get_tokenizer()(source), engine, origin).parse()
                except TemplateSyntaxError as exc:
                    raise _explain_tokenizer_disagreement(exc) from exc
                for node in nodelist.get_nodes_by_type(CitrySegment):
                    node.owner = self

                # Tags reach for `context.template`, so the nodelist needs a carrier.
                carrier = Template("", origin=origin, engine=engine)
                carrier.nodelist = nodelist
                self._template = carrier
        return self._template

    def render(self, context: Any) -> Any:
        """
        Let Django drive the block and return what it produced.

        Each reached segment gives Django an inert marker. Django still owns
        branch selection and repetition; afterward the markers are restored as
        nested ``CitryRender`` parts so outer serialization sees the full tree.
        """
        engine = get_django_engine()
        django_context = make_context(
            dict(context.variables),
            context.variables.get("request"),
            autoescape=engine.engine.autoescape,
        )
        state = _BlockState(self, context)
        django_context.citry_state = state
        carrier = self._django_template()
        with django_context.bind_template(carrier):
            html = carrier.nodelist.render(django_context)
        return state.restore(html)

    def collect_fills(self, context: Any, sink: Any) -> None:
        engine = get_django_engine()
        django_context = make_context(
            dict(context.variables),
            context.variables.get("request"),
            autoescape=engine.engine.autoescape,
        )
        django_context.citry_state = _BlockState(self, context, mode="fills", sink=sink)
        carrier = self._django_template()
        with django_context.bind_template(carrier):
            carrier.nodelist.render(django_context)

    def __repr__(self) -> str:
        return f"ForeignNode({self.source[:40]!r}, {len(self.segments)} segments)"


class DjangoHtmlAttr(HtmlAttr):
    """A component input whose ordered source is rendered by Django."""

    def __init__(
        self,
        source: str,
        position: tuple[int, int],
        key: str,
        loads: str,
        origin: str,
    ) -> None:
        self.source = source
        self.position = position
        self.key = key
        self.loads = loads
        self.origin = origin
        self.used_vars = ()
        self._template = None
        self._template_lock = RLock()

    def resolve(self, context: Any) -> Any:
        if self._template is None:
            with self._template_lock:
                if self._template is None:
                    engine = get_django_engine().engine
                    self._template = Template(
                        self.loads + self.source,
                        origin=Origin(self.origin, template_name=self.origin),
                        engine=engine,
                    )
        template = self._template
        if template is None:  # pragma: no cover - guarded by the lock above
            raise RuntimeError("Django foreign template compilation did not publish a template.")
        engine = get_django_engine()
        request = context.variables.get("request")
        django_context = make_context(
            dict(context.variables),
            request,
            autoescape=engine.engine.autoescape,
        )
        return mark_safe(template.render(django_context))


def render_segment(foreign: ForeignNode, index: int, django_context: Any) -> str:
    """
    Render one Citry segment and give Django an inert positional marker.

    The live render stays in the block state until Django has selected and
    ordered all occurrences. Called once per time Django reaches this point, so
    a Django-side ``{% for %}`` gets one distinct render per iteration.
    """
    state = getattr(django_context, "citry_state", None)
    if state is None:  # pragma: no cover - a marker outside its own block
        return ""
    variables = django_context.flatten()
    if state.mode == "fills":
        collect_compiled_body_fills(
            foreign.segments[index],
            state.citry_context,
            state.sink,
            variables_overlay=variables,
        )
        return ""
    rendered = render_compiled_body(
        foreign.segments[index],
        state.citry_context,
        variables_overlay=variables,
    )
    return mark_safe(state.retain(rendered))


class CitryDjangoExtension(Extension):
    """
    Install with ``Citry(extensions=[CitryDjangoExtension()])``.

    Which engine owns a given ``{{ ... }}``, and whether a Django block hosts
    Citry content, are decided from the template itself. The one thing worth
    passing is ``tokenizer``, when something other than Django compiles your
    templates.
    """

    name = "citry_django"

    def __init__(self, *, tokenizer: Callable[[str], list[Any]] | None = None) -> None:
        # Every claim about where Django's syntax starts and stops is read with
        # this. Django's own lexer unless the template stack compiles templates
        # with something else, in which case the two have to agree.
        self.tokenizer = tokenizer or _django_lexer

    def on_template_foreign_spans(self, ctx: Any) -> ForeignSpanSet | None:
        """
        Claim every span Django owns, using Django's own lexer.

        This is the whole of the adapter's parsing: Django says where its
        syntax is, and Citry keeps it out of its grammar. `{{ ... }}` is
        claimed only when it is Django's (see `expressions.py`), because both
        engines spell interpolation the same way.
        """
        engine = get_django_engine().engine
        tokens = get_tokenizer()(ctx.content)
        libraries = _loaded_libraries(tokens)

        # An attribute value compiles as its own template with no `{% load %}`
        # of its own, so the enclosing template's are kept for it.
        loads = "".join(
            ctx.content[t.position[0] : t.position[1]]
            for t in tokens
            if t.token_type is TokenType.BLOCK and t.contents.split()[:1] == ["load"]
        )
        byte_offsets = _utf8_byte_offsets(ctx.content)
        spans: list[ForeignSpan] = []
        verbatim_from: int | None = None
        for token in tokens:
            command = token.contents.split()[:1] if token.token_type is TokenType.BLOCK else []

            # Claimed whole, body included: Django's lexer returns that body as
            # plain text, which Citry would otherwise parse.
            if command == ["verbatim"]:
                verbatim_from = token.position[0]
                continue
            if command == ["endverbatim"] and verbatim_from is not None:
                spans.append(
                    ForeignSpan(
                        byte_offsets[verbatim_from],
                        byte_offsets[token.position[1]],
                        may_control_body=True,
                    )
                )
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
            start, end = token.position
            spans.append(
                ForeignSpan(
                    byte_offsets[start],
                    byte_offsets[end],
                    may_control_body=token.token_type is TokenType.BLOCK,
                )
            )
        if not spans:
            return None
        return ForeignSpanSet(tuple(spans), provider_metadata={"loads": loads})

    def on_template_foreign_compiled(self, ctx: Any) -> list[Any] | None:
        metadata = ctx.provider_metadata if isinstance(ctx.provider_metadata, dict) else {}
        loads = "".join(
            node.text
            for node in ctx.nodes
            if isinstance(node, CitryForeignNode)
            if node.provider == self.name
            if node.text.lstrip("{% ").startswith("load")
        ) or metadata.get("loads", "")
        _resolve_foreign_attrs(ctx.nodes, loads, ctx.origin)
        result = _splice_body(ctx.nodes, loads, ctx.origin, ctx.compiled_body)
        ctx.mark_resolved(*ctx.claims)
        return result


def _utf8_byte_offsets(source: str) -> list[int]:
    """Map every Python character boundary to its UTF-8 byte offset."""
    offsets = [0]
    total = 0
    for character in source:
        total += len(character.encode("utf-8"))
        offsets.append(total)
    return offsets


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


def _resolve_foreign_attrs(body: list[Any], loads: str, origin: str) -> None:
    """Replace direct foreign component inputs with Django-rendered attrs."""
    for item in body:
        attrs = getattr(item, "attrs", None)
        if not isinstance(attrs, tuple):
            continue
        replaced = []
        changed = False
        for attr in attrs:
            if not isinstance(attr, CitryForeignHtmlAttr):
                replaced.append(attr)
                continue
            foreign_nodes = attr.foreign_nodes()
            if any(node.provider != CitryDjangoExtension.name for node in foreign_nodes):
                replaced.append(attr)
                continue
            source = "".join(
                part.text if isinstance(part, CitryForeignNode) else part for part in attr.parts
            )
            replaced.append(DjangoHtmlAttr(source, attr.position, attr.key, loads, origin))
            changed = True
        if changed:
            item.attrs = tuple(replaced)


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


def _emit_run(
    pieces: list[str],
    segments: list[CompiledBody],
    run: list[Any],
    compiled_body: Any,
) -> None:
    """Add one run of Citry content to the Django source being built."""
    equivalents = [_as_django_source(item) for item in run]
    if all(source is not None for source in equivalents):
        pieces.append("".join(cast("list[str]", equivalents)))
        return
    pieces.append(f"{{% citryseg {len(segments)} %}}")
    segments.append(compiled_body(run))


def _splice_body(body: list[Any], loads: str, origin: str, compiled_body: Any) -> list[Any]:
    """
    Replace a body containing Django tags with a single Django-driven node.

    The body already carries Django's tags as ForeignNode, in the order they
    were written, so the block structure can be rebuilt by handing Django's own
    parser a template made of those tags plus one marker per run of Citry
    content. Django decides what pairs with what; nothing here matches tags.
    """

    def is_owned(item: Any) -> bool:
        return isinstance(item, CitryForeignNode) and item.provider == CitryDjangoExtension.name

    if not any(is_owned(item) for item in body):
        return body

    # Alternating: Django source from the foreign tags, Citry runs in between.
    pieces: list[str] = []
    segments: list[CompiledBody] = []
    run: list[Any] = []
    for item in body:
        if is_owned(item):
            if run:
                _emit_run(pieces, segments, run, compiled_body)
                run = []
            pieces.append(item.text)
        else:
            run.append(item)
    if run:
        _emit_run(pieces, segments, run, compiled_body)

    return [ForeignNode("".join(pieces), segments, loads, origin)]
