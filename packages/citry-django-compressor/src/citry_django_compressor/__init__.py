"""
Route Citry component assets through django-compressor.

Citry collects each component's CSS and JS and emits them into the page.
A project that runs django-compressor wants those assets preprocessed
(SCSS, Less, CoffeeScript, ...) and minified before they reach the browser.

This extension hooks Citry's ``on_dependencies`` lifecycle to feed assets
into django-compressor's programmatic API, replacing inline content with
compressed file URLs.

Usage::

    from citry import Citry
    from citry_django import CitryDjangoExtension
    from citry_django_compressor import CitryCompressorExtension

    app = Citry(extensions=[CitryDjangoExtension(), CitryCompressorExtension()])

Components declare assets the usual Citry way. To mark an asset for
precompilation, set its ``type`` attribute to match a
``COMPRESS_PRECOMPILERS`` entry::

    from citry.ext.dependencies import Style

    class MyComponent(Component):
        class Dependencies:
            css = [Style(content="...", attrs={"type": "text/x-scss"})]

For file-based assets, use the ``Dependencies`` class with a URL and type.
Use Django's ``static()`` to respect your ``STATIC_URL`` setting::

    from django.templatetags.static import static

    class MyComponent(Component):
        class Dependencies:
            css = [Style(url=static("component.scss"), attrs={"type": "text/x-scss"})]
"""

from __future__ import annotations

import re
from typing import Any

from citry.ext.dependencies import Script, Style
from citry.extension import Extension
from compressor.css import CssCompressor
from compressor.js import JsCompressor

__all__ = ["CitryCompressorExtension"]


# File extensions that map to precompiler MIME types.
# Users can extend this via CITRY_COMPRESSOR_FILE_TYPES setting.
DEFAULT_FILE_TYPES: dict[str, str] = {
    # CSS precompilers
    ".scss": "text/x-scss",
    ".sass": "text/x-sass",
    ".less": "text/less",
    ".styl": "text/stylus",
    # JS precompilers
    ".coffee": "text/coffeescript",
}

# Standard types that don't need precompilation.
STANDARD_TYPES = frozenset({"text/css", "text/javascript", "module"})


def _get_mimetype_from_url(url: str, file_types: dict[str, str]) -> str | None:
    """Extract MIME type from URL based on file extension."""
    for ext, mimetype in file_types.items():
        if url.endswith(ext):
            return mimetype
    return None


def _needs_precompilation(dep: Script | Style, file_types: dict[str, str]) -> bool:
    """Check if a dependency needs precompilation."""
    type_attr = dep.attrs.get("type")
    if type_attr and isinstance(type_attr, str) and type_attr not in STANDARD_TYPES:
        return True

    if dep.url:
        return _get_mimetype_from_url(dep.url, file_types) is not None

    return False


def _build_compressor_content(deps: list[Script | Style], kind: str) -> str:
    """Build HTML content string for django-compressor."""
    parts = []
    for dep in deps:
        if kind == "css":
            if dep.url:
                attrs_str = " ".join(f'{k}="{v}"' for k, v in dep.attrs.items() if k != "type")
                type_attr = dep.attrs.get("type", "")
                type_str = f' type="{type_attr}"' if type_attr else ""
                parts.append(f'<link rel="stylesheet" href="{dep.url}"{type_str}{attrs_str}/>')
            else:
                attrs_str = " ".join(f'{k}="{v}"' for k, v in dep.attrs.items() if k != "type")
                type_attr = dep.attrs.get("type", "")
                type_str = f' type="{type_attr}"' if type_attr else ""
                attrs_prefix = f" {attrs_str}" if attrs_str else ""
                parts.append(f'<style{type_str}{attrs_prefix}>{dep.content}</style>')
        else:  # js
            if dep.url:
                attrs_str = " ".join(f'{k}="{v}"' for k, v in dep.attrs.items() if k != "type")
                type_attr = dep.attrs.get("type", "")
                type_str = f' type="{type_attr}"' if type_attr else ""
                parts.append(f'<script src="{dep.url}"{type_str}{attrs_str}></script>')
            else:
                attrs_str = " ".join(f'{k}="{v}"' for k, v in dep.attrs.items() if k != "type")
                type_attr = dep.attrs.get("type", "")
                type_str = f' type="{type_attr}"' if type_attr else ""
                attrs_prefix = f" {attrs_str}" if attrs_str else ""
                parts.append(f'<script{type_str}{attrs_prefix}>{dep.content}</script>')
    return "\n".join(parts)


