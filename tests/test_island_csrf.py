"""A page that holds an island makes Django send the CSRF cookie.

Citry's Events calls pass Django's own CSRF check, which needs the cookie,
and a page without a form never asks Django for it.
"""

from __future__ import annotations

import pytest
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware


@pytest.fixture(autouse=True)
def fixtures(component):
    component(
        "<b>live</b>",
        name="csrf-live",
        js_data=lambda self, kwargs, slots: {"on": True},
    )
    component("<i>still</i>", name="csrf-still")
    component("<ul>{% for n in ns %}<li><c-csrf-live/></li>{% endfor %}</ul>", name="csrf-loop")


def cookie_sent(request, html: str) -> bool:
    """Whether Django's CSRF middleware would set the cookie on this response."""
    middleware = CsrfViewMiddleware(lambda request: HttpResponse(html))
    response = middleware(request)
    return "csrftoken" in response.cookies


def test_a_region_with_an_island_asks_for_the_token(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-live/>", request=request)
    assert cookie_sent(request, html)


def test_a_static_region_does_not(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-still/>", request=request)
    assert not cookie_sent(request, html)


def test_an_island_in_a_django_block_asks_for_the_token(render, rf):
    request = rf.get("/")
    html = render("<c-csrf-loop c-ns='[1]'/>", request=request)
    assert cookie_sent(request, html)


def test_the_token_is_not_written_into_the_page(render_django, rf):
    request = rf.get("/")
    html = render_django("<c-csrf-live/>", request=request)
    assert request.META["CSRF_COOKIE"] not in html


def test_an_island_in_a_django_block_of_a_region_asks_for_the_token(render_django, rf):
    """The region itself needs no Vue here; only the islands its Django
    block builds once the region has rendered do."""
    request = rf.get("/")
    html = render_django("<c-csrf-loop c-ns='[1]'/>", request=request)
    assert cookie_sent(request, html)
