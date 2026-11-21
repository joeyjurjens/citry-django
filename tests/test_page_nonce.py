"""The page says which nonce it has, so a swap in any tab gets the right one.

The session keeps one nonce, the last page's. With two tabs open that is the
wrong nonce for the older one, so htmx sends the nonce of the page it is
in with each request (`X-Citry-Page-Nonce`), and the partial's islands use it.
"""

from __future__ import annotations

import pytest

from citry_django.islands import PAGE_NONCE_HEADER, page_nonce_script, sent_page_nonce


@pytest.fixture(autouse=True)
def fixtures(component, citry_app):
    previous = citry_app.mounted_prefix
    citry_app.set_mounted_prefix("/citry")
    component(
        '<b @click="n++">quiet</b>',
        name="nonce-live",
        js_data=lambda self, kwargs, slots: {"n": 0},
    )
    component("<i>still</i>", name="nonce-still")
    yield
    citry_app._mounted_prefix = previous


def page(rf, nonce="pageNonce1234"):
    request = rf.get("/")
    request.csp_nonce = nonce
    return request


def partial(rf, sent=None, nonce="ownNonce12345"):
    extra = {"HTTP_HX_REQUEST": "true"}
    if sent is not None:
        extra["HTTP_X_CITRY_PAGE_NONCE"] = sent
    request = rf.get("/", **extra)
    request.csp_nonce = nonce
    return request


def test_a_page_with_an_island_makes_htmx_send_its_nonce(render_django, rf):
    html = render_django("<c-nonce-live/>", request=page(rf))
    assert '<script nonce="pageNonce1234">(function(n)' in html
    assert PAGE_NONCE_HEADER in html
    assert '"pageNonce1234");</script>' in html


def test_a_page_without_an_island_writes_none(render_django, rf):
    assert PAGE_NONCE_HEADER not in render_django("<c-nonce-still/>", request=page(rf))


def test_a_page_without_a_nonce_writes_none(render_django, rf):
    request = rf.get("/")
    assert PAGE_NONCE_HEADER not in render_django("<c-nonce-live/>", request=request)


def test_several_islands_each_write_a_script_that_registers_once(render_django, rf):
    html = render_django("<c-nonce-live/><c-nonce-live/>", request=page(rf))
    # The guard is in the script, so repeats are harmless.
    assert "window.__citryPageNonce)return" in html


def test_a_partial_writes_none_because_it_lands_in_a_page(render_django, rf):
    html = render_django("<c-nonce-live/>", request=partial(rf, sent="pageNonce1234"))
    assert PAGE_NONCE_HEADER not in html


def test_a_partials_island_carries_the_nonce_the_page_sent(render_django, rf):
    html = render_django("<c-nonce-live/>", request=partial(rf, sent="olderTabNonce1"))
    assert "olderTabNonce1" in html
    assert "ownNonce12345" not in html


def test_the_sent_nonce_wins_over_the_one_kept_in_the_session(render_django, rf):
    request = partial(rf, sent="olderTabNonce1")
    request.session = {"citry_django_csp_nonce": "newerTabNonce1"}
    html = render_django("<c-nonce-live/>", request=request)
    assert "olderTabNonce1" in html
    assert "newerTabNonce1" not in html


@pytest.mark.parametrize(
    "bad", ["short", "has space in it 123", 'quo"te12345678', "<script>alert(1)", "a" * 200]
)
def test_a_header_that_is_not_a_nonce_is_ignored(rf, bad):
    assert sent_page_nonce(partial(rf, sent=bad)) is None


def test_a_nonce_is_escaped_in_the_script(rf):
    script = page_nonce_script(page(rf, nonce='x"</script>'), 'x"</script>')
    assert "</script><" not in script.split("</script>")[0]
    assert script.count("</script>") == 1


def test_a_server_event_client_can_send_the_nonce_too(rf):
    from types import SimpleNamespace

    from citry_django import page_csp_nonce

    request = partial(rf, sent="olderTabNonce1")
    assert page_csp_nonce(SimpleNamespace(native=request)) == "olderTabNonce1"