def _extract_urls_from_output(html: str, kind: str) -> list[dict[str, Any]]:
    """
    Extract URLs and attributes from compressor output HTML.

    Returns list of dicts with 'url' or 'content' and optional 'attrs'.
    """
    results = []

    if kind == "css":
        # Parse <link> tags
        for match in re.finditer(r'<link[^>]*href="([^"]+)"[^>]*/?>', html, re.IGNORECASE):
            url = match.group(1)
            attrs = {}
            tag_str = match.group(0)
            media_match = re.search(r'media="([^"]+)"', tag_str, re.IGNORECASE)
            if media_match:
                attrs["media"] = media_match.group(1)
            results.append({"url": url, "attrs": attrs})

        # Parse inline <style> tags (when compression is disabled)
        for match in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.IGNORECASE | re.DOTALL):
            content = match.group(1)
            tag_str = match.group(0)
            attrs = {}
            media_match = re.search(r'media="([^"]+)"', tag_str, re.IGNORECASE)
            if media_match:
                attrs["media"] = media_match.group(1)
            results.append({"content": content, "attrs": attrs})
    else:  # js
        # Parse <script> tags with src
        for match in re.finditer(r'<script[^>]*src="([^"]+)"[^>]*>', html, re.IGNORECASE):
            url = match.group(1)
            tag_str = match.group(0)
            attrs = {}
            if re.search(r'\bdefer\b', tag_str, re.IGNORECASE):
                attrs["defer"] = True
            if re.search(r'\basync\b', tag_str, re.IGNORECASE):
                attrs["async"] = True
            results.append({"url": url, "attrs": attrs})

        # Parse inline <script> tags (when compression is disabled)
        for match in re.finditer(r'<script([^>]*)>(.*?)</script>', html, re.IGNORECASE | re.DOTALL):
            attrs_str = match.group(1)
            content = match.group(2)
            if re.search(r'src="', attrs_str, re.IGNORECASE):
                continue
            attrs = {}
            if re.search(r'\bdefer\b', attrs_str, re.IGNORECASE):
                attrs["defer"] = True
            if re.search(r'\basync\b', attrs_str, re.IGNORECASE):
                attrs["async"] = True
            results.append({"content": content, "attrs": attrs})

    return results


class CitryCompressorExtension(Extension):
    """
    Routes Citry component assets through django-compressor.

    Assets marked with a precompiler ``type`` attribute are fed to
    django-compressor, which preprocesses (SCSS, Less, etc.) and minifies
    them. The original dependencies are replaced with URL-based ones
    pointing to the compressed output.

    Citry's deduplication runs before this hook, so identical assets from
    multiple components are only compressed once.

    For file-based assets, use the ``Dependencies`` class with a URL and
    explicit ``type`` attribute. The extension detects the file type from
    the URL extension or the ``type`` attribute.
    """

    name = "compressor"

    def __init__(self) -> None:
        self._file_types: dict[str, str] | None = None

    def _get_file_types(self) -> dict[str, str]:
        """Get file extension to MIME type mapping, with user overrides."""
        if self._file_types is None:
            from django.conf import settings

            user_types = getattr(settings, "CITRY_COMPRESSOR_FILE_TYPES", {})
            self._file_types = {**DEFAULT_FILE_TYPES, **user_types}
        return self._file_types

    def on_dependencies(self, ctx: Any) -> None:
        """
        Hook into Citry's dependency emission to compress assets.

        Citry has already deduplicated assets by this point, so we only
        see each unique asset once. We collect assets that need
        precompilation, feed them to django-compressor, and replace the
        originals with compressed URLs.
        """
        file_types = self._get_file_types()

        css_to_compress: list[Style] = []
        css_passthrough: list[Style] = []
        js_to_compress: list[Script] = []
        js_passthrough: list[Script] = []

        for style in ctx.styles:
            if _needs_precompilation(style, file_types):
                css_to_compress.append(style)
            else:
                css_passthrough.append(style)

        for script in ctx.scripts:
            # Skip core scripts (Citry runtime, manifest) - already optimized
            if script.kind == "core":
                js_passthrough.append(script)
            elif _needs_precompilation(script, file_types):
                js_to_compress.append(script)
            else:
                js_passthrough.append(script)

        if css_to_compress:
            compressed_css = self._compress_css(css_to_compress)
            ctx.styles[:] = css_passthrough + compressed_css

        if js_to_compress:
            compressed_js = self._compress_js(js_to_compress)
            ctx.scripts[:] = js_passthrough + compressed_js

    def _compress_css(self, deps: list[Style]) -> list[Style]:
        """Compress CSS dependencies and return new Style objects with URLs."""
        content = _build_compressor_content(deps, "css")
        if not content.strip():
            return []

        compressor = CssCompressor("css", content=content)
        output_html = compressor.output(mode="file", forced=True)

        results = []
        for item in _extract_urls_from_output(output_html, "css"):
            if "url" in item:
                results.append(Style(url=item["url"], attrs=item.get("attrs", {})))
            elif "content" in item:
                results.append(Style(content=item["content"], attrs=item.get("attrs", {})))
        return results

    def _compress_js(self, deps: list[Script]) -> list[Script]:
        """Compress JS dependencies and return new Script objects with URLs."""
        content = _build_compressor_content(deps, "js")
        if not content.strip():
            return []

        compressor = JsCompressor("js", content=content)
        output_html = compressor.output(mode="file", forced=True)

        results = []
        for item in _extract_urls_from_output(output_html, "js"):
            if "url" in item:
                results.append(Script(url=item["url"], attrs=item.get("attrs", {}), wrap=False))
            elif "content" in item:
                results.append(
                    Script(content=item["content"], attrs=item.get("attrs", {}), wrap=False)
                )
        return results
