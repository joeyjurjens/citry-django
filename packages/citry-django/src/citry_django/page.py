"""One page's Citry assets, written once and where the page wants them.

A Django template renders each `<c-*>` region on its own, and each region
that needs Vue becomes its own Vue app, an *island*. Citry hands a region's
asset tags back apart from its HTML, in three groups:

- the runtime group: Citry's browser runtime and its preload hints, the
  same for every island;
- the component group: component CSS and JavaScript and the files they
  depend on;
- the app group: one island's stylesheet, configuration block and start
  script.

A region writes each group between two comments of its own, CSS before the
region's HTML and JavaScript after it. The region's HTML then stands on its
own: a project may cache it or store it, and it still works on the page it
is rendered into.

When the outermost template has finished, the page reads those comments
back and hands each group to Citry's `combine_assets()`. That keeps one copy
of each runtime and component tag, and turns the stylesheet tags of several
islands that load the same file into one tag naming every island. The page
then moves the tags to the spot a `<c-css />` or `<c-js />` in the template
names. Without such a spot, each tag stays where its region left it. So a
page with several islands loads the runtime and each stylesheet once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from citry import SerializedAssets, combine_assets
from django.conf import settings

from .registry import get_citry_app

current_page: ContextVar[PageAssets | None] = ContextVar("citry_django_page", default=None)

#: What every comment this module writes begins with.
PREFIX = "citry-django"


class Assets(StrEnum):
    """Where a tag goes: CSS before a region's HTML, JavaScript after it."""

    CSS = "css"
    JS = "js"


class Group(StrEnum):
    """Which of Citry's groups a block of tags came from, in page order."""

    #: Citry's browser runtime. One copy per page.
    RUNTIME = "runtime"
    #: Component CSS and JavaScript. One copy per page, and the only group
    #: extensions see through `on_page_assets`.
    COMPONENT = "component"
    #: One island's own tags. Each configuration block and start script names
    #: its own app, so all of them are kept; islands share a stylesheet tag.
    APP = "app"

    @property
    def result_field(self) -> str:
        """The `SerializedRender` field Citry returns this group in."""
        return f"{self.value}_assets"


#: The role of the comment pair a `<c-css />` or `<c-js />` writes.
SLOT = "slot"

#: One delimited block: an opening comment that names the group, the tags,
#: and a closing comment. The content may not hold another opening comment,
#: so a stray opening comment cannot swallow the block after it.
BLOCK = re.compile(
    rf"<!--{PREFIX}:(?P<kind>css|js):(?P<role>runtime|component|app|{SLOT})-->"
    rf"(?P<content>(?:(?!<!--{PREFIX}:).)*?)"
    rf"<!--{PREFIX}:(?P=kind):end-->",
    re.DOTALL,
)

#: One asset tag inside such a block. Only ever read over markup Citry wrote.
TAG = re.compile(r"<(?P<name>script|style)\b[^>]*>.*?</(?P=name)>|<link\b[^>]*?>", re.DOTALL)


def opening(kind: Assets, role: str) -> str:
    return f"<!--{PREFIX}:{kind.value}:{role}-->"


def closing(kind: Assets) -> str:
    return f"<!--{PREFIX}:{kind.value}:end-->"


def delimited(kind: Assets, role: str, content: str) -> str:
    return f"{opening(kind, role)}{content}{closing(kind)}"


def placed(result: Any) -> str:
    """A region's or an island's HTML with its asset tags around it.

    `result` is what `serialize_result(deps_position="separate")` returned.
    CSS goes before the HTML and JavaScript after it, in Citry's order:
    runtime, then component, then app tags. While a page is open, each group
    sits between comments so the page can find it; without a page the tags
    are written as they are, and the HTML still works on its own.
    """
    page_open = current_page.get() is not None
    around: dict[Assets, list[str]] = {Assets.CSS: [], Assets.JS: []}
    for group in Group:
        assets = getattr(result, group.result_field)
        for kind in Assets:
            tags = "".join(getattr(assets, kind.value))
            if not tags:
                continue
            around[kind].append(delimited(kind, group.value, tags) if page_open else tags)
    return "".join(around[Assets.CSS]) + result.html + "".join(around[Assets.JS])


def slot(kind: Assets) -> str:
    """What a `<c-css />` or `<c-js />` in a Django template writes.

    An empty pair of comments that the page fills with every tag of that
    kind. Without a page there is nothing to fill it with.
    """
    return "" if current_page.get() is None else delimited(kind, SLOT, "")


class Block:
    """One delimited run of assets, as it sits in a finished page."""

    def __init__(self, match: re.Match) -> None:
        self.match = match
        self.kind = Assets(match.group("kind"))
        role = match.group("role")
        self.group = None if role == SLOT else Group(role)
        self.kept: list[str] = []
        self._tags: list[str] | None = None

    @property
    def is_slot(self) -> bool:
        return self.group is None

    def tags(self) -> list[str]:
        # Read once: the page asks for the same block's tags several times.
        if self._tags is None:
            self._tags = [match.group(0) for match in TAG.finditer(self.match.group("content"))]
        return self._tags

    def assets(self) -> SerializedAssets:
        """This block's tags, in the shape `combine_assets()` reads."""
        return SerializedAssets(**{self.kind.value: tuple(self.tags())})


