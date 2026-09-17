import pytest
from citry import Citry, Component
from django.test import RequestFactory

from citry_django import CitryDjangoExtension
from citry_django.urls import release, urlpatterns


@pytest.fixture
def mounted():
    """An engine whose routes are mounted, as a project's `urls.py` does."""
    app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
    return app, urlpatterns(app, "/citry")


def runtime_view(patterns):
    """The pattern serving the client runtime.

    One level down: the mount wraps its routes in a release segment, so that
    every URL Citry builds carries it.
    """
    nested = patterns[0].url_patterns
    return next(p for p in nested if "citry.js" in str(p.pattern))


class TestMounting:
    def test_the_prefix_is_recorded(self, mounted):
        """Without it Citry has nowhere to point a `src` at, so it inlines the
        whole bundle into every page instead."""
        app, _ = mounted
        assert app.mounted_prefix.startswith("/citry/")

    def test_the_prefix_carries_a_release_segment(self, mounted):
        """`Citry.build_url` is the prefix and the route's path, so a segment
        here is in every URL Citry builds.

        Citry names its own routes: `citry.js` is `citry.js` at every version.
        Told to keep one forever, a browser would keep the wrong one after an
        upgrade; under a new segment it is a different file instead.
        """
        app, _ = mounted
        segment = app.mounted_prefix.removeprefix("/citry/")

        assert segment and "/" not in segment
        assert segment == release()

    def test_minifying_changes_the_release(self, settings):
        """It changes the bytes at the same route, so it has to change the URL."""
        plain = release()
        settings.CITRY_MINIFY_ASSETS = True

        assert release() != plain

    def test_the_runtime_is_served_as_a_file(self, mounted):
        app, _ = mounted

        class Widget(Component):
            citry = app
            template = '<div x-data="{}">x</div>'

        app.register(Widget, "mounted-widget")
        assert f"/citry/{release()}/citry.js" in str(Widget())


class TestServing:
    def test_the_response_is_kept_forever(self, mounted):
        """It can be: other bytes arrive under another release segment."""
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))

        assert response["Cache-Control"] == "public, max-age=31536000, immutable"
        assert response["ETag"]

    def test_an_endpoint_is_left_alone(self, mounted):
        """Citry mounts its event endpoints beside the files.

        Those answer per request, in JSON. Telling a browser to keep one for a
        year would break every interactive component on the page.
        """
        _, patterns = mounted
        events = next(
            p for p in patterns[0].url_patterns if str(p.pattern).endswith("ext/events/call")
        )
        response = events.callback(RequestFactory().post("/citry/ext/events/call"))

        assert "Cache-Control" not in response

    def test_a_body_is_gzipped_once(self, mounted):
        """Around 10 ms for the 400 kB runtime, worth paying on the first
        request and not on every one."""
        from citry_django.urls import packed

        _, patterns = mounted
        request = RequestFactory().get("/citry/citry.js", HTTP_ACCEPT_ENCODING="gzip")
        view = runtime_view(patterns).callback
        first = view(request).content
        keys = dict(packed)

        assert view(request).content == first
        assert dict(packed) == keys

    def test_minification_is_off_by_default(self, mounted):
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))
        assert b"\n" in response.content

    def test_minification_shrinks_the_runtime(self, mounted, settings):
        """Citry ships it unminified, and it is not a file staticfiles can see,
        so this is the one place able to shrink it."""
        _, patterns = mounted
        view = runtime_view(patterns).callback
        before = len(view(RequestFactory().get("/citry/citry.js")).content)
        settings.CITRY_MINIFY_ASSETS = True
        after = len(view(RequestFactory().get("/citry/citry.js")).content)
        assert after < before

    def test_a_response_is_gzipped_for_a_client_that_asks(self, mounted):
        """These come from a view, so a web server rule naming a static
        directory never reaches them."""
        _, patterns = mounted
        request = RequestFactory().get("/citry/citry.js", HTTP_ACCEPT_ENCODING="gzip, deflate")
        response = runtime_view(patterns).callback(request)
        assert response["Content-Encoding"] == "gzip"
        assert response["Vary"] == "Accept-Encoding"

    def test_a_client_that_does_not_ask_gets_it_plain(self, mounted):
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))
        assert "Content-Encoding" not in response
