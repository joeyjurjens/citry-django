from __future__ import annotations

from django.http import HttpResponse
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


def page(request):
    return HttpResponse(engines["citry"].from_string(PAGE).render({}, request))


def fills(request):
    return HttpResponse(engines["citry"].from_string(FILLS).render({"note": NOTE}, request))


urlpatterns = [
    path("page/", page, name="page"),
    path("fills/", fills, name="fills"),
    # Mounted the way the README shows, so the browser loads Citry's files
    # through citry-django's gzip wrapper.
    *citry_urls(app, PREFIX),
]
