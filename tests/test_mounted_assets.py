import pytest
from citry import Citry, Component
from django.test import RequestFactory

from citry_django import CitryDjangoExtension
from citry_django.urls import urlpatterns


@pytest.fixture
def mounted():
    """An engine whose routes are mounted, as a project's `urls.py` does."""
    app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
    return app, urlpatterns(app, "/citry")


def runtime_view(patterns):
    """The pattern serving the client runtime."""
    return next(p for p in patterns if "citry.js" in str(p.pattern))


class TestMounting:
    def test_the_prefix_is_recorded(self, mounted):
        """Without it Citry has nowhere to point a `src` at, so it inlines the
        whole bundle into every page instead."""
        app, _ = mounted
        assert app.mounted_prefix == "/citry"

    def test_the_runtime_is_served_as_a_file(self, mounted):
        app, _ = mounted

        class Widget(Component):
            citry = app
            template = '<div x-data="{}">x</div>'

        app.register(Widget, "mounted-widget")
        assert "/citry/citry.js" in str(Widget())


class TestServing:
    def test_the_response_revalidates(self, mounted):
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))
        assert response["Cache-Control"] == "public, max-age=3600"
        assert response["ETag"]

    def test_the_window_is_a_setting(self, mounted, settings):
        settings.CITRY_ASSET_MAX_AGE = 60
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))
        assert response["Cache-Control"] == "public, max-age=60"

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
