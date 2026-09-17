from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import PurePosixPath
from typing import Any

from citry.ext.dependencies import Script, Style
from citry.extension import Extension
from compressor.cache import cache_get, cache_set, get_templatetag_cachekey
from compressor.css import CssCompressor
from compressor.js import JsCompressor
from django.conf import settings

from citry_django.compat import StrEnum
from citry_django.page import current_page

__all__ = ["CitryCompressorExtension"]


class Kind(StrEnum):
    """The two groups django-compressor keeps apart."""

    CSS = "css"
    JS = "js"


#: Marks a tag the page may still bundle with the rest of its group. Written
#: only while a page is collecting, and gone by the time the page is finished:
#: either the tag was bundled into one that does not carry it, or the mark is
#: taken off again.
BUNDLE_ATTR = "data-citry-bundle"

#: The kinds that are the same on every page placing the component, and so are
#: worth bundling. ``core`` is the client runtime a component registers against
#: and ``variables`` is one instance's own ``js_data``, whose payload would
#: otherwise land in a file meant to be shared between pages.
BUNDLED_KINDS = frozenset({"component", "extra", "file"})


@dataclass(frozen=True)
class Asset:
    """One asset django-compressor produced: a file it wrote, or content."""

    attrs: dict[str, Any] = field(default_factory=dict)
    url: str | None = None
    content: str | None = None

    def as_dependency(self, build: Any) -> Any:
        if self.url is not None:
            return build(url=self.url, attrs=self.attrs)
        return build(content=self.content, attrs=self.attrs)


class Collecting:
    """django-compressor's own pipeline, read as values rather than as tags.

    It answers in HTML: ``output()`` ends by rendering ``compressor/css_file.html``
    with the URL of the file it wrote. One step earlier that URL is still a
    value, and this reads it there. The template is rendered as well, so
    ``post_compress`` still fires for a project listening to it, and nothing
    about how compressing works is reimplemented here.

    Grouping is the reason this reads a list. A stylesheet's ``media`` and a
    script's ``async`` cannot be bundled across, so django-compressor splits
    those into separate nodes, each rendering its own tag, and each node shares
    the one ``context`` its parent was built with.
    """

    #: Where the values are kept, in the context django-compressor shares
    #: between a compressor and the per-group nodes it copies from itself.
    SINK = "citry_django_compressor"

    @classmethod
    def over(cls, kind: str, content: str) -> Collecting:
        """One compressor whose per-group nodes report back to it.

        The sink goes in before there is anything to put in it, because
        ``Compressor.__init__`` keeps ``context or {}``: an empty one is
        falsy, so a node copied from this compressor would be handed a
        dictionary of its own and report into nothing.
        """
        return cls(kind, content=content, context={cls.SINK: []})

    def render_output(self, mode: str, context: dict | None = None) -> str:
        self.context[self.SINK].append({**(context or {}), **self.extra_context})
        return super().render_output(mode, context)

    def assets(self, mode: str = "file", forced: bool = False) -> list[Asset]:
        self.output(mode=mode, forced=forced)
        return [
            Asset(
                url=values.get("url"), content=values.get("content"), attrs=self.attrs_for(values)
            )
            for values in self.context[self.SINK]
        ]

    @staticmethod
    def attrs_for(values: dict) -> dict[str, Any]:
        raise NotImplementedError


class CollectingCss(Collecting, CssCompressor):
    @staticmethod
    def attrs_for(values: dict) -> dict[str, Any]:
        media = values.get("media")
        return {"media": media} if media else {}


class CollectingJs(Collecting, JsCompressor):
    @staticmethod
    def attrs_for(values: dict) -> dict[str, Any]:
        #: django-compressor keeps these as the string it would put in the tag.
        extra = (values.get("extra") or "").strip()
        return {extra: True} if extra else {}


#: What each group is compressed with, and what its results are built as.
GROUPS: dict[Kind, tuple[type[Collecting], Any]] = {
    Kind.CSS: (CollectingCss, Style),
    Kind.JS: (CollectingJs, partial(Script, wrap=False)),
}


