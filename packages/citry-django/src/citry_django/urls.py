from __future__ import annotations

import gzip
import hashlib
from collections import OrderedDict
from threading import Lock
from typing import Any

from citry.contrib.django import urlpatterns as citry_urlpatterns
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import include, path
from django.utils.cache import patch_vary_headers

#: What a project that still turns on `CITRY_MINIFY_ASSETS` is told.
MINIFY_REMOVED = (
    "CITRY_MINIFY_ASSETS was removed in citry-django 0.4.0. Citry pins each "
    "file it serves with an integrity hash of its bytes, so the browser "
    "refuses a minified copy and the page loses Citry's runtime. Remove the "
    "setting; the mount still gzips each file for a client that asks."
)


def urlpatterns(app: Any, prefix: str) -> list[Any]:
    """Citry's own routes, mounted and served the way a static file would be.

    Without them Citry has nowhere to serve its client runtime from, so it
    inlines the whole bundle into every page, on every request. Mounted, a
    browser fetches it once. List them where URL paths start at the site
    root, normally the root URLconf, because they already sit under
    `prefix`::

        # urls.py
        from citry_django.urls import urlpatterns as citry_urls

        urlpatterns = [
            *citry_urls(app, "/citry"),
            ...
        ]

    A response is gzipped once for a client that asks for it.

    Raises:
        ImproperlyConfigured: `CITRY_MINIFY_ASSETS` is on. Citry pins each
            file it serves with an `integrity` hash of its bytes, so a
            browser refuses a minified copy and the page loses its runtime.
    """
    # Checked here because the mount is the only place the setting ever
    # applied. Django loads the URLconf in `check`, in `runserver`, or on the
    # first request, so the project fails before it serves any page whose
    # runtime the browser would refuse.
    if getattr(settings, "CITRY_MINIFY_ASSETS", False):
        raise ImproperlyConfigured(MINIFY_REMOVED)
    mounted = citry_urlpatterns(app, prefix)
    # The patterns sit under `prefix` themselves, so the URLs Citry builds
    # from it and the routes Django matches cannot disagree.
    segment = prefix.strip("/")
    route = f"{segment}/" if segment else ""
    return [path(route, include([served(pattern) for pattern in mounted]))]


def served(pattern: Any) -> Any:
    """One mounted route, prepared the way a web server prepares a file."""
    view = pattern.callback

    def serve(request: Any, *args: Any, **kwargs: Any) -> Any:
        return prepared(request, view(request, *args, **kwargs))

    pattern.callback = serve
    return pattern


def prepared(request: Any, response: Any) -> Any:
    """`response` as it should leave: compressed when it is a file.

    A web server compresses the files it serves, and these are not files it
    serves: they come from a Django view, so a rule that names a static
    directory never reaches them, and nginx leaves a proxied response alone
    unless it was told otherwise.

    Caching stays Citry's to decide. It names the runtime and the
    JavaScript that defines each Vue island by a hash of their content and
    marks those `immutable`, and it serves the files whose content can
    change at a fixed name, such as `cache/<class_id>.js`, with `no-cache`
    and an `ETag`, so a browser asks again after a deploy instead of keeping
    the old component JS.
    """
    if response.status_code not in (200, 304) or not is_file(request, response):
        return response
    # Every answer for a file says it depends on Accept-Encoding, the plain
    # one too, so a shared cache that first stores the plain body does not
    # hand it to every client after that.
    patch_vary_headers(response, ["Accept-Encoding"])
    if not accepts_gzip(request) or "Content-Encoding" in response:
        return response
    # A strong ETag names one exact body, and the gzipped body is a
    # different one. Weak says "the same content", which is still true. A
    # 304 repeats the tag the 200 would carry, and Citry compares the tag a
    # browser sends back the weak way, so a revalidation still gets its 304.
    etag = response.get("ETag")
    if etag and not etag.startswith("W/"):
        response["ETag"] = f"W/{etag}"
    if response.status_code == 200 and is_text(response):
        response.content = compressed(response.content)
        response["Content-Encoding"] = "gzip"
    return response


def is_file(request: Any, response: Any) -> bool:
    """Whether this answer is one of Citry's public files, not an endpoint.

    Citry marks each public JavaScript and CSS file it serves with
    `Access-Control-Allow-Origin: *`, which the browser needs to check the
    file's `integrity`, and its endpoints never carry it. Reading the
    answer rather than the path keeps an endpoint out even when its URL
    ends in something that looks like a file name, such as a GET event
    named `export.csv`, whose answer belongs to one visitor.
    """
    return request.method in ("GET", "HEAD") and response.get("Access-Control-Allow-Origin") == "*"


def is_text(response: Any) -> bool:
    """Whether gzip is worth running: text compresses, images mostly do not."""
    kind = response.get("Content-Type", "").split(";", 1)[0].strip()
    return kind.startswith("text/") or kind in TEXT_TYPES


#: Content types beyond `text/*` that Citry serves and gzip shrinks.
TEXT_TYPES = frozenset({"application/javascript", "application/json", "image/svg+xml"})

#: Gzipped bodies by a digest of the plain body, most recently used last.
packed: OrderedDict[bytes, bytes] = OrderedDict()

#: How many gzipped bodies `packed` keeps.
PACKED_LIMIT = 64

packed_lock = Lock()


def compressed(content: bytes) -> bytes:
    """`content` gzipped, once per distinct body.

    Around 10 ms for the 400 kB runtime, which is worth paying on the first
    request and not on every one. Keyed by a digest of the body rather than
    the URL, because a file at a fixed name such as `cache/<class_id>.js`
    can change while the process runs. The limit keeps the stylesheets
    Citry builds for each set of `css_data()` values from growing the cache
    without end, and `mtime=0` makes every worker write the same bytes.
    """
    key = hashlib.sha256(content).digest()
    with packed_lock:
        if key in packed:
            packed.move_to_end(key)
            return packed[key]
    body = gzip.compress(content, compresslevel=6, mtime=0)
    with packed_lock:
        packed[key] = body
        while len(packed) > PACKED_LIMIT:
            packed.popitem(last=False)
    return body


def accepts_gzip(request: Any) -> bool:
    return "gzip" in request.META.get("HTTP_ACCEPT_ENCODING", "")
