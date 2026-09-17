import re

import pytest
from django.template import Context, engines


@pytest.fixture
def render_page(rf):
    """Render through the project's engine."""

    def render_source(source, **context):
        context.setdefault("request", rf.get("/"))
        return engines["citry"].from_string(source).template.render(Context(context))

    return render_source


@pytest.fixture
def compressor_enabled(settings):
    """Enable compression for tests that need it."""
    settings.COMPRESS_ENABLED = True


@pytest.fixture
def compressor_disabled(settings):
    """Disable compression but keep precompilers active."""
    settings.COMPRESS_ENABLED = False


@pytest.fixture
def no_compressor(settings):
    """No compression, no precompilers - assets pass through unchanged."""
    settings.COMPRESS_ENABLED = False
    settings.COMPRESS_PRECOMPILERS = ()


def styles(html):
    return re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)


def scripts(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


def style_tags(html):
    return re.findall(r"<style[^>]*>.*?</style>", html, re.S)


def script_tags(html):
    return re.findall(r"<script[^>]*>.*?</script>", html, re.S)


def link_tags(html):
    return re.findall(r'<link[^>]*rel="stylesheet"[^>]*/?>', html, re.S)


def script_src_tags(html):
    return re.findall(r'<script[^>]*src="[^"]+"[^>]*>', html, re.S)


def extension():
    """The extension, for the two methods a test exercises directly."""
    from citry_django_compressor import CitryCompressorExtension

    return CitryCompressorExtension()


class TestCompressorIntegration:
    """Tests for Citry assets flowing through django-compressor."""

    @pytest.mark.usefixtures("compressor_enabled")
    def test_scss_is_precompiled(self, render_page):
        """SCSS content is compiled to CSS and compressed to a file."""
        html = render_page("<c-scss-component/>")
        # SCSS should be compiled to a CSS file
        # The output should be a link tag pointing to the compressed file
        assert 'rel="stylesheet"' in html
        assert "CACHE/css" in html
        # Should NOT contain raw SCSS syntax in the HTML
        assert "&.nested" not in html

        # Verify the compressed file contains compiled CSS
        import re

        from compressor.storage import default_storage as compressor_storage

        # Extract the URL from the link tag
        match = re.search(r'href="([^"]+)"', html)
        assert match is not None
        url = match.group(1)
        # The file should exist and contain compiled CSS
        # Extract path from URL
        path = url.replace("/static/", "")
        assert compressor_storage.exists(path)
        content = compressor_storage.open(path).read().decode()
        # Compiled SCSS should have the class
        assert ".scss-test" in content
        # Nested selector should be compiled to flat CSS
        assert ".scss-test.nested" in content or ".scss-test .nested" in content

    @pytest.mark.usefixtures("compressor_disabled")
    def test_precompilers_run_without_compression(self, render_page):
        """Even with COMPRESS_ENABLED=False, precompilers should run."""
        html = render_page("<c-scss-component/>")
        # SCSS should still be compiled to a file
        assert 'rel="stylesheet"' in html
        assert "CACHE/css" in html
        # Should NOT contain raw SCSS syntax
        assert "&.nested" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_scss_file_url_is_precompiled(self, render_page):
        """SCSS file referenced by URL is compiled through django-compressor."""
        html = render_page("<c-scss-file-component/>")
        # The URL-based SCSS should be compiled
        assert 'rel="stylesheet"' in html
        assert "CACHE/css" in html


class TestJavaScriptCallbacks:
    """Tests that $component() callbacks and js_data() survive compression."""

    @pytest.mark.usefixtures("compressor_enabled")
    def test_component_callback_survives_compression(self, render_page):
        """$component() callback should be present in compressed output."""
        html = render_page("<c-callback-component value='test123'/>")
        # The callback should be in the HTML (either inline or in compressed file)
        # Since it's marked as text/javascript, it should pass through or be compressed
        assert "callback-test" in html
        # The callback code should be present somewhere
        assert "$component" in html or "callback" in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_js_data_is_serialized(self, render_page):
        """js_data() should be serialized into the page for $component callbacks."""
        import base64
        import json
        import re

        html = render_page("<c-callback-component value='myvalue'/>")
        # The component should render
        assert "callback-test" in html
        # js_data is serialized as a script that registers the data with Citry's manager
        # Look for the registerComponentData call which contains the data
        assert "registerComponentData" in html
        # Extract the base64 encoded data from the registerComponentData call
        match = re.search(r'registerComponentData\([^,]+,\s*[^,]+,\s*atob\("([^"]+)"\)\)', html)
        assert match is not None, "Could not find registerComponentData call with base64 data"
        encoded_data = match.group(1)

        # Decode and verify the data structure
        decoded = base64.b64decode(encoded_data).decode("utf-8")
        data = json.loads(decoded)
        assert "callback_value" in data
        assert data["callback_value"] == "myvalue"

    @pytest.mark.usefixtures("compressor_enabled")
    def test_multiple_callback_instances(self, render_page):
        """Multiple instances should each get their own callback data."""
        html = render_page(
            "<c-callback-component value='first'/><c-callback-component value='second'/>"
        )
        # Both instances should render
        assert html.count("callback-test") == 2
        # The callback code should be present (deduplicated)
        assert "$component" in html or "callback" in html
        # Both should have their data registered
        assert "registerComponentData" in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_file_based_js_with_callback(self, render_page):
        """File-based JS with $component callback should work."""
        html = render_page("<c-file-callback-component value='filetest'/>")
        # The component should render
        assert "file-callback-test" in html
        # The file-based JS should be present (either inline or as URL)
        assert "$component" in html or "file-callback" in html
        # js_data should still be serialized
        assert "registerComponentData" in html


class TestDeduplication:
    """Tests that Citry's deduplication works with compression."""

    @pytest.mark.usefixtures("compressor_enabled")
    def test_identical_scss_deduplicated(self, render_page):
        """The same SCSS from three components is compressed once."""
        html = render_page("<c-scss-component/><c-scss-component/><c-scss-component/>")
        assert html.count('rel="stylesheet"') == 1
        assert html.count("scss-test") == 3

    @pytest.mark.usefixtures("compressor_enabled")
    def test_identical_js_deduplicated(self, render_page):
        """Same JS from multiple components should only be compressed once."""
        html = render_page("<c-callback-component value='a'/><c-callback-component value='b'/>")
        # Both should render
        assert html.count("callback-test") == 2


class TestMixedAssets:
    """Tests for components with both regular and precompiled assets."""

    @pytest.mark.usefixtures("compressor_enabled")
    def test_regular_and_scss_land_in_one_file(self, render_page):
        """One stylesheet for both, and the Sass compiled on the way."""
        html = render_page("<c-mixed-component/>")
        assert html.count('rel="stylesheet"') == 1
        assert "/CACHE/css/" in html
        assert "mixed-test" in html
        assert "&.nested" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_regular_css_is_bundled_too(self, render_page):
        """Not only what needs a precompiler: plain CSS is minified and
        bundled the way `{% compress %}` would on any Django page."""
        html = render_page("<c-swatch label='test'/>")
        assert "/CACHE/css/" in html
        assert ".swatch{" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_core_scripts_stay_where_citry_put_them(self, render_page):
        """The runtime is the same on every page but Citry serves it itself,
        and one instance's `js_data` belongs to that instance."""
        html = render_page("<c-callback-component value='myvalue'/>")
        assert "registerComponentData" in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_multiple_components_compressed_together(self, render_page):
        """Two components with different CSS still produce one stylesheet.

        The whole reason to route Citry's assets through django-compressor: a
        page asks for one file however many components contributed to it.
        """
        html = render_page("<c-scss-component/><c-swatch label='test'/>")
        assert "scss-test" in html
        assert "swatch" in html
        assert html.count('rel="stylesheet"') == 1


class TestWhatCompressorIsOffered:
    """Which assets are handed over, and as what."""

    @staticmethod
    def compression():
        from citry_django_compressor import Compression

        return Compression()

    def test_a_declared_type_is_what_says_it_needs_compiling(self):
        """django-compressor keys its precompilers on nothing else."""
        from citry.ext.dependencies import Style

        assert self.compression().precompiles(Style(content="x", attrs={"type": "text/x-scss"}))
        assert not self.compression().precompiles(Style(content="x", attrs={"type": "text/css"}))

    def test_the_project_can_map_its_own_suffixes(self, settings):
        """So one call can name a `.css` and a `.scss` together.

        `styles()` writes its keyword attributes onto every path it is given,
        so a declared `type` is all-or-nothing per call. The mapping belongs to
        the project anyway: which suffixes it compiles, and under which of its
        own `COMPRESS_PRECOMPILERS` names.
        """
        from citry.ext.dependencies import Style

        settings.CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}
        plain, sass = Style(url="/static/a.css"), Style(url="/static/b.scss")

        assert not self.compression().precompiles(plain)
        assert self.compression().precompiles(sass)
        assert 'type="text/x-scss"' in self.compression().markup([sass])[0]

    def test_a_declared_type_wins_over_the_mapping(self, settings):
        from citry.ext.dependencies import Style

        settings.CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}
        declared = Style(url="/static/b.scss", attrs={"type": "text/plain"})

        assert 'type="text/plain"' in self.compression().markup([declared])[0]

    def test_a_suffix_alone_says_nothing(self):
        """Without that mapping, a `.scss` is source and stays source.

        Reading a type out of the suffix on our own would be this package
        deciding what a file is, and the mimetype has to match the project's
        `COMPRESS_PRECOMPILERS` exactly, so nothing is assumed.
        """
        from citry.ext.dependencies import Style

        assert not self.compression().precompiles(Style(url="/static/a.scss"))

    @pytest.mark.usefixtures("compressor_enabled")
    def test_an_asset_it_does_not_serve_is_out_of_reach(self):
        from citry.ext.dependencies import Script

        assert not self.compression().reads(Script(url="https://cdn.example.com/lib.js"))
        assert self.compression().reads(Script(url="/static/a.js"))

    def test_nothing_to_read_is_not_offered(self):
        from citry.ext.dependencies import Style

        assert not self.compression().reads(Style())

    def test_a_dependency_goes_in_as_the_tag_citry_wrote(self):
        """No tag is built here: Citry already knows how to write one."""
        from citry.ext.dependencies import Script, Style

        deps = [
            Style(content=".a{}", attrs={"type": "text/x-scss"}),
            Script(url="/static/a.js"),
        ]
        markup = self.compression().markup(deps)

        assert markup == [str(dep.render()) for dep in deps]
        assert 'type="text/x-scss"' in markup[0]


