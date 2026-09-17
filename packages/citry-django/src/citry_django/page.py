from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from citry.assets import dedupe
from django.conf import settings

from .compat import StrEnum
from .registry import get_citry_app

current_page: ContextVar[PageAssets | None] = ContextVar("citry_django_page", default=None)

#: What every comment this module writes begins with.
PREFIX = "citry-django"


class Assets(StrEnum):
    """The two groups Citry places, and Citry's own name for each."""

    CSS = "css"
    JS = "js"

    @property
    def placeholder(self) -> str:
        """Citry's placeholder for this group, which its render fills."""
        return f"<c-{self.value} />"

    @property
    def anchor(self) -> str:
        """The closing tag Citry's own placement puts this group before."""
        return "</head>" if self is Assets.CSS else "</body>"

    @property
    def trailing(self) -> bool:
        """Whether this group goes after a region rather than before it."""
        return self is Assets.JS


class Role(StrEnum):
    """What one delimited block is for."""

    #: What a region collected, waiting where the region left it.
    REGION = "region"
    #: Where the page wants them, written as `<c-css />` in a host template.
    SLOT = "slot"


#: One delimited block, opened by its role and closed by kind alone.
BLOCK = re.compile(
    rf"<!--{PREFIX}:(?P<kind>css|js):(?P<role>region|slot)-->"
    rf"(?P<content>.*?)"
    rf"<!--{PREFIX}:(?P=kind):end-->",
    re.DOTALL,
)

#: One asset tag inside such a block. Only ever read over markup Citry wrote.
TAG = re.compile(r"<(?P<name>script|style)\b[^>]*>.*?</(?P=name)>|<link\b[^>]*?>", re.DOTALL)

#: A `<c-css />` or `<c-js />` a host template wrote for itself.
PLACEHOLDER = re.compile(r"<c-(?P<kind>css|js)\b[^>]*?>")


def opening(kind: Assets, role: Role) -> str:
    return f"<!--{PREFIX}:{kind.value}:{role.value}-->"


def closing(kind: Assets) -> str:
    return f"<!--{PREFIX}:{kind.value}:end-->"


def delimited(kind: Assets, role: Role, content: str) -> str:
    return f"{opening(kind, role)}{content}{closing(kind)}"


class RegionSource:
    """One region's source, with a delimited spot for each group of assets.

    Citry fills `<c-css />` and `<c-js />` with what the render collected, so a
    placeholder between two comments is what lets the page find those tags
    again without reading them. That matters: what Citry emits depends on the
    request nonce and on the security policy in force, and a page that matched
    the tags it expected would stop matching the moment either is set.

    Where the spot goes is Citry's own rule, so nothing moves by adding it: the
    host's own placeholder if it wrote one, else before `</head>` or `</body>`,
    else around the region.
    """

    def __init__(self, source: str) -> None:
        self.source = source

    def prepared(self) -> str:
        source = self.source
        for kind in Assets:
            source = self.spotted(source, kind)
        return source

    def spotted(self, source: str, kind: Assets) -> str:
        own = self.host_placeholder(source, kind)
        if own is not None:
            return source.replace(own, delimited(kind, Role.SLOT, own), 1)
        spot = delimited(kind, Role.REGION, kind.placeholder)
        if kind.anchor in source:
            return source.replace(kind.anchor, spot + kind.anchor, 1)
        return source + spot if kind.trailing else spot + source

    @staticmethod
    def host_placeholder(source: str, kind: Assets) -> str | None:
        """The `<c-css />` this source wrote itself, if it wrote one."""
        for match in PLACEHOLDER.finditer(source):
            if match.group("kind") == kind.value:
                return match.group(0)
        return None


class Block:
    """One delimited run of assets, as it sits in a finished page."""

    def __init__(self, match: re.Match) -> None:
        self.match = match
        self.kind = Assets(match.group("kind"))
        self.role = Role(match.group("role"))
        self.kept: list[str] = []

    @property
    def is_slot(self) -> bool:
        return self.role is Role.SLOT

    def tags(self) -> list[str]:
        return [match.group(0) for match in TAG.finditer(self.match.group("content"))]


