from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import partial
from pathlib import PurePosixPath
from typing import Any

from citry.ext.dependencies import Script, Style
from citry.extension import Extension
from compressor.cache import cache_get, cache_set, get_templatetag_cachekey
from compressor.conf import settings as compressor_settings
from compressor.css import CssCompressor
from compressor.js import JsCompressor
from compressor.utils import get_class
from django.conf import settings

__all__ = ["CitryCompressorExtension"]


class Kind(StrEnum):
    """The two groups django-compressor keeps apart."""

    CSS = "css"
    JS = "js"


#: One attribute of a tag Citry wrote: a name, and a quoted value or none.
ATTRIBUTE = re.compile(r"""([^\s=/>"']+)(\s*=\s*(?:"([^"]*)"|'([^']*)'))?""")

#: A tag the page hands over: its name, its attributes, and any content.
PAGE_TAG = re.compile(
    r"<(?P<name>script|style|link)\b(?P<attrs>[^>]*?)/?>(?:(?P<content>.*?)</(?P=name)>)?",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class PageTag:
    """One component tag from a finished page, read the way a dependency reads.

    The page hands this package markup, not Citry's dependency objects, so a
    tag is read back into the few things the rules below ask of an asset: its
    URL or content and its attributes. What Citry said about the tag, the
    components that declared it and whether it may hold one render's data,
    comes with it as `entry`, a `citry.SerializedAssetEntry`, or None when
    Citry did not describe it.
    """

    markup: str
    name: str
    attrs: dict[str, Any]
    content: str | None
    entry: Any = None

    @classmethod
    def read(cls, markup: str, entry: Any = None) -> PageTag | None:
        """`markup` as a tag, or None when it is not one this package reads."""
        match = PAGE_TAG.fullmatch(markup.strip())
        if match is None:
            return None
        attrs: dict[str, Any] = {}
        for name, assigned, double, single in ATTRIBUTE.findall(match.group("attrs")):
            # `href=""` is an empty value, not a bare attribute.
            attrs[name.lower()] = html.unescape(double or single) if assigned else True
        return cls(markup, match.group("name").lower(), attrs, match.group("content"), entry)

    @property
    def kind(self) -> Kind:
        return Kind.JS if self.name == "script" else Kind.CSS

    @property
    def url(self) -> str | None:
        """The file this tag loads, if it loads one."""
        if self.name == "script":
            return self.attrs.get("src") or None
        if self.name == "link" and self.attrs.get("rel") == "stylesheet":
            return self.attrs.get("href") or None
        return None

    @property
    def origin_class_id(self) -> str | None:
        """The class id of the first component that declared this tag, if Citry said."""
        class_ids = self.entry.class_ids if self.entry is not None else ()
        return class_ids[0] if class_ids else None

    @property
    def is_style(self) -> bool:
        return self.kind is Kind.CSS

    def typed(self, mimetype: str) -> PageTag:
        """This tag, saying what compiles it."""
        opened = f"<{self.name}"
        start = self.markup.index(opened) + len(opened)
        markup = f'{self.markup[:start]} type="{html.escape(mimetype)}"{self.markup[start:]}'
        return replace(self, markup=markup, attrs={**self.attrs, "type": mimetype})


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

#: ``{(kind, configured class): collecting class}``, built once per pair.
_COLLECTING: dict[tuple[Kind, type], type[Collecting]] = {}


def collecting(kind: Kind) -> type[Collecting]:
    """The compressor for `kind`, built on the class ``COMPRESSORS`` names.

    The same class a ``{% compress %}`` block uses, so a project that configures
    its own compressor, to name its output files for instance, gets it for the
    files written here as well.
    """
    base = GROUPS[kind][0]
    configured = get_class(compressor_settings.COMPRESSORS[kind.value])
    if issubclass(base, configured):
        return base
    key = (kind, configured)
    if key not in _COLLECTING:
        _COLLECTING[key] = type(base.__name__, (base, configured), {})
    return _COLLECTING[key]


class Compression:
    """django-compressor, handed assets and read back as assets.

    Everything this knows is django-compressor's: what it can read, what it
    does with it, and where its answer is a value rather than a tag. What is
    worth handing over in the first place is Citry's question, and belongs to
    the extension below.

    ``tags`` takes markup from a finished page, and django-compressor reads
    markup - that is what a ``{% compress %}`` block hands it - so a tag goes
    in as Citry wrote it.
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

    def reads(self, dep: Script | Style | PageTag) -> bool:
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

    def precompiles(self, dep: Script | Style | PageTag) -> bool:
        """Whether django-compressor has a precompiler to run over `dep`.

        Keyed on the asset's own ``type``, because that attribute is the only
        thing django-compressor keys them on. One that names none arrives as
        source and leaves as source, exactly as a `<link href="x.scss">`
        without one would inside a ``{% compress %}`` block. The extension
        writes that attribute before this is asked; see `typed()` there.
        """
        declared = dep.attrs.get("type")
        return bool(declared) and declared in dict(settings.COMPRESS_PRECOMPILERS)

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

        compressor = collecting(kind).over(kind, content)
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

    It works on the finished page, through citry-django's `on_page_assets`
    hook, which hands over the component tags of a response: one call for the
    CSS and one for the JavaScript when the template names a `<c-css />` or
    `<c-js />` spot, or one call per region without a spot. Citry's browser
    runtime and each Vue island's own tags never reach it, so the assets of a
    component that needs Vue stay as Citry wrote them.

    ``sort`` decides the order inside that file. A compressed file is named
    after its own bytes, and components arrive in whatever order a page
    reaches them, so the tags are sorted first: one set of components makes
    one file wherever they sit. `sort=False` keeps the page's order, for a
    project whose component stylesheets rely on it. The file takes the
    position of the first tag it replaced, and every tag it does not take
    keeps its own place.
    """

    name = "compressor"

    def __init__(self, force: Callable[[], bool] | None = None, *, sort: bool = True) -> None:
        self.compression = Compression(force)
        self.sort = sort

    def on_page_assets(self, asset: Any) -> tuple[str, ...]:
        """One page's worth of component tags of one kind, as one file.

        This hook is what makes the difference between a bundle per `<c-*>`
        region and a bundle per response: two regions holding different
        components compress to two files however little is in them, because
        neither render can see the other.
        """
        kind = Kind(str(asset.kind))
        # An earlier extension may have replaced some tags, so an entry is
        # found by its tag rather than by its position.
        entries = {entry.tag: entry for entry in getattr(asset, "entries", ())}
        offered = [self.offered(tag, kind, entries.get(tag)) for tag in asset.tags]
        mine = [tag.markup for tag in offered if tag is not None]
        if not mine:
            return asset.tags
        placed: list[str] = []
        replacement = self.compression.tags(sorted(mine) if self.sort else mine, kind)
        for original, tag in zip(asset.tags, offered, strict=True):
            if tag is None:
                placed.append(original)
            elif replacement:
                # The bundle takes the position of the first tag it swallowed.
                placed.extend(replacement)
                replacement = []
        return tuple(placed)

    def offered(self, markup: str, kind: Kind, entry: Any = None) -> PageTag | None:
        """`markup` typed for django-compressor, or None when it is not offered."""
        tag = PageTag.read(markup, entry)
        if tag is None or tag.kind is not kind:
            return None
        tag = self.typed(tag)
        if self.shareable(tag) and self.compression.reads(tag):
            return tag
        return None

    def typed(self, dep: Any) -> Any:
        """`dep`, saying what compiles it, when the project mapped its suffix.

        An asset's own ``type`` always wins. `CITRY_COMPRESSOR_FILE_TYPES` is
        for the rest, so a project spells the mapping once instead of at every
        call site, and one call can name a `.css` and a `.scss` together.
        """
        if dep.attrs.get("type"):
            return dep
        mimetype = self.file_types().get(self.suffix_of(dep))
        if mimetype is None:
            return dep
        if isinstance(dep, PageTag):
            return dep.typed(mimetype)
        return replace(dep, attrs={**dep.attrs, "type": mimetype})

    def suffix_of(self, dep: Any) -> str:
        """The suffix of the file this asset came from, as far as it is known.

        A `Dependencies` entry is a URL and says so itself. A ``css_file``
        arrives as contents with no URL at all, so the suffix is the
        component's to answer: `origin_class_id` names the class, and Citry
        looks it up.
        """
        url = getattr(dep, "url", None)
        if url:
            return self.suffix(url)
        declared = self.declared_file(dep)
        return self.suffix(declared) if declared else ""

    @staticmethod
    def suffix(path: str) -> str:
        """`path`'s suffix, without a query or fragment.

        django-compressor drops a querystring before it resolves a file, so a
        URL carrying one compiles fine there. Reading the suffix off the whole
        string would see `.scss?v=2`, match no mimetype, and leave the SCSS to
        reach the browser as SCSS.
        """
        bare = path.split("?", 1)[0].split("#", 1)[0]
        return PurePosixPath(bare).suffix.lower()

    def declared_file(self, dep: Any) -> str | None:
        """What the component this asset came from named as its file."""
        class_id = getattr(dep, "origin_class_id", None)
        if class_id is None:
            return None
        try:
            component = self.citry.get_component_by_class_id(class_id)
        except KeyError:
            return None
        is_style = dep.is_style if isinstance(dep, PageTag) else isinstance(dep, Style)
        attribute = "css_file" if is_style else "js_file"
        return getattr(component, attribute, None)

    @staticmethod
    def file_types() -> dict[str, str]:
        """Suffix to the mimetype this project compiles it under.

        Empty unless the project says otherwise: which suffixes it compiles,
        and under which of its own `COMPRESS_PRECOMPILERS` names, is not this
        package's to guess.
        """
        return dict(getattr(settings, "CITRY_COMPRESSOR_FILE_TYPES", {}))

    def shareable(self, tag: PageTag) -> bool:
        """Whether this tag is the same on every page placing the component.

        Citry says so in the tag's entry: `instance` is False only for a
        component's own CSS and JavaScript and its `Dependencies`. A tag
        that may hold one render's data, such as a `<style>` with one
        instance's `css_data()` values, or one Citry did not describe, would
        put one page's data in a file meant to be shared, so it stays in the
        page. A file Citry serves from its own routes stays too: those are
        not in staticfiles, where django-compressor reads.
        """
        if tag.entry is None or tag.entry.instance:
            return False
        url = tag.url
        if not url:
            return True
        prefix = self.citry.mounted_prefix
        return not (prefix and url.startswith(prefix))