class Placement:
    """Every asset a page's regions placed, put where the page wants them.

    Nothing here refers to the render that produced a block, so a region
    stored and rendered into a later page is read exactly as a fresh one.
    """

    def __init__(self, html: str) -> None:
        self.html = html
        self.blocks = [Block(match) for match in BLOCK.finditer(html)]

    def resolved(self) -> str:
        if not self.blocks:
            return self.html
        for kind in Assets:
            self.assign(kind)
        return self.rebuilt()

    def assign(self, kind: Assets) -> None:
        """Give every surviving tag of `kind` to the block that will carry it."""
        blocks = [block for block in self.blocks if block.kind is kind]
        survivors = {
            group: combined(kind, [block for block in blocks if block.group is group])
            for group in Group
        }

        # The first spot the template named takes every tag of this kind, in
        # Citry's order: runtime, then component, then app tags.
        slot = next((block for block in blocks if block.is_slot), None)
        if slot is not None:
            components = [tag for _, tag in survivors[Group.COMPONENT]]
            slot.kept = [
                *(tag for _, tag in survivors[Group.RUNTIME]),
                *rewritten(kind, components, collected=True),
                *(tag for _, tag in survivors[Group.APP]),
            ]
            return

        # Without a spot each tag stays in the block it came from, and an
        # extension sees the component tags block by block.
        for group in Group:
            for block, tag in survivors[group]:
                block.kept.append(tag)
        for block in blocks:
            if block.group is Group.COMPONENT:
                block.kept = list(rewritten(kind, block.kept, collected=False))

    def rebuilt(self) -> str:
        parts: list[str] = []
        cursor = 0
        for block in self.blocks:
            parts.append(self.html[cursor : block.match.start()])
            parts.append("".join(block.kept))
            cursor = block.match.end()
        parts.append(self.html[cursor:])
        return "".join(parts)


def combined(kind: Assets, blocks: list[Block]) -> list[tuple[Block, str]]:
    """The tags `combine_assets()` keeps for `blocks`, each with the block it came from.

    Citry keeps each tag where it first appears, so a kept tag belongs to the
    first block that held it. A stylesheet tag that several islands share is
    rewritten to name all of them, so it equals none of the tags it replaced;
    it belongs to the first block holding a tag that Citry folds into it.
    """
    if not blocks:
        return []
    kept = getattr(combine_assets(block.assets() for block in blocks), kind.value)
    exact = set(kept)
    supplied = {tag for block in blocks for tag in block.tags()}
    # Only the rewritten tags need the slower match below, and a page has one
    # per stylesheet file its islands share.
    rewritten_tags = [tag for tag in kept if tag not in supplied]
    owners: dict[str, Block] = {}
    for block in blocks:
        for tag in block.tags():
            owner = tag if tag in exact else folded_into(kind, tag, rewritten_tags)
            if owner is not None:
                owners.setdefault(owner, block)
    return [(owners[tag], tag) for tag in kept]


def folded_into(kind: Assets, tag: str, candidates: list[str]) -> str | None:
    """The candidate that Citry folds `tag` into, if any.

    Combining a tag with the tag that replaced it gives back that one tag,
    which is how this asks Citry rather than reading its attribute itself.
    """
    for candidate in candidates:
        both = SerializedAssets(**{kind.value: (candidate, tag)})
        if getattr(combine_assets([both]), kind.value) == (candidate,):
            return candidate
    return None


@dataclass(frozen=True)
class PageAsset:
    """Component tags of one kind, as the page is about to place them.

    ``collected`` says whether this is the whole page's worth: it is, when the
    host template named a spot for them and every component tag of this kind
    is on its way there. Without one they are still where each region put
    them, and an extension that would turn them into a single file has
    nowhere to put it.

    Only the component group reaches extensions. Citry's runtime checks the
    URL, `integrity` and app attributes of the runtime and app tags, so an
    extension that bundled those would break the islands.
    """

    kind: Assets
    tags: tuple[str, ...]
    collected: bool


def rewritten(kind: Assets, tags: Iterable[str], *, collected: bool) -> tuple[str, ...]:
    """`tags` as this engine's extensions would have them.

    A hook is a Citry hook, so an extension outside this package reaches it the
    same way: define ``on_page_assets`` and return the tags to place instead.
    """
    tags = tuple(tags)
    if not tags:
        return tags
    asset = PageAsset(kind=kind, tags=tags, collected=collected)
    return get_citry_app().extensions.emit("on_page_assets", asset, result="map", field="tags")


class PageAssets:
    """One page, and the Citry regions Django rendered into it.

    The page is a scope and holds nothing: while it is open a region delimits
    the assets Citry gave it, and closing the page reads those delimiters back.

    `CITRY_COLLECT_PAGE_ASSETS = False` turns it off, and every region writes
    its tags beside its own HTML.
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


def collected(html: str, page: PageAssets | None) -> Any:
    """`html` with `page`'s assets placed, or as it stands without a page."""
    return html if page is None else page.finish(html)