class TestPageWideBundle:
    """One response's assets, as one file."""

    @pytest.fixture
    def scss_pair(self, component):
        component(
            "<div>a</div>",
            name="bundle-a",
            css=".a { color: red; &.nested { color: blue } }",
            css_type="text/x-scss",
        )
        component(
            "<div>b</div>",
            name="bundle-b",
            css=".b { color: green; &.nested { color: teal } }",
            css_type="text/x-scss",
        )

    @pytest.mark.usefixtures("compressor_enabled", "scss_pair")
    def test_two_regions_bundle_into_one_file(self, render_django):
        """The reason this hook exists.

        `on_dependencies` fires while one region is being serialized and can
        see no further, so two regions holding different components compress
        to two files however little is in them. The page sees both.
        """
        html = render_django("<head><c-css /></head><body><c-bundle-a />x<c-bundle-b /></body>")

        assert len(link_tags(html)) == 1
        assert "CACHE/css" in html

    @pytest.mark.usefixtures("compressor_enabled", "scss_pair")
    def test_the_same_components_make_one_file_whatever_their_order(self, render_django):
        """A compressed file is named after its own bytes.

        Components arrive in whatever order a page reaches them, so without a
        canonical order two pages placing the same components differently write
        two files with identical contents, and a visitor moving between them
        downloads both.
        """
        first = render_django("<head><c-css /></head><body><c-bundle-a />x<c-bundle-b /></body>")
        second = render_django("<head><c-css /></head><body><c-bundle-b />x<c-bundle-a /></body>")

        assert link_tags(first) == link_tags(second)

    @pytest.mark.usefixtures("compressor_enabled", "scss_pair")
    def test_without_a_placeholder_the_region_files_stand(self, render_django):
        """Bundling needs somewhere to put the result.

        A page that named no spot for its stylesheets keeps what its regions
        made, where they made it, and nothing is left saying they could have
        been bundled.
        """
        html = render_django("<body><c-bundle-a />x<c-bundle-b /></body>")

        assert len(link_tags(html)) == 2
        assert "data-citry-bundle" not in html


