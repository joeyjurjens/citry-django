from __future__ import annotations

import secrets
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.template import engines
from django.urls import path

from citry_django.urls import urlpatterns as citry_urls

from .app import PREFIX, app

#: Two islands with Django text between them, and spots for their tags.
PAGE = """<!doctype html>
<html><head><title>Two islands</title><link rel="icon" href="data:,"><c-css/></head>
<body>
  <c-counter label="first"/>
  <p>Django text between the islands.</p>
  <c-counter label="second"/>
  <c-js/>
</body></html>
"""


#: Interactive components whose fills hold Django tags.
FILLS = """{% load i18n %}<!doctype html>
<html><head><title>Fills</title><link rel="icon" href="data:,"><c-css/></head>
<body>
  <c-modal title="Notes">
    <span class="hello">{% translate "Hello" %}</span>
    {% if note %}<b class="note">{{ note }}</b>{% endif %}
  </c-modal>
  <p>Django text between the islands.</p>
  <c-panel/>
  <c-js/>
</body></html>
"""

#: What a visitor might type: Vue syntax and markup, which must stay text.
NOTE = '{{ 1 + 1 }} <img src=x onerror="window.injected = 1"> v-html'


#: An island, and a wrapper htmx swaps a second island into. htmx comes from
#: this site, so a Content Security Policy of `script-src 'self'` allows it.
SWAP = """<!doctype html>
<html><head><title>Swap</title><link rel="icon" href="data:,"><c-css/></head>
<body>
  <c-counter label="first"/>
  <button
    type="button"
    class="load"
    hx-get="/card/"
    hx-target="#cards"
    hx-swap="innerHTML"
  >load</button>
  <div id="cards"></div>
  <script src="/htmx.js"></script>
  <c-js/>
</body></html>
"""

#: The same wrapper on a page without any island, so without Citry's runtime.
PLAIN = SWAP.replace('<c-counter label="first"/>', "<p>No island here.</p>")

#: What `/card/` answers: Django text around an island.
CARD = """<p class="card">A card from the server.</p>
<c-counter label="swapped"/>
"""

#: htmx 2.0.10, the copy Citry's own htmx demo pins (Zero-Clause BSD).
HTMX = Path(__file__).parent / "static" / "htmx-2.0.10.min.js"


def with_csp(view):
    """Send a nonce-based Content Security Policy when a test turns it on.

    Each response gets a fresh nonce on `request.csp_nonce`, where django-csp
    puts it and citry-django reads it, so an htmx request carries a nonce no
    page in the browser has. `'self'` lets the page load htmx and Citry's
    files; every inline script needs the page's nonce.
    """

    @wraps(view)
    def wrapped(request):
        if not getattr(settings, "EVENTS_SITE_CSP", False):
            return view(request)
        request.csp_nonce = secrets.token_urlsafe(16)
        response = view(request)
        response["Content-Security-Policy"] = f"script-src 'self' 'nonce-{request.csp_nonce}'"
        return response

    return wrapped


def page(request):
    return HttpResponse(engines["citry"].from_string(PAGE).render({}, request))


def fills(request):
    return HttpResponse(engines["citry"].from_string(FILLS).render({"note": NOTE}, request))


@with_csp
def swap(request):
    return HttpResponse(engines["citry"].from_string(SWAP).render({}, request))


@with_csp
def plain(request):
    return HttpResponse(engines["citry"].from_string(PLAIN).render({}, request))


@with_csp
def card(request):
    # htmx sends HX-Request, so citry-django writes the island as a fragment.
    return HttpResponse(engines["citry"].from_string(CARD).render({}, request))


def htmx(request):
    return FileResponse(HTMX.open("rb"), content_type="text/javascript")


urlpatterns = [
    path("page/", page, name="page"),
    path("fills/", fills, name="fills"),
    path("swap/", swap, name="swap"),
    path("plain/", plain, name="plain"),
    path("card/", card, name="card"),
    path("htmx.js", htmx, name="htmx"),
    # Mounted the way the README shows, so the browser loads Citry's files
    # through citry-django's gzip wrapper.
    *citry_urls(app, PREFIX),
]
