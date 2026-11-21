"""Vue islands: the parts of a Django page that Citry hands to Vue.

An island is one Vue app on the page. Citry writes it as an element where Vue
mounts, followed by one configuration block and one start script. A region
of a Django template becomes an island when something in it needs Vue, and so
does each component that needs Vue inside a Django block of a component's
template (see `foreign.py`).

This module answers three questions for both places: does a render become
an island (Citry's `needs_browser_runtime()` decides), may the island stand
where the template put it, and may it be built with the configured asset
strategy. The last two are refusals: a Vue host inside a `<p>` or a
`<table>`, or an island written without its scripts, breaks in the browser
without any error, so citry-django raises instead.

Which components in Django blocks become islands is decided only once the
whole region has rendered, or, for a component rendered straight from
Python, once its root component has (see `PendingIslands`): a block cannot
see whether a component around it will be a Vue app.
"""

from __future__ import annotations

import json
import re
import warnings
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from weakref import WeakKeyDictionary

from citry import CitryRender, OutsideSlotContentError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.utils.html import escape

from .content import refused_content
from .events import partial_csp_nonce
from .page import placed
from .partials import PartialResponseWarning, is_partial
from .registry import deps_strategy, get_citry_app

try:
    from django.middleware.csp import get_nonce
except ImportError:  # Django 5.2 has no CSP middleware of its own.
    get_nonce = None

#: The element Vue mounts an island on. Only the placement check reads it,
#: to find where each host stands in the region's HTML.
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
    #: Inside a region: where the region's Django blocks wait for it to
    #: decide which of their components become islands.
    pending: PendingIslands | None = None


@dataclass(frozen=True)
class Candidate:
    """A component in a Django block that may become an island.

    While it is a candidate, an empty string stands in its place, so the
    question "does anything around it need Vue?" leaves it out.
    """

    holder: CitryRender
    index: int
    child: CitryRender

    def stand_aside(self) -> None:
        self.holder.parts[self.index] = ""

    def come_back(self) -> None:
        self.holder.parts[self.index] = self.child


class PendingIslands:
    """The Django blocks of one region, waiting for the region to finish.

    A component that needs Vue inside a Django block becomes its own island
    only when nothing around it is a Vue app already: an island inside
    another Vue app would be a second app inside the first. A block renders
    before the components around it have finished, so it cannot tell. It
    hands its render here instead, and the region decides once it has
    rendered completely (see `settle`). Without a region, as for a
    component rendered straight from Python or by a server event, its root
    component plays the region's part (see `pending_for_root`).
    """

    def __init__(self, options: IslandOptions | None = None) -> None:
        # Usually in the order the blocks finished, which puts a block inside
        # another block's component first; `settle` does not rely on it.
        self.blocks: list[CitryRender] = []
        # What the islands are built with, for a root component's blocks;
        # a region passes its own when it settles.
        self.options = options
        # Why the region became one Vue app although its blocks held
        # components that could have been islands, for the error message
        # when Citry then refuses the region.
        self.reason: str | None = None

    def add(self, block: CitryRender) -> None:
        self.blocks.append(block)

    def settle(self, region: CitryRender, *, csp_nonce: str | None, request: Any = None) -> bool:
        """Make islands of the components that can each be their own Vue app; say if any.

        Each component in a block that needs Vue on its own becomes a
        candidate. A candidate inside another candidate is not one, because
        it will be part of that component's app. Then:

        - When something else in the region still needs Vue, the region is
          one Vue app and holds every component in its blocks. Citry writes
          the Django HTML around them as static blocks, and refuses the
          ones it cannot (see `refused_content`).
        - Otherwise each candidate becomes its own island. When one holds
          slot content from outside it, it cannot stand alone, so the region
          becomes one Vue app instead, as above.
        """
        # A block the region does not hold, such as one under a marker that
        # a Django tag escaped, never reaches the page.
        reached = renders_in(region)
        candidates: list[Candidate] = []
        for block in self.blocks:
            if id(block) not in reached:
                continue
            for holder, index, child in vue_children(block):
                # A block inside a candidate is part of that candidate's app.
                if any(id(holder) in renders_in(other.child) for other in candidates):
                    continue
                # And a candidate inside `child` is part of child's app now.
                held = renders_in(child)
                inside = [candidate for candidate in candidates if id(candidate.holder) in held]
                for candidate in inside:
                    candidate.come_back()
                    candidates.remove(candidate)
                candidate = Candidate(holder, index, child)
                candidate.stand_aside()
                candidates.append(candidate)
        if not candidates:
            return False

        if not region.needs_browser_runtime():
            try:
                built = [
                    serialize_island(candidate.child, csp_nonce=csp_nonce, request=request)
                    for candidate in candidates
                ]
            except IslandSlotError as error:
                self.reason = str(error.reason)
            else:
                for candidate, html in zip(candidates, built, strict=True):
                    candidate.holder.parts[candidate.index] = html
                return True
        for candidate in candidates:
            candidate.come_back()
        return False


