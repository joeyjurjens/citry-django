from __future__ import annotations

import re
from functools import cache
from secrets import token_hex
from threading import RLock
from typing import Any

from citry import (
    CitryRender,
    CompiledBody,
)
from citry.nodes import HtmlAttr, Node
from django.template import Context
from django.template.base import Origin, Template, Variable, VariableDoesNotExist
from django.template.context import make_context
from django.template.exceptions import TemplateSyntaxError
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .engine import explain_tokenizer_disagreement, get_django_engine
from .expressions import is_dotted_path
from .nodes import CitryParser, CitrySegment
from .registry import get_tokenizer

SEGMENT_MARKER_LABEL = "CiTrY-SeGmEnT"

#: Any segment marker, whatever render produced it. Used to catch a marker that
#: outlived the render it belonged to, which a body-caching tag will do.
ANY_SEGMENT_MARKER = re.compile(
    rf"(?:<!--|&lt;!--){re.escape(SEGMENT_MARKER_LABEL)}:(?P<nonce>[0-9a-f]+):\d+(?:-->|--&gt;)"
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
        return self.marker(index)

    def marker(self, index: int) -> str:
        return f"<!--{SEGMENT_MARKER_LABEL}:{self.nonce}:{index}-->"

    def restore(self, html: str) -> CitryRender:
        """Replace Django's intact markers with their structured renders."""
        raw_prefix = f"<!--{SEGMENT_MARKER_LABEL}:{self.nonce}:"
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

        self.reject_stale_markers(html)

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

    def reject_stale_markers(self, html: str) -> None:
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
            for match in ANY_SEGMENT_MARKER.finditer(html)
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


class ForeignNode(Node):
    """
    A Django block whose interior is Citry's, at render time.

    Django drives: it selects branches, orders them and repeats them, and asks back
    only for the runs of Citry content it actually reaches. Each run hands Django an
    inert marker and keeps its structured ``CitryRender`` aside, so once Django has
    finished the markers are swapped back and the enclosing serializer sees one
    tree. A tag that alters or discards a reached marker fails loudly.

    A Django block whose interior is Citry's, driven by Django.
    """

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

    def django_template(self) -> Any:
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
                    raise explain_tokenizer_disagreement(exc) from exc
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
        carrier = self.django_template()
        # `push_state` as well as `bind_template`: rendering the nodelist
        # directly skips `Template._render`, which is what would otherwise set
        # `render_context.template`. Django's debug error path reads that to
        # decide whether it may annotate an exception, and on None it raises
        # from inside its own handler, replacing whatever went wrong in the
        # block with `'NoneType' object has no attribute 'origin'`. Not
        # isolated: the host's render context still belongs to the host.
        with (
            django_context.bind_template(carrier),
            django_context.render_context.push_state(carrier, isolated_context=False),
        ):
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
        carrier = self.django_template()
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
        path = self.lone_path()
        if path is not None:
            root, _, rest = path.partition(".")
            value = context.variables.get(root)
            return django_lookup(value, rest) if rest else value
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

    def lone_path(self) -> str | None:
        """The dotted path this attribute is, when that is all it is.

        `image="{{ product.image }}"` means the image, not a rendering of it,
        so such a value resolves to the object. Anything else - a tag, a
        filter, text beside the interpolation - can only be a string.
        """
        match = LONE_INTERPOLATION.match(self.source)
        if match is None:
            return None
        expression = match.group("expression").strip()
        return expression if is_dotted_path(expression) or expression.isidentifier() else None


#: The value is one interpolation and nothing else.
LONE_INTERPOLATION = re.compile(r"^\s*\{\{(?P<expression>.*?)\}\}\s*$", re.S)

#: The name the resolved root is bound to while Django walks the rest of the
#: path. Never seen by a template; it only has to be a legal Django variable.
LOOKUP_ROOT = "root"


def django_lookup(root: object, path: str) -> object:
    """`path` resolved off `root` the way a Django template resolves it.

    Django's own ``Variable`` does the walking, so the rules are not restated
    here and do not drift: dictionary key, then attribute, then numeric index,
    calling what it finds unless that is marked ``do_not_call_in_templates`` or
    ``alters_data``.

    A name that is not there is the engine's ``string_if_invalid``, empty by
    default, which is what the same path would render in a Django template.
    Citry treats an absent name as an error and this does not, deliberately:
    the point of writing ``{{ }}`` is that the path means what it means in
    Django, and half of Django's rule would be the worst of both.
    """
    engine = carrier().engine
    context = Context({LOOKUP_ROOT: root})
    # `alters_data` is answered with the engine's `string_if_invalid`, which
    # Django reads off the bound template. Binding an empty one keeps that
    # branch on Django's answer rather than a crash or an invention here.
    with context.bind_template(carrier()):
        try:
            return Variable(f"{LOOKUP_ROOT}.{path}").resolve(context)
        except VariableDoesNotExist:
            return engine.string_if_invalid


@cache
def carrier() -> Template:
    """An empty template, for the engine settings a lookup may consult."""
    return Template("", engine=get_django_engine().engine)
