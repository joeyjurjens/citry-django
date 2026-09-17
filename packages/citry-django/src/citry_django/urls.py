from __future__ import annotations

import gzip
import hashlib
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePosixPath
from typing import Any

from citry.contrib.django import urlpatterns as citry_urlpatterns
from django.conf import settings
from django.urls import include, path

#: A year, which is as long as `Cache-Control` is allowed to promise.
FOREVER = 31536000

#: One compressed body per URL. The release segment is in that URL, so an
#: upgrade is a different key rather than a stale value.
packed: dict[str, bytes] = {}


def urlpatterns(app: Any, prefix: str) -> list[Any]:
    """Citry's own routes, mounted and served the way a static file would be.

    Without them Citry has nowhere to serve its client runtime from, so it
    inlines the whole bundle into every page, on every request. Mounted, a
    browser fetches it once::

        # urls.py
        from citry_django.urls import urlpatterns as citry_urls

        urlpatterns = [
            *citry_urls(app, "/citry"),
            ...
        ]

    `CITRY_MINIFY_ASSETS` runs the JavaScript through django-compressor's
    minifier on the way out, and a response is gzipped once for a client that
    asks for it. Citry ships the runtime unminified, and it is not a file
    staticfiles can see, so this is the one place able to shrink it.
    """
    token = release()
    mounted = citry_urlpatterns(app, f"{prefix.rstrip('/')}/{token}")
    return [path(f"{token}/", include([served(pattern) for pattern in mounted]))]


def release() -> str:
    """A path segment that changes whenever the served bytes could.

    Citry names its own routes: `citry.js` is `citry.js` at every version, so
    a browser told to keep one forever would keep the wrong one after an
    upgrade. Putting this in the mount prefix puts it in every URL Citry
    builds, since `Citry.build_url` is the prefix and the route's path, and
    an upgrade then reaches a browser as a different file rather than as a
    revalidation it may skip.

    What can change those bytes is the version of Citry that ships them and
    whether this module minifies on the way out.
    """
    minified = bool(getattr(settings, "CITRY_MINIFY_ASSETS", False))
    digest = hashlib.sha256(f"{installed('citry')}:{minified}".encode())
    return digest.hexdigest()[:8]


def installed(package: str) -> str:
    """The version of `package`, or a marker when it is not installed."""
    try:
        return version(package)
    except PackageNotFoundError:  # pragma: no cover - Citry is a dependency
        return "unknown"


def served(pattern: Any) -> Any:
    """One mounted route, prepared the way a web server prepares a file."""
    view = pattern.callback

    def serve(request: Any, *args: Any, **kwargs: Any) -> Any:
        return prepared(request, view(request, *args, **kwargs))

    pattern.callback = serve
    return pattern


def prepared(request: Any, response: Any) -> Any:
    """`response` as it should leave: minified, compressed, kept forever.

    A web server compresses and caches the files it serves, and these are not
    files it serves: they come from a Django view, so a rule that names a
    static directory never reaches them, and nginx leaves a proxied response
    alone unless it was told otherwise.

    Only for the routes that are files. Citry mounts its event endpoints
    beside them, and those answer in JSON, per request: telling a browser to
    keep one of those for a year would break every interactive component on
    the page.
    """
    if response.status_code != 200 or not is_file(request):
        return response
    if is_javascript(response) and getattr(settings, "CITRY_MINIFY_ASSETS", False):
        response.content = minified(response.content)
    if accepts_gzip(request) and "Content-Encoding" not in response:
        response.content = compressed(request.path, response.content)
        response["Content-Encoding"] = "gzip"
        response["Vary"] = "Accept-Encoding"
    response["ETag"] = f'"{hashlib.sha256(response.content).hexdigest()[:16]}"'
    response["Cache-Control"] = f"public, max-age={FOREVER}, immutable"
    return response


def is_file(request: Any) -> bool:
    """Whether this request is for one of the files, rather than an endpoint.

    A file route names a file: `citry.js`, `cache/Table_a1b2c3.js`,
    `asset/theme.css`. An endpoint does not: `ext/events/call` and
    `ext/events/e/<class_id>` are where a component's server-side events are
    answered, in JSON. Asking the path is what keeps a route Citry adds later
    from being cached by accident.
    """
    return request.method == "GET" and bool(PurePosixPath(request.path).suffix)


def compressed(url: str, content: bytes) -> bytes:
    """`content` gzipped, once.

    Around 10 ms for the 400 kB runtime, which is worth paying on the first
    request and not on every one. What a URL serves cannot change while the
    process runs, because the release segment is part of it.
    """
    if url not in packed:
        packed[url] = gzip.compress(content, compresslevel=6)
    return packed[url]


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
