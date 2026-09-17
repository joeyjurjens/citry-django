from __future__ import annotations

import gzip
import hashlib
from typing import Any

from citry.contrib.django import urlpatterns as citry_urlpatterns
from django.conf import settings

#: How long a browser may keep one of Citry's own files, in seconds. Citry
#: serves the runtime from an unhashed URL, so this is a revalidation window
#: rather than a promise: the ETag below turns a stale hit into a cheap 304.
DEFAULT_MAX_AGE = 3600


def urlpatterns(app: Any, prefix: str) -> list[Any]:
    """Citry's own routes, mounted and served the way a static file would be.

    Without them Citry has nowhere to serve its client runtime from, so it
    inlines the whole bundle into every page, on every request. Mounted, the
    browser fetches it once and revalidates after that::

        # urls.py
        from citry_django.urls import urlpatterns as citry_urls

        urlpatterns = [
            *citry_urls(app, "/citry"),
            ...
        ]

    `CITRY_ASSET_MAX_AGE` sets the revalidation window, and
    `CITRY_MINIFY_ASSETS` runs the JavaScript through django-compressor's
    minifier on the way out. A response is gzipped for a client that asks
    for it. Citry ships the runtime unminified, and it is not
    a file staticfiles can see, so this is the one place able to shrink it.
    """
    return [served(pattern) for pattern in citry_urlpatterns(app, prefix)]


def served(pattern: Any) -> Any:
    """One mounted route, prepared the way a web server prepares a file."""
    view = pattern.callback

    def serve(request: Any, *args: Any, **kwargs: Any) -> Any:
        return prepared(request, view(request, *args, **kwargs))

    pattern.callback = serve
    return pattern


def prepared(request: Any, response: Any) -> Any:
    """`response` as it should leave: minified, compressed, revalidating.

    A web server compresses the files it serves, and these are not files it
    serves: they come from a Django view, so a rule that names a static
    directory never reaches them. Compressing here is what keeps the runtime
    from crossing the wire at its full size.
    """
    if response.status_code != 200:
        return response
    if is_javascript(response) and getattr(settings, "CITRY_MINIFY_ASSETS", False):
        response.content = minified(response.content)
    if accepts_gzip(request) and "Content-Encoding" not in response:
        response.content = gzip.compress(response.content, compresslevel=6)
        response["Content-Encoding"] = "gzip"
        response["Vary"] = "Accept-Encoding"
    response["ETag"] = f'"{hashlib.sha256(response.content).hexdigest()[:16]}"'
    max_age = getattr(settings, "CITRY_ASSET_MAX_AGE", DEFAULT_MAX_AGE)
    response["Cache-Control"] = f"public, max-age={max_age}"
    return response


def accepts_gzip(request: Any) -> bool:
    return "gzip" in request.META.get("HTTP_ACCEPT_ENCODING", "")


def is_javascript(response: Any) -> bool:
    return "javascript" in response.get("Content-Type", "")


def minified(content: bytes) -> bytes:
    """`content` through django-compressor's minifier, or unchanged without it.

    The dependency is the compressor package's, not this one's, so a project
    that does not install it keeps the bundle it had rather than an error.
    """
    try:
        from compressor.filters.jsmin import rJSMinFilter
    except ImportError:
        return content
    return rJSMinFilter(content.decode()).output().encode()
