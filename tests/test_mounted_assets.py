import base64
import gzip
import hashlib
import re
import types

import pytest
from citry import Citry, Component
from citry.ext.events import event
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory

from citry_django import CitryDjangoExtension
from citry_django.urls import packed, urlpatterns


@pytest.fixture
def mounted():
    """An engine whose routes are mounted, as a project's `urls.py` does."""
    app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
    return app, urlpatterns(app, "/citry")


def runtime_view(patterns):
    """The pattern serving the client runtime.

    One level down: the mount wraps Citry's routes in one `include()`.
    """
    nested = patterns[0].url_patterns
    return next(p for p in nested if "citry.js" in str(p.pattern))


def served_file(patterns, file_path, **headers):
    """The response the mount gives for `file_path`, a path below the prefix."""
    nested = patterns[0].url_patterns
    for pattern in nested:
        match = pattern.resolve(file_path)
        if match:
            request = RequestFactory().get(f"/citry/{file_path}", **headers)
            return match.func(request, *match.args, **match.kwargs)
    raise AssertionError(f"no route serves {file_path}")


def sri(content):
    """The `integrity` value a browser computes for `content`."""
    return "sha384-" + base64.b64encode(hashlib.sha384(content).digest()).decode()


def interactive(app, name):
    """A component with its own JS, so a render links Citry's runtime."""

    class Interactive(Component):
        citry = app
        template = "<div>x</div>"
        js = "console.log('interactive')"

    app.register(Interactive, name)
    return Interactive


class TestMounting:
    def test_the_prefix_is_recorded(self, mounted):
        """Without it Citry has nowhere to point a `src` at, so it inlines the
        whole bundle into every page instead."""
        app, _ = mounted
        assert app.mounted_prefix == "/citry"

    def test_minifying_is_refused(self, settings):
        """Citry pins each file with an `integrity` hash, so a browser would
        refuse a minified runtime. Failing at URL loading stops the project
        before it serves such a page."""
        settings.CITRY_MINIFY_ASSETS = True
        app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])

        with pytest.raises(ImproperlyConfigured, match="CITRY_MINIFY_ASSETS was removed"):
            urlpatterns(app, "/citry")
        assert app.mounted_prefix is None

    def test_minifying_turned_off_is_harmless(self, settings):
        settings.CITRY_MINIFY_ASSETS = False
        app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])

        assert urlpatterns(app, "/citry")

    @pytest.mark.parametrize("prefix", ["/citry", "/assets/citry/", "/"])
    def test_the_mount_serves_the_urls_citry_builds(self, settings, client, prefix):
        """Listed at the top of the root URLconf, the routes sit under the
        prefix Citry builds every `src` from, so a linked file is found."""
        app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
        urlconf = types.ModuleType("mounted_site_urls")
        urlconf.urlpatterns = [*urlpatterns(app, prefix)]
        settings.ROOT_URLCONF = urlconf
        # Wagtail's middleware reads the database, which these requests do not need.
        settings.MIDDLEWARE = []

        html = str(interactive(app, "mounted-linked")())
        sources = re.findall(r'<script src="([^"]+)"', html)

        assert sources
        assert all(client.get(src).status_code == 200 for src in sources)

    def test_the_runtime_is_served_as_a_file(self, settings, client):
        """Citry links its runtime by a hash of its content and pins it with
        `integrity`. The mount serves those exact bytes, gzipped or not, so
        the browser accepts them and may keep them for good."""
        app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()])
        urlconf = types.ModuleType("mounted_site_urls")
        urlconf.urlpatterns = [*urlpatterns(app, "/citry")]
        settings.ROOT_URLCONF = urlconf
        settings.MIDDLEWARE = []

        html = str(interactive(app, "mounted-widget")())
        tag = re.search(r'<script src="(/citry/citry\.[0-9a-f]{64}\.js)"([^>]*)>', html)
        assert tag, html
        src, attributes = tag.groups()
        pinned = re.search(r'integrity="(sha384-[^"]+)"', attributes)
        assert pinned
        assert 'crossorigin="anonymous"' in attributes

        plain = client.get(src)
        zipped = client.get(src, HTTP_ACCEPT_ENCODING="gzip")

        assert plain.status_code == zipped.status_code == 200
        assert zipped["Content-Encoding"] == "gzip"
        assert gzip.decompress(zipped.content) == plain.content
        assert sri(plain.content) == pinned.group(1)
        assert plain["Cache-Control"] == "public, max-age=31536000, immutable"
        # Citry's CORS header, which the browser needs to check the integrity
        # of a script it fetches with crossorigin="anonymous".
        assert zipped["Access-Control-Allow-Origin"] == "*"