class Compression:
    """django-compressor, handed assets and read back as assets.

    Everything this knows is django-compressor's: what it can read, what it
    does with it, and where its answer is a value rather than a tag. What is
    worth handing over in the first place is Citry's question, and belongs to
    the extension below.

    Both ways in end up at the same call. ``dependencies`` is for a render,
    where Citry has objects; ``tags`` is for a finished page, where all that is
    left is markup. django-compressor reads markup either way - that is what a
    ``{% compress %}`` block hands it - so a dependency goes in as the tag
    Citry would have written for it.
    """

    def __init__(self, force: Callable[[], bool] | None = None) -> None:
        self.force = force

    def forced(self) -> bool:
        """Whether this render must bypass django-compressor's cache.

        A project says so when its output depends on something the cache key
        does not cover - Wagtail's preview of unsaved theme settings is the
        case this exists for.
        """
        return bool(self.force and self.force())

    def reads(self, dep: Script | Style) -> bool:
        """Whether django-compressor can read this asset at all.

        Two things put one out of reach. An asset somewhere django-compressor
        does not serve from is not its to read, which is what keeps a
        component's CDN script out of a bundle rather than ending the response
        with `UncompressableFileError`. And one with neither a URL nor content
        has nothing to read.

        What is left depends on `COMPRESS_ENABLED`. With it on, everything
        goes through, which minifies and bundles the ordinary `.css` and `.js`
        a component declares and not only what a precompiler is configured for.
        With it off, only what needs precompiling: a `.scss` still has to
        become CSS in development, and the rest is left where Citry put it so
        what you read in the browser is what you wrote.
        """
        url = getattr(dep, "url", None)
        if url and not url.startswith(str(settings.COMPRESS_URL)):
            return False
        if not (url or getattr(dep, "content", None)):
            return False
        return bool(settings.COMPRESS_ENABLED) or self.precompiles(dep)

    def precompiles(self, dep: Script | Style) -> bool:
        """Whether django-compressor has a precompiler to run over `dep`.

        Keyed on the asset's own ``type``, because that attribute is the only
        thing django-compressor keys them on. One that names none arrives as
        source and leaves as source, exactly as a `<link href="x.scss">`
        without one would inside a ``{% compress %}`` block. The extension
        writes that attribute before this is asked; see `typed()` there.
        """
        declared = dep.attrs.get("type")
        return bool(declared) and declared in dict(settings.COMPRESS_PRECOMPILERS)

    def dependencies(self, deps: list[Any], kind: Kind) -> list[Any]:
        """`deps` as django-compressor leaves them, one group at a time."""
        build = GROUPS[kind][1]
        return [asset.as_dependency(build) for asset in self.of(self.markup(deps), kind)]

    def tags(self, tags: list[str], kind: Kind) -> list[str]:
        """`tags` as django-compressor leaves them, still markup."""
        build = GROUPS[kind][1]
        return [str(asset.as_dependency(build).render()) for asset in self.of(tags, kind)]

    def of(self, markup: list[str], kind: Kind) -> list[Asset]:
        """What django-compressor makes of `markup`, from its cache where allowed.

        That cache lives in the ``{% compress %}`` tag rather than in
        ``output()``, so calling ``output()`` directly recompiles the SCSS every
        time: once per emission, and a page that places one component ten times
        pays ten times. The rule here is the tag's own rule, and the key is
        django-compressor's too, a digest of the content plus the mtimes of its
        sources, so an edited stylesheet still invalidates.
        """
        content = "\n".join(markup)
        if not content.strip():
            return []

        compressor = GROUPS[kind][0].over(kind, content)
        if self.forced() or not settings.COMPRESS_ENABLED:
            return compressor.assets(forced=True)

        key = get_templatetag_cachekey(compressor, "file", kind)
        cached = cache_get(key)
        if cached is not None:
            return cached
        assets = compressor.assets(forced=True)
        cache_set(key, assets)
        return assets

    @staticmethod
    def markup(deps: list[Any]) -> list[str]:
        """`deps` as the tags Citry would have written for them."""
        return [str(dep.render()) for dep in deps]