#: The Django blocks of a component tree rendered without a region, keyed by
#: its root component, until that root has rendered. A weak key, so a render
#: that fails before then leaves nothing behind.
ROOT_PENDING: WeakKeyDictionary[Any, PendingIslands] = WeakKeyDictionary()


def pending_for_root(root: Any, options: IslandOptions) -> PendingIslands:
    """Where a block outside any region waits for its root component to finish."""
    pending = ROOT_PENDING.get(root)
    if pending is None:
        pending = ROOT_PENDING[root] = PendingIslands(options)
    return pending


def settle_root(component: Any, rendered: Any) -> IslandOptions | None:
    """Decide the islands of a root component's blocks.

    Called once the root component has rendered, from citry-django's
    `on_component_rendered` hook, and its render plays the region's part.
    Returns the options the islands were built with, or None when none were,
    so the caller can do for them what a region does for its own.
    """
    pending = ROOT_PENDING.pop(component, None)
    if pending is None or not isinstance(rendered, CitryRender):
        return None
    options = pending.options or IslandOptions(csp_nonce=None)
    settled = pending.settle(rendered, csp_nonce=options.csp_nonce, request=options.request)
    return options if settled else None


def vue_children(render: CitryRender) -> Iterator[tuple[CitryRender, int, CitryRender]]:
    """Each component that needs Vue directly inside `render`, and where it stands.

    A `<c-if>` branch, a `<c-for>` body or a fill is not a component of its
    own, so the walk looks inside it. A component is not looked inside: if
    it needs Vue, all of it does.
    """
    for index, part in enumerate(render.parts):
        if not isinstance(part, CitryRender):
            continue
        if not part.is_component_root:
            yield from vue_children(part)
        elif part.needs_browser_runtime():
            yield render, index, part


def renders_in(render: CitryRender) -> set[int]:
    """The ids of `render` and of every render inside it."""
    found = {id(render)}
    for part in render.parts:
        if isinstance(part, CitryRender):
            found |= renders_in(part)
    return found


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
    return IslandOptions(
        csp_nonce=island_csp_nonce(request, request_csp_nonce(request)), request=request
    )


#: What an island's configuration block says about itself. Citry writes
#: `eventContext` and `eventBindings` for a component that has server events,
#: and for no other component.
PREPARED_PROTOCOL = re.compile(r'"protocol"\s*:\s*"citry-vue-prepared/1"')
EVENTS_MARK = re.compile(r'"(?:eventContext|eventBindings)"')


def holds_server_events(html: str) -> bool:
    """Whether an island's HTML has a component with server events.

    Reads the configuration block Citry wrote beside the island. When it
    cannot tell, because there is no block or it is a protocol this does not
    know, the answer is yes: asking for the token costs a cookie, and not
    asking costs a 403 on the first server event.
    """
    # Only the data blocks: an inlined runtime names the protocol too.
    blocks = [
        match.group("body")
        for match in SCRIPT.finditer(html)
        if "application/json" in match.group("attrs")
        and "citry-vue-prepared" in match.group("body")
    ]
    if not blocks:
        return True
    for body in blocks:
        if PREPARED_PROTOCOL.search(body) is None or EVENTS_MARK.search(body):
            return True
    return False