class TestServing:
    def test_citry_keeps_deciding_how_long_a_file_is_kept(self, mounted):
        """Citry marks a file at a fixed name for revalidation.

        `cache/<class_id>.js` changes with the component, so a browser told to
        keep it for a year would run the old component JS after a deploy.
        """
        app, patterns = mounted

        class Cached(Component):
            citry = app
            template = "<div>x</div>"
            js = "console.log('cached')"

        app.register(Cached, "mounted-cached")
        response = served_file(patterns, f"cache/{Cached.class_id}.js")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-cache"
        assert response["ETag"]

    def test_the_unhashed_runtime_is_not_stored(self, mounted):
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))

        assert response["Cache-Control"] == "no-store"

    def test_a_gzipped_file_keeps_citrys_tag_as_a_weak_one(self, mounted):
        """The gzipped body is a different body, so its ETag is weak. Citry
        compares a returned tag the weak way and still answers 304."""
        app, patterns = mounted

        class Zipped(Component):
            citry = app
            template = "<div>x</div>"
            js = "console.log('zipped')"

        app.register(Zipped, "mounted-zipped")
        url = f"cache/{Zipped.class_id}.js"
        plain = served_file(patterns, url)
        zipped = served_file(patterns, url, HTTP_ACCEPT_ENCODING="gzip")

        assert zipped["ETag"] == f"W/{plain['ETag']}"
        assert zipped["Cache-Control"] == "no-cache"
        again = served_file(
            patterns, url, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=zipped["ETag"]
        )
        # The 304 repeats the tag and the Vary the 200 carried, so a cache
        # holding the gzipped copy may keep using it.
        assert again.status_code == 304
        assert again["ETag"] == zipped["ETag"]
        assert again["Vary"] == "Accept-Encoding"

    def test_a_plain_answer_still_varies_on_accept_encoding(self, mounted):
        """Otherwise a shared cache that first stores the plain body hands
        it to every client after that, gzip-capable or not."""
        _, patterns = mounted
        response = runtime_view(patterns).callback(RequestFactory().get("/citry/citry.js"))

        assert "Content-Encoding" not in response
        assert response["Vary"] == "Accept-Encoding"

    def test_head_gets_the_headers_get_gets(self, mounted):
        _, patterns = mounted
        view = runtime_view(patterns).callback
        get = view(RequestFactory().get("/citry/citry.js", HTTP_ACCEPT_ENCODING="gzip"))
        head = view(RequestFactory().head("/citry/citry.js", HTTP_ACCEPT_ENCODING="gzip"))

        for name in ("Content-Encoding", "Vary", "Cache-Control"):
            assert head[name] == get[name]

    def test_an_endpoint_is_left_alone(self, settings, client):
        """Citry mounts its event endpoints beside the files.

        Those answer each request for one visitor, so the mount must not gzip
        them or change their headers, even when the URL of a GET event ends
        in something that looks like a file name.
        """
        app = Citry(autodiscover=False, extensions=[CitryDjangoExtension()], secret="mounted-" * 6)
        urlconf = types.ModuleType("mounted_site_urls")
        urlconf.urlpatterns = [*urlpatterns(app, "/citry")]
        settings.ROOT_URLCONF = urlconf
        # Wagtail's middleware reads the database, which these requests do not need.
        settings.MIDDLEWARE = []

        class Report(Component):
            citry = app
            template = "<div>x</div>"

            class Events:
                @event(name="export.csv", methods=("GET",), csrf=False)
                def export(self):
                    return {"user": "alice"}

        app.register(Report, "mounted-report")
        response = client.get(
            f"/citry/ext/events/e/{Report.class_id}/export.csv", HTTP_ACCEPT_ENCODING="gzip"
        )

        assert response.status_code == 200
        assert b'"alice"' in response.content
        assert "Content-Encoding" not in response
        # Citry lists X-Citry-Page-Nonce on every event answer; the mount adds nothing.
        assert "Accept-Encoding" not in response.get("Vary", "")
        assert response["Cache-Control"] == "no-store"

    def test_a_body_is_gzipped_once(self, mounted):
        """Around 10 ms for the 400 kB runtime, worth paying on the first
        request and not on every one."""
        _, patterns = mounted
        request = RequestFactory().get("/citry/citry.js", HTTP_ACCEPT_ENCODING="gzip")
        view = runtime_view(patterns).callback
        first = view(request).content
        keys = list(packed)

        assert view(request).content == first
        assert list(packed) == keys

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