class Placement:
    """Every asset a page's regions placed, put where the page wants them.

    A region delimits what Citry gave it and keeps it, so its markup stays
    complete: a host may store that markup, cache it, and render it into a
    later page, and this reads the stored copy exactly as it reads a fresh one.
    Nothing here refers to the render that produced it.

    Three things happen. An asset a page has already placed is dropped, which
    is what takes the client runtime from one copy per region down to one per
    page. When a host template wrote `<c-css />` or `<c-js />`, everything of
    that group moves there; without one, each group stays where Citry put it.
    And every extension gets the group as a whole, through `on_page_assets`,
    which is where one page's worth of assets can become one file.
    """

    def __init__(self, html: str) -> None:
        self.html = html
        self.blocks = [Block(match) for match in BLOCK.finditer(html)]

    def resolved(self) -> str:
        if not self.blocks:
            return self.html
        self.assign()
        return self.rebuilt()

    def assign(self) -> None:
        """Give every distinct tag to the one block that will carry it.

        Which tags survive is Citry's own rule, `citry.assets.dedupe`: equal
        tags are one tag, and the first one seen is the one kept. Walking the
        blocks afterwards is only about *where* each survivor goes.
        """
        slots = {block.kind: block for block in reversed(self.blocks) if block.is_slot}
        surviving = [list(dedupe(self.tags(kind))) for kind in Assets]
        remaining = dict(zip(Assets, surviving, strict=True))
        for block in self.blocks:
            for tag in block.tags():
                if tag not in remaining[block.kind]:
                    continue
                remaining[block.kind].remove(tag)
                slots.get(block.kind, block).kept.append(tag)
        for block in self.blocks:
            block.kept = list(rewritten(block.kind, block.kept, collected=block.is_slot))

    def tags(self, kind: Assets) -> list[str]:
        """Every tag of one group, in the order the page holds them."""
        return [tag for block in self.blocks if block.kind is kind for tag in block.tags()]

    def rebuilt(self) -> str:
        parts: list[str] = []
        cursor = 0
        for block in self.blocks:
            parts.append(self.html[cursor : block.match.start()])
            parts.append("".join(block.kept))
            cursor = block.match.end()
        parts.append(self.html[cursor:])
        return "".join(parts)


@dataclass(frozen=True)
class PageAsset:
    """One group of assets, as the page is about to place them.

    ``collected`` says whether this is the whole page's worth: it is, when the
    host template named a spot for them and everything of this group is on its
    way there. Without one they are still where Citry put them, several tags in
    several places, and an extension that would turn them into a single file
    has nowhere to put it.
    """

    kind: Assets
    tags: tuple[str, ...]
    collected: bool


def rewritten(kind: Assets, tags: list[str], *, collected: bool) -> tuple[str, ...]:
    """`tags` as this engine's extensions would have them.

    A hook is a Citry hook, so an extension outside this package reaches it the
    same way: define ``on_page_assets`` and return the tags to place instead.
    """
    asset = PageAsset(kind=kind, tags=tuple(tags), collected=collected)
    return get_citry_app().extensions.emit("on_page_assets", asset, result="map", field="tags")


class PageAssets:
    """One page, and the Citry regions Django rendered into it.

    A Django template renders each `<c-*>` region on its own, and Citry places
    a region's assets when that region is serialized. That gave one `<style>`
    beside every component and the client runtime once per region, with no way
    to say the tags belong in the head.

    The page is a scope and holds nothing: while it is open a region delimits
    the assets Citry gave it, and closing the page reads those delimiters back.
    A region that keeps its own assets is a region whose markup stands on its
    own, which is what a host storing rendered HTML needs of it.

    `CITRY_COLLECT_PAGE_ASSETS = False` turns it off, and every region places
    what it asked for the way Citry would on its own.
    """

    @classmethod
    def open(cls) -> PageAssets | None:
        """Start a page, unless an enclosing render already did.

        Returns the page to close, or None when this render is nested in one:
        an `{% include %}` renders through the same backend, and only the
        outermost render is the page.
        """
        if not getattr(settings, "CITRY_COLLECT_PAGE_ASSETS", True):
            return None
        if current_page.get() is not None:
            return None
        page = cls()
        current_page.set(page)
        return page

    def close(self) -> None:
        current_page.set(None)

    def finish(self, html: str) -> str:
        return Placement(html).resolved()


def prepared(source: str) -> str:
    """`source` with a delimited spot for its assets, when a page is open."""
    return source if current_page.get() is None else RegionSource(source).prepared()


def collected(html: str, page: PageAssets | None) -> Any:
    """`html` with `page`'s assets placed, or as it stands without a page."""
    return html if page is None else page.finish(html)
