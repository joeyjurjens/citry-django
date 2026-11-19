from __future__ import annotations

from citry.contrib.django import urlpatterns as citry_urlpatterns
from django.http import HttpResponse
from django.template import engines
from django.urls import include, path

from .app import PREFIX, app

#: Two islands with Django text between them, and spots for their tags.
PAGE = """<!doctype html>
<html><head><title>Two islands</title><c-css/></head>
<body>
  <c-counter label="first"/>
  <p>Django text between the islands.</p>
  <c-counter label="second"/>
  <c-js/>
</body></html>
"""


def page(request):
    return HttpResponse(engines["citry"].from_string(PAGE).render({}, request))


urlpatterns = [
    path("page/", page),
    path(f"{PREFIX.strip('/')}/", include(citry_urlpatterns(app, prefix=PREFIX))),
]