class CitryCompressorExtension(Extension):
    """
    Citry's component assets, routed through django-compressor.

    An asset a browser cannot read on its own - SCSS, Less, CoffeeScript - is
    fed to django-compressor, which precompiles and minifies it, and the
    dependency is replaced by one pointing at the compressed file. Say what
    compiles it the way you would in a template, with the asset's own ``type``::

        class Dependencies:
            css = [Style(url=static("theme.scss"), attrs={"type": "text/x-scss"})]

    Two hooks, because there are two moments. `on_dependencies` fires while one
    Citry region is being serialized, and `on_page_assets` once the page holding
    those regions is finished. Only the second sees a whole response, so only
    the second can make one file of it.

    ``sort`` decides the order inside that file; see :meth:`bundled`.
    """

    name = "compressor"

    def __init__(self, force: Callable[[], bool] | None = None, *, sort: bool = True) -> None:
        self.compression = Compression(force)
        self.sort = sort

    def on_dependencies(self, ctx: Any) -> None:
        """Replace what django-compressor will take with what it made."""
        ctx.styles[:] = self.replaced(ctx.styles, Kind.CSS)
        ctx.scripts[:] = self.replaced(ctx.scripts, Kind.JS)

    def on_page_assets(self, asset: Any) -> tuple[str, ...]:
        """One page's worth of a group, as one file.

        This hook is what makes the difference between a bundle per `<c-*>`
        region and a bundle per response: two regions holding different
        components compress to two files however little is in them, because
        neither render can see the other.

        Bundling needs somewhere to put the result, so a page that named no
        spot for this group keeps the files its regions made, and the marks
        that said they could still be bundled come off.
        """
        mine = [tag for tag in asset.tags if BUNDLE_ATTR in tag]
        if not mine:
            return asset.tags
        if not asset.collected:
            return tuple(self.unmarked(tag) for tag in asset.tags)
        return self.bundled(Kind(str(asset.kind)), asset.tags, mine)

    def replaced(self, deps: list[Any], kind: Kind) -> list[Any]:
        """`deps` with the ones worth compressing swapped for what came back."""
        typed = [self.typed(dep) for dep in deps]
        ours = [dep for dep in typed if self.shareable(dep) and self.compression.reads(dep)]
        if not ours:
            return typed
        untouched = [dep for dep in typed if dep not in ours]
        compressed = self.compression.dependencies(ours, kind)
        return untouched + [self.marked(dep) for dep in compressed]

    def typed(self, dep: Any) -> Any:
        """`dep`, saying what compiles it, when the project mapped its suffix.

        An asset's own ``type`` always wins. `CITRY_COMPRESSOR_FILE_TYPES` is
        for the rest, so a project spells the mapping once instead of at every
        call site, and one call can name a `.css` and a `.scss` together.
        """
        if dep.attrs.get("type"):
            return dep
        mimetype = self.file_types().get(self.suffix_of(dep))
        return dep if mimetype is None else replace(dep, attrs={**dep.attrs, "type": mimetype})

    def suffix_of(self, dep: Any) -> str:
        """The suffix of the file this asset came from, as far as it is known.

        A `Dependencies` entry is a URL and says so itself. A ``css_file`` or
        ``js_file`` arrives as contents with no URL at all, so the suffix is
        the component's to answer: `origin_class_id` names the class, and
        Citry looks it up.
        """
        url = getattr(dep, "url", None)
        if url:
            return PurePosixPath(url).suffix.lower()
        declared = self.declared_file(dep)
        return PurePosixPath(declared).suffix.lower() if declared else ""

    def declared_file(self, dep: Any) -> str | None:
        """What the component this asset came from named as its file."""
        class_id = getattr(dep, "origin_class_id", None)
        if class_id is None:
            return None
        try:
            component = self.citry.get_component_by_class_id(class_id)
        except KeyError:
            return None
        attribute = "css_file" if isinstance(dep, Style) else "js_file"
        return getattr(component, attribute, None)

    @staticmethod
    def file_types() -> dict[str, str]:
        """Suffix to the mimetype this project compiles it under.

        Empty unless the project says otherwise: which suffixes it compiles,
        and under which of its own `COMPRESS_PRECOMPILERS` names, is not this
        package's to guess.
        """
        return dict(getattr(settings, "CITRY_COMPRESSOR_FILE_TYPES", {}))

    def shareable(self, dep: Script | Style) -> bool:
        """Whether this asset is the same on every page placing the component.

        Two things say it is not. A kind that belongs to one render cannot be
        shared between pages: `core` is the client runtime and `variables` is
        one instance's own `js_data`. And an asset Citry serves from its own
        routes is not in staticfiles, where django-compressor reads.
        """
        if getattr(dep, "kind", None) not in BUNDLED_KINDS:
            return False
        url = getattr(dep, "url", None)
        prefix = self.citry.mounted_prefix
        return not (url and prefix and url.startswith(prefix))

    def bundled(self, kind: Kind, tags: tuple[str, ...], mine: list[str]) -> tuple[str, ...]:
        """`tags` with everything bundleable replaced, in place, by one file.

        In place because position is meaning: what a bundle does not swallow
        still has to come before or after it. The bundle takes the position of
        the first tag it swallowed.

        What goes *inside* it is sorted, because a compressed file is named
        after its own bytes. Components arrive in whatever order a page reaches
        them, so two pages placing the same components differently would write
        two files with identical contents in a different order, and a visitor
        moving between them would download both. Sorting makes one set of
        components one file, wherever they sit.

        `sort=False` keeps the order the page has them in, for a project whose
        component stylesheets rely on it.
        """
        replacement = self.compression.tags(sorted(mine) if self.sort else mine, kind)
        placed: list[str] = []
        for tag in tags:
            if BUNDLE_ATTR not in tag:
                placed.append(tag)
            elif replacement:
                placed.extend(replacement)
                replacement = []
        return tuple(placed)

    @staticmethod
    def marked(dep: Any) -> Any:
        """`dep`, saying the page may still bundle it, while there is a page."""
        if current_page.get() is None:
            return dep
        return replace(dep, attrs={**dep.attrs, BUNDLE_ATTR: ""})

    @staticmethod
    def unmarked(tag: str) -> str:
        return tag.replace(f' {BUNDLE_ATTR}=""', "").replace(f" {BUNDLE_ATTR}", "")