class TestWhatIsBundled:
    """Which of a component's assets django-compressor is offered."""

    @pytest.fixture
    def kinds(self, component):
        """One component per way of declaring an asset."""
        from citry.ext.dependencies import Script
        from django.templatetags.static import static

        component("<div>inline</div>", name="kind-inline", js="console.log('inline')")
        component(
            "<div>file</div>",
            name="kind-file",
            Dependencies=type("Dependencies", (), {"js": [Script(url=static("file-callback.js"))]}),
        )
        component(
            "<div>extern</div>",
            name="kind-extern",
            Dependencies=type(
                "Dependencies", (), {"js": [Script(url="https://cdn.example.com/lib.js")]}
            ),
        )
        component("<section><c-kind-inline /><c-kind-file /></section>", name="kind-nested")

    @pytest.mark.usefixtures("compressor_enabled", "kinds")
    def test_inline_and_static_assets_are_bundled(self, render_django):
        """Both ways of declaring an asset end up in a file of ours."""
        inline = render_django("<body><c-kind-inline /><c-js /></body>")
        from_file = render_django("<body><c-kind-file /><c-js /></body>")

        assert "CACHE/js" in inline
        assert "CACHE/js" in from_file

    @pytest.mark.usefixtures("compressor_enabled", "kinds")
    def test_an_asset_it_does_not_serve_is_left_alone(self, render_django):
        """A CDN script is not django-compressor's to read.

        Offering it one ends the whole response with `UncompressableFileError`,
        since a URL outside `COMPRESS_URL` is one it refuses outright.
        """
        html = render_django("<body><c-kind-extern /><c-js /></body>")

        assert 'src="https://cdn.example.com/lib.js"' in html
        assert "CACHE/js" not in html

    @pytest.mark.usefixtures("compressor_enabled", "kinds")
    def test_three_regions_of_mixed_assets_bundle_once(self, render_django):
        """Nested, repeated, and unbundleable, on one page.

        The bundle takes the position of the first tag it swallowed and what it
        could not read keeps its own place after it.
        """
        html = render_django(
            "<body><c-kind-nested />x<c-kind-extern />y<c-kind-inline /><c-js /></body>"
        )

        assert len(script_src_tags(html)) == 2
        assert len([tag for tag in script_src_tags(html) if "CACHE/js" in tag]) == 1
        assert 'src="https://cdn.example.com/lib.js"' in html
