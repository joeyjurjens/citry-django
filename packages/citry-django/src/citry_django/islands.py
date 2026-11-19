"""Vue islands: the parts of a Django page that Citry hands to Vue.

An island is one Vue app on the page. Citry writes it as an element where Vue
mounts, followed by one configuration block and one start script. A region
of a Django template becomes an island when something in it needs Vue, and so
does each component that needs Vue inside a Django block of a component's
template (see `foreign.py`).

This module answers three questions for both places: did a serialize produce
an island, may the island stand where the template put it, and may it be
built with the configured asset strategy. The last two are refusals: a Vue
host inside a `<p>` or a `<table>`, or an island written without its
scripts, breaks in the browser without any error, so citry-django raises
instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from citry import CitryRender
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.utils.html import escape

from .registry import deps_strategy

try:
    from django.middleware.csp import get_nonce
except ImportError:  # Django 5.2 has no CSP middleware of its own.
    get_nonce = None

# TODO(C2): once Citry has a public check of whether a render needs its
# browser runtime, ask it and delete this pattern. Until then the mount
# element is the only public sign of an island: the
# `CitryRender.serialize()` docstring says Citry puts the rendered content "in
# one element where Vue mounts", and this is how 1.0.3 writes that element.
VUE_HOST = re.compile(r'<div id="citry-vue-(?P<app>[0-9a-f]+)"')

#: A script element, which escaped data can never write. Under the
#: "document" strategy Citry names the app id in the configuration block's
#: opening tag; under "fragment", only as `"appId"` in its JSON.
SCRIPT = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.S | re.I)
SCRIPT_APP_ATTR = re.compile(r'="([0-9a-f]+)"')
SCRIPT_APP_JSON = re.compile(r'"appId":"([0-9a-f]+)"')

#: The `CITRY_DEPS_STRATEGY` values that write an island's scripts. The others
#: write the HTML alone, and the interactive part then silently does nothing.
ISLAND_STRATEGIES = frozenset({"document", "fragment"})


#: The provide key a region passes its island options down under. Read only by
#: `foreign.py`, so components never need to know it.
ISLANDS_PROVIDE = "citry_django_islands"


class IslandStrategyError(ImproperlyConfigured):
    """An island would be written without the scripts that make it work."""


class IslandPlacementError(ValueError):
    """An island would stand where the browser moves or drops its element."""


@dataclass(frozen=True)
class IslandOptions:
    """What a region knows that the islands inside its components need.

    A component's template has no Django context, so a region hands these
    down through a provide. Each island inside the region is then built
    with the same CSP nonce as the region itself, which the browser runtime
    requires of every app on one page.
    """

    csp_nonce: str | None
    request: Any = None


def island_ids(html: str) -> set[str]:
    """The app ids of the Vue apps in serialized output.

    A host element counts only when a script element names its app id too.
    A component may write `id="citry-vue-..."` from data, which Django or
    Citry escapes as a value, but data cannot write a `<script>` element.
    """
    hosts = {match.group("app") for match in VUE_HOST.finditer(html)}
    if not hosts:
        return set()
    named: set[str] = set()
    for match in SCRIPT.finditer(html):
        named.update(SCRIPT_APP_ATTR.findall(match.group("attrs")))
        named.update(SCRIPT_APP_JSON.findall(match.group("body")))
    return hosts & named


def has_island(html: str) -> bool:
    """Whether serialized output holds a Vue app."""
    return bool(island_ids(html))


def island_options(citry_context: Any) -> IslandOptions:
    """The options the enclosing region provided, or what the render itself knows.

    A component rendered directly, outside any Django template, has no region
    above it. Its request, when a caller passed one as a render global, still
    names the nonce.
    """
    provided = citry_context.provides.get(ISLANDS_PROVIDE)
    if isinstance(provided, IslandOptions):
        return provided
    request = citry_context.variables.get("request")
    return IslandOptions(csp_nonce=request_csp_nonce(request), request=request)


def ensure_csrf_cookie(request: Any) -> None:
    """Make Django send the CSRF cookie with the response that holds an island.

    Citry's Events calls pass Django's own CSRF check: the browser runtime
    reads the `csrftoken` cookie and sends it back as a header. A page with
    no form never asks Django for a token, so without this the cookie may be
    missing and the first call fails with a 403. Asking for the token is
    what `{% csrf_token %}` does too; the token itself is not written into
    the page.

    TODO(C2): ask only for islands that hold an Events component, once Citry
    can tell which ones do. Until then every island asks.

    TODO: the browser runtime reads the default cookie and header names. A
    project with CSRF_USE_SESSIONS, CSRF_COOKIE_HTTPONLY, or a custom
    CSRF_COOKIE_NAME or CSRF_HEADER_NAME needs a matching runtime
    configuration, which citry-django does not write yet.
    """
    if isinstance(request, HttpRequest):
        get_token(request)


def request_csp_nonce(request: Any) -> str | None:
    """The CSP nonce a CSP package put on the request, if any did.

    django-csp sets `request.csp_nonce`. Django's own CSP middleware (6.0 and
    later) keeps it where `django.middleware.csp.get_nonce` reads it.
    """
    if request is None:
        return None
    nonce = getattr(request, "csp_nonce", None)
    if nonce is None and get_nonce is not None:
        nonce = get_nonce(request)
    return None if nonce is None else str(nonce)


class IslandHtml(str):
    """A finished island's HTML, standing in a render's parts.

    A plain `str` to Citry. The type lets a Django block further out see that
    a component already holds finished islands, so it does not turn that
    whole component into an island again.
    """

    __slots__ = ()


def finished_islands(render: Any) -> set[str]:
    """The app ids of the finished islands anywhere inside `render`."""
    found: set[str] = set()
    for part in render.parts:
        if isinstance(part, IslandHtml):
            found |= island_ids(part)
        elif isinstance(part, CitryRender):
            found |= finished_islands(part)
    return found


def serialize_island(render: Any, *, csp_nonce: str | None) -> IslandHtml | None:
    """`render` serialized as its own island, or None when it needs no Vue.

    Used for a component inside a Django block, which has to stand on its own
    because the HTML around it is Django's. A component that needs no Vue is
    left to the enclosing serializer, which collects its assets with the rest
    of the page, so the serialize done here to find out is discarded.
    """
    strategy = deps_strategy()
    # Under "simple" or "ignore" Citry writes no host at all, so the only way
    # to see that the render needed one is to ask for the scripts.
    html = render.serialize(
        deps_strategy=strategy if strategy in ISLAND_STRATEGIES else "document",
        csp_nonce=csp_nonce,
    )
    # Islands an inner Django block already finished are copied into this
    # output as they stand. Only an app this serialize created makes the
    # component an island; otherwise it stays live, and its own assets are
    # collected with the page.
    if not island_ids(html) - finished_islands(render):
        return None
    refuse_strategy(strategy)
    return IslandHtml(html)


def serialize_region(render: Any, *, csp_nonce: str | None) -> tuple[str, bool]:
    """A region's output, and whether it holds an island.

    The region is serialized once, as before. Only under a strategy that
    writes no scripts does a second serialize run, to find out whether the
    region needed them.
    """
    strategy = deps_strategy()
    html = render.serialize(deps_strategy=strategy, csp_nonce=csp_nonce)
    if strategy in ISLAND_STRATEGIES:
        return html, has_island(html)
    if has_island(render.serialize(deps_strategy="document", csp_nonce=csp_nonce)):
        refuse_strategy(strategy)
    return html, False


def refuse_strategy(strategy: str) -> None:
    """Raise when the configured strategy would write an island without scripts."""
    if strategy in ISLAND_STRATEGIES:
        return
    msg = (
        f'CITRY_DEPS_STRATEGY = "{strategy}" writes this component without the scripts '
        "Vue needs, so its interactive part would do nothing in the browser. Set "
        'CITRY_DEPS_STRATEGY to "document" (the default), or remove the setting.'
    )
    raise IslandStrategyError(msg)


# --- Where a Vue host may stand ------------------------------------------------
#
# Vue mounts on a `<div>`. The browser's HTML parser closes a `<p>` before a
# `<div>`, moves a `<div>` out of a table that is not inside a cell, drops one
# inside a `<select>`, and leaves SVG or MathML for it. The page then shows
# the island somewhere else, or not at all, and nothing reports an error. The
# scanner below tracks which elements are open the way the parser would, for
# the cases that decide this, and is not a general HTML parser.

#: Elements that hold no content and are never closed.
VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "keygen",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

#: Elements whose content is text, so a `<div` inside them is not a tag.
RAW_TEXT = frozenset(
    {"script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes"}
)

#: Start tags that close an open `<p>` first.
CLOSES_P = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "center",
        "dd",
        "details",
        "dialog",
        "dir",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "li",
        "listing",
        "main",
        "menu",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "ul",
        "xmp",
    }
)

#: Elements that stop the parser looking further up for an open `<p>`.
P_SCOPE_LIMITS = frozenset(
    {
        "applet",
        "button",
        "caption",
        "html",
        "marquee",
        "object",
        "table",
        "td",
        "template",
        "th",
        # SVG and MathML elements that hold HTML again.
        "annotation-xml",
        "desc",
        "foreignobject",
        "mi",
        "mn",
        "mo",
        "ms",
        "mtext",
    }
)

#: Table parts whose direct content the parser moves out of the table.
TABLE_PARTS = frozenset({"colgroup", "table", "tbody", "tfoot", "thead", "tr"})

#: Elements inside SVG or MathML whose content is HTML again.
HTML_INSIDE_FOREIGN = frozenset(
    {"annotation-xml", "desc", "foreignobject", "mi", "mn", "mo", "ms", "mtext", "title"}
)

#: One comment or one tag, attributes quote-aware.
TOKEN = re.compile(
    r"<!--.*?(?:-->|\Z)"
    r"|<(?P<end>/?)(?P<name>[A-Za-z][A-Za-z0-9:_.-]*)"
    r"(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)>",
    re.S,
)


@dataclass(frozen=True)
class Tag:
    name: str
    is_end: bool
    attrs: str
    start: int


def tags(markup: str) -> Iterator[Tag]:
    """Every tag in `markup`, skipping comments and the text of raw-text elements."""
    # Lowered once: a page with many islands has many raw-text elements, and
    # lowering the whole page for each of them made the scan quadratic.
    lowered = markup.lower()
    position = 0
    while True:
        match = TOKEN.search(markup, position)
        if match is None:
            return
        position = match.end()
        name = match.group("name")
        if name is None:  # A comment.
            continue
        tag = Tag(name.lower(), bool(match.group("end")), match.group("attrs"), match.start())
        yield tag
        if not tag.is_end and tag.name in RAW_TEXT:
            close = lowered.find(f"</{tag.name}", position)
            if close < 0:
                return
            position = close


class OpenElements:
    """The elements open at some point of a page, as the browser counts them."""

    def __init__(self, names: Iterable[str] = ()) -> None:
        self.stack = list(names)

    def feed(self, markup: str) -> None:
        for tag in tags(markup):
            self.apply(tag)

    def apply(self, tag: Tag) -> None:
        if tag.is_end:
            if tag.name in self.stack:
                self.pop_through(tag.name)
            return
        self.close_implied(tag.name)
        if tag.name not in VOID and not tag.attrs.rstrip().endswith("/"):
            self.stack.append(tag.name)

    def close_implied(self, name: str) -> None:
        """Close what the parser closes on its own before `name` opens."""
        if name in CLOSES_P and self.p_in_scope():
            self.pop_through("p")
        if name == "li":
            self.pop_nearest({"li"}, limits={"ol", "ul"})
        elif name in {"dd", "dt"}:
            self.pop_nearest({"dd", "dt"}, limits={"dl"})
        elif name in {"td", "th"}:
            self.pop_nearest({"td", "th"}, limits={"tr", "table"})
        elif name == "tr":
            self.pop_nearest({"tr"}, limits={"tbody", "thead", "tfoot", "table"})
        elif name in {"tbody", "thead", "tfoot"}:
            self.pop_nearest({"tbody", "thead", "tfoot"}, limits={"table"})
        elif name in {"option", "optgroup"}:
            self.pop_nearest({"option"} if name == "option" else {"option", "optgroup"}, set())

    def pop_nearest(self, names: set[str], limits: set[str]) -> None:
        """Pop through the nearest of `names`, unless one of `limits` comes first."""
        for index in range(len(self.stack) - 1, -1, -1):
            current = self.stack[index]
            if current in names:
                del self.stack[index:]
                return
            if current in limits or current in P_SCOPE_LIMITS:
                return

    def pop_through(self, name: str) -> None:
        index = len(self.stack) - 1 - self.stack[::-1].index(name)
        del self.stack[index:]

    def p_in_scope(self) -> bool:
        for current in reversed(self.stack):
            if current == "p":
                return True
            if current in P_SCOPE_LIMITS:
                return False
        return False

    def refused_parent(self) -> str | None:
        """The open element that would move or drop a `<div>` placed here."""
        if self.p_in_scope():
            return "p"
        if self.stack and self.stack[-1] in TABLE_PARTS:
            return self.stack[-1]
        if "select" in self.stack:
            return "select"
        for current in reversed(self.stack):
            if current in HTML_INSIDE_FOREIGN:
                break
            if current in {"svg", "math"}:
                return current
        return None


def refuse_misplaced_islands(html: str, *, open_elements: Iterable[str], origin: str) -> None:
    """Raise when a Vue host in `html` stands where the browser would move it.

    `open_elements` are the elements open where `html` goes, outermost first,
    as the Django template around a region left them.
    """
    apps = island_ids(html)
    if not apps:
        return
    state = OpenElements(open_elements)
    for tag in tags(html):
        host = VUE_HOST.match(f"<div{tag.attrs}") if tag.name == "div" else None
        if not tag.is_end and host is not None and host.group("app") in apps:
            parent = state.refused_parent()
            if parent is not None:
                raise IslandPlacementError(placement_message(parent, origin))
        state.apply(tag)


def placement_message(parent: str, origin: str) -> str:
    return (
        f"In {origin}, a Citry component that needs Vue stands inside <{escape(parent)}>. "
        "Vue mounts it on a <div>, and the browser moves or drops a <div> placed there, "
        "so the component would show up in the wrong place or not at all. Move the "
        f"<{escape(parent)}> into the component's own template, or move the component "
        f"out of the <{escape(parent)}>."
    )