#: The request header an htmx request carries the nonce of the page it was sent from in.
PAGE_NONCE_HEADER = "X-Citry-Page-Nonce"

#: What a nonce looks like: base64 or base64url, which is what django-csp and
#: Django's CSP middleware write. Anything else in the header is ignored.
NONCE_SHAPE = re.compile(r"[A-Za-z0-9_+/=-]{8,128}")


def sent_page_nonce(request: Any) -> str | None:
    """The nonce the page itself sent with this request, if it did.

    `page_nonce_script` makes htmx send it. It is the right nonce even when the
    visitor has several tabs open, which a nonce kept in the session is not.
    A request can say anything here, but the nonce only ends up in that
    request's own response.
    """
    headers = getattr(request, "headers", None)
    value = None if headers is None else headers.get(PAGE_NONCE_HEADER)
    return value if isinstance(value, str) and NONCE_SHAPE.fullmatch(value) else None


def json_for_script(value: Any) -> str:
    """`value` as JSON that can stand inside a `<script>` element."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def page_nonce_script(request: Any, csp_nonce: str | None) -> str:
    """The script that makes htmx send this page's nonce with its requests, or "".

    An htmx response that holds an island lands in a page that is already
    loaded, and the runtime starts it only if it carries that page's nonce.
    The server cannot tell which page a request came from, so the page says.
    Only requests to the page's own origin carry it. Every island writes the
    same script, and the second one does nothing.

    A partial response is not a page and writes none: it lands in one.
    """
    if not csp_nonce or is_partial(request) or not isinstance(request, HttpRequest):
        return ""
    body = (
        "(function(n){if(window.__citryPageNonce)return;window.__citryPageNonce=1;"
        'document.addEventListener("htmx:configRequest",function(e){try{'
        "var u=new URL(e.detail.path,location.href);"
        f'if(u.origin===location.origin)e.detail.headers["{PAGE_NONCE_HEADER}"]=n'
        "}catch(x){}})})("
        f"{json_for_script(csp_nonce)});"
    )
    return f'<script nonce="{escape(csp_nonce)}">{body}</script>'


def with_page_scripts(html: str, request: Any, csp_nonce: str | None) -> str:
    """`html` for an island, with the scripts its page needs beside it."""
    return with_csrf(html, request, csp_nonce) + page_nonce_script(request, csp_nonce)


def with_csrf(html: str, request: Any, csp_nonce: str | None) -> str:
    """`html` for an island, after doing what its server events need from Django.

    Only an island with server events calls Django's CSRF check, so only it
    makes Django send the cookie (and the `Vary: Cookie` that comes with it),
    and only it needs `csrf_script`. A page of islands without events stays
    cacheable.
    """
    if not holds_server_events(html):
        return html
    ensure_csrf_cookie(request)
    return html + csrf_script(request, csp_nonce)


def ensure_csrf_cookie(request: Any) -> None:
    """Make Django send the CSRF cookie with the response that holds an island.

    Citry's Events calls pass Django's own CSRF check: the browser runtime
    reads the `csrftoken` cookie and sends it back as a header. A page with
    no form never asks Django for a token, so without this the cookie may be
    missing and the first call fails with a 403. Asking for the token is
    what `{% csrf_token %}` does too; the token itself is not written into
    the page, except where Django keeps it out of the cookie (see
    `csrf_script`). Called through `with_csrf`, for islands with server events.
    """
    if isinstance(request, HttpRequest):
        get_token(request)


#: What Django's CSRF settings are when a project has not changed them, and so
#: what Citry's browser runtime reads without being told.
DEFAULT_CSRF_COOKIE = "csrftoken"
DEFAULT_CSRF_HEADER = "HTTP_X_CSRFTOKEN"


def csrf_config(request: Any) -> dict[str, str] | None:
    """What Citry's runtime must be told about Django's CSRF token, or None.

    The runtime reads the `csrftoken` cookie and sends it as `X-CSRFToken`. A
    project that renames either, or keeps the token where a script cannot read
    it (`CSRF_USE_SESSIONS`, or a `CSRF_COOKIE_HTTPONLY` cookie), would get a
    403 on every server event. Then the runtime is given the header name and
    either the cookie's name or the token itself.
    """
    if not isinstance(request, HttpRequest):
        return None
    header = settings.CSRF_HEADER_NAME
    hidden = settings.CSRF_USE_SESSIONS or settings.CSRF_COOKIE_HTTPONLY
    if (
        not hidden
        and header == DEFAULT_CSRF_HEADER
        and settings.CSRF_COOKIE_NAME == DEFAULT_CSRF_COOKIE
    ):
        return None
    config: dict[str, str] = {}
    if header != DEFAULT_CSRF_HEADER:
        name = header.removeprefix("HTTP_").replace("_", "-")
        config["header"] = name
    if hidden:
        config["token"] = get_token(request)
    elif settings.CSRF_COOKIE_NAME != DEFAULT_CSRF_COOKIE:
        config["cookie"] = settings.CSRF_COOKIE_NAME
    return config


def csrf_script(request: Any, csp_nonce: str | None) -> str:
    """The script that tells Citry's runtime where Django's CSRF token is, or "".

    The runtime reads it when a server event is sent, not when it starts, so
    this only has to run once the runtime exists. It waits for it, up to five
    seconds, because the runtime's own tag may come after this one or load
    later, as it does in a fragment. Every island writes the same script, and
    a second `Citry.configure` replaces the first with the same values.
    """
    config = csrf_config(request)
    if config is None:
        return ""
    payload = json_for_script({"csrf": config})
    nonce = f' nonce="{escape(csp_nonce)}"' if csp_nonce else ""
    body = (
        "(function(c){var n=0;(function go(){var k=window.Citry;"
        "if(k&&k.configure){k.configure(c)}else if(n++<100){setTimeout(go,50)}})()})("
        f"{payload});"
    )
    return f"<script{nonce}>{body}</script>"


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


def island_csp_nonce(request: Any, nonce: str | None) -> str | None:
    """The nonce the islands of this response carry: `nonce`, unless it is a partial.

    A partial response lands in a page that is already loaded. The page says
    which one it is with a request header (see `page_nonce_script`), and that
    wins. Otherwise it is the nonce citry-django kept in the session when it
    rendered a page (see `events.partial_csp_nonce`), which is the last page
    the visitor loaded and so may be another tab's. Without either, `nonce`
    stands; under a nonce-based policy the browser runtime then refuses the
    island and says so in the console.
    """
    if is_partial(request):
        sent = sent_page_nonce(request)
        if sent is not None:
            return sent
        kept = partial_csp_nonce(get_citry_app(), request)
        if kept is not None:
            return kept
    return nonce


def island_strategy(request: Any) -> str:
    """The asset strategy an island in this response is written with.

    The configured strategy, except that an island in a partial response is
    a fragment when Citry's routes are mounted: Citry's `"document"` strategy
    expects the page around it, with the runtime and a start script that
    runs, and a partial has neither.
    """
    strategy = deps_strategy()
    if strategy != "document" or not is_partial(request):
        return strategy
    # A fragment loads the runtime and the island's files by URL, so Citry
    # needs its routes mounted. Without them the island stays a full-page
    # one, as before partials were recognised: htmx runs its inline scripts,
    # which works for a boosted page. Refusing would turn every htmx request
    # of such a project into an error.
    if get_citry_app().mounted_prefix is None:
        if settings.DEBUG:
            warnings.warn(
                "A component that needs Vue is part of a partial response (an htmx "
                "request, or a view that sets request.citry_partial = True), but "
                "Citry's routes are not mounted, so citry-django writes it for a "
                "whole page, which may not start once inserted. Add "
                'citry_django.urls to your URLconf (see "Citry\'s own routes" in '
                "the citry-django README).",
                PartialResponseWarning,
                stacklevel=2,
            )
        return strategy
    return "fragment"


class IslandSlotError(TypeError):
    """A component that needs Vue holds slot content written outside it."""

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        #: One sentence naming the component and why it cannot stand alone.
        self.reason = reason


def serialize_island(render: Any, *, csp_nonce: str | None, request: Any = None) -> str | None:
    """`render` serialized as its own island, or None when it needs no Vue.

    Used for a component inside a Django block, which has to stand on its own
    because the HTML around it is Django's. A component that needs no Vue is
    left to the enclosing serializer, which collects its assets with the rest
    of the page.
    """
    # Citry answers from the render alone, so a component that needs no Vue
    # costs no serialize here.
    if not render.needs_browser_runtime():
        return None
    strategy = island_strategy(request)
    refuse_strategy(strategy)
    try:
        html = serialized(render, strategy=strategy, csp_nonce=csp_nonce)
    except OutsideSlotContentError as error:
        name = type(render.context.component).__name__
        reason = (
            f"{name} needs Vue but cannot be its own Vue app, because it holds content that "
            "the component around it passed in."
        )
        raise IslandSlotError(outside_slot_message(render), reason) from error
    return with_page_scripts(html, request, csp_nonce)


def outside_slot_message(render: Any) -> str:
    name = type(render.context.component).__name__
    return (
        f"{name} needs Vue and stands inside a Django tag, so citry-django makes it its "
        "own Vue app. It also holds content that the component around it passed in "
        "(between its tags or in a <c-fill>), and Vue cannot own that content in a "
        f"separate app. Migrate that part to Citry: write the Django tag around {name} "
        "as <c-if> or <c-for>, so both components stay in one Vue app."
    )


def serialize_region(
    render: Any, *, csp_nonce: str | None, reason: str | None = None, request: Any = None
) -> tuple[str, bool]:
    """A region's output, and whether it is an island itself.

    `reason` says why the region is one Vue app although components in its
    Django blocks could have been islands; an error about the region names it.
    """
    island = render.needs_browser_runtime()
    # A region without Vue keeps the configured strategy in a partial too, so
    # the page still writes each of its tags once (see `page.placed`).
    strategy = island_strategy(request) if island else deps_strategy()
    # Under "simple" or "ignore" Citry would write the island without its
    # scripts, so it would do nothing in the browser.
    if island:
        refuse_strategy(strategy)
    html = serialized(render, strategy=strategy, csp_nonce=csp_nonce, reason=reason)
    return (with_page_scripts(html, request, csp_nonce) if island else html), island


def serialized(
    render: Any, *, strategy: str, csp_nonce: str | None, reason: str | None = None
) -> str:
    """`render`'s HTML, with its asset tags beside it for the page to collect.

    Citry hands the tags back apart from the HTML, so citry-django writes them
    itself (see `page.placed`). A fragment is the exception, and Citry refuses
    to hand its tags back: it carries no page tags, only a loader for the
    runtime and the island's data block, which have to stay beside its HTML
    because they work only once that HTML is in the page.
    """
    try:
        if strategy == "fragment":
            return render.serialize(deps_strategy=strategy, csp_nonce=csp_nonce)
        result = render.serialize_result(
            deps_strategy=strategy, deps_position="separate", csp_nonce=csp_nonce
        )
    except (TypeError, ValueError) as error:
        # Citry refuses Django output it cannot put inside a Vue app; say
        # what to change in the Django template instead.
        explained = refused_content(error, reason)
        if explained is None:
            raise
        raise explained from error
    return placed(result)


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
