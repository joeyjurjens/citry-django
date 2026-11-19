import json
import re
from pathlib import Path

import pytest
from compressor.css import CssCompressor
from django.conf import settings
from django.template import engines

from citry_django_compressor import GROUPS, Kind, collecting
from islands import islands, runtime_scripts


@pytest.fixture
def render_page(rf):
    """Render through the project's backend, which opens the page the
    compressor works on."""

    def render_source(source, **context):
        request = context.pop("request", rf.get("/"))
        return engines["citry"].from_string(source).render(context, request)

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


def bundle_body(html):
    """What django-compressor wrote for the one stylesheet this page links."""
    (href,) = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html)
    path = href[len(str(settings.COMPRESS_URL)) :]
    return (Path(settings.COMPRESS_ROOT) / path).read_text()


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
    def test_island_code_is_left_out_of_compression(self, render_page):
        """A component with its own `js` is a Vue island, and its code stays
        with the island: Citry's runtime checks those tags, so the compressor
        never touches them."""
        html = render_page("<c-callback-component value='test123'/>")
        assert 'class="callback-test"' in html
        assert 'console.log("callback:"' in html
        assert "CACHE/js" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_js_data_is_serialized(self, render_page):
        """js_data() reaches the island's configuration block."""
        html = render_page("<c-callback-component value='myvalue'/>")

        (config,) = islands(html).configs
        assert "myvalue" in json.dumps(config)

    @pytest.mark.usefixtures("compressor_enabled")
    def test_multiple_callback_instances(self, render_page):
        """Each instance keeps its own data."""
        html = render_page(
            "<c-callback-component value='first'/><c-callback-component value='second'/>"
        )
        assert html.count('class="callback-test"') == 2
        configs = json.dumps(islands(html).configs)
        assert "first" in configs
        assert "second" in configs

    @pytest.mark.usefixtures("compressor_enabled")
    def test_file_based_js_with_callback(self, render_page):
        """A `js_file` component is an island too, with its data in its block."""
        html = render_page("<c-file-callback-component value='filetest'/>")
        assert 'class="file-callback-test"' in html
        assert "filetest" in json.dumps(islands(html).configs)


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
        """Two islands of one component load its code once."""
        html = render_page(
            "<c-callback-component value='a'/><p>x</p><c-callback-component value='b'/>"
        )
        assert html.count('class="callback-test"') == 2
        assert len(islands(html)) == 2
        assert html.count('console.log("callback:"') == 1


class TestMixedAssets:
    """Tests for components with both regular and precompiled assets."""

    @pytest.fixture
    def plain(self, component):
        """A component that needs no Vue, with plain CSS."""
        component('<div class="plain-css">x</div>', name="plain-css", css=".plain-css{color:red}")

    @pytest.mark.usefixtures("compressor_enabled")
    def test_regular_and_scss_land_in_one_file(self, render_page):
        """One stylesheet for both, and the Sass compiled on the way."""
        html = render_page("<c-mixed-component/>")
        assert html.count('rel="stylesheet"') == 1
        assert "/CACHE/css/" in html
        assert "mixed-test" in html
        assert "&.nested" not in html

    @pytest.mark.usefixtures("compressor_enabled", "plain")
    def test_regular_css_is_bundled_too(self, render_page):
        """Not only what needs a precompiler: plain CSS is minified and
        bundled the way `{% compress %}` would on any Django page."""
        html = render_page("<c-plain-css/>")
        assert "/CACHE/css/" in html
        assert ".plain-css{" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_core_scripts_stay_where_citry_put_them(self, render_page):
        """The runtime and an island's own tags are Citry's: its runtime
        checks them, and one island's data belongs to that island."""
        html = render_page("<c-callback-component value='myvalue'/>")
        assert runtime_scripts(html) == 1
        assert len(islands(html).configs) == 1
        assert "CACHE/" not in html

    @pytest.mark.usefixtures("compressor_enabled", "plain")
    def test_multiple_components_compressed_together(self, render_page):
        """Two components with different CSS still produce one stylesheet.

        The whole reason to route Citry's assets through django-compressor: a
        page asks for one file however many components contributed to it.
        """
        html = render_page("<c-scss-component/><c-plain-css/>")
        assert "scss-test" in html
        assert "plain-css" in html
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

        assert extension().typed(plain).attrs.get("type") is None
        assert extension().typed(sass).attrs["type"] == "text/x-scss"

    def test_a_declared_type_wins_over_the_mapping(self, settings):
        from citry.ext.dependencies import Style

        settings.CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}
        declared = Style(url="/static/b.scss", attrs={"type": "text/plain"})

        assert extension().typed(declared).attrs["type"] == "text/plain"

    def test_a_suffix_alone_says_nothing(self):
        """Without that mapping, a `.scss` is source and stays source.

        Reading a type out of the suffix on our own would be this package
        deciding what a file is, and the mimetype has to match the project's
        `COMPRESS_PRECOMPILERS` exactly, so nothing is assumed.
        """
        from citry.ext.dependencies import Style

        assert extension().typed(Style(url="/static/a.scss")).attrs.get("type") is None

    def test_a_cache_busting_query_does_not_hide_the_suffix(self, settings):
        """django-compressor drops one before it resolves the file.

        Reading the suffix off the whole URL would see `.scss?v=2`, match no
        mimetype, and leave the SCSS to reach the browser as SCSS.
        """
        from citry.ext.dependencies import Style

        settings.CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}

        for url in ("/static/b.scss?v=2", "/static/b.scss#top", "/static/b.scss?v=2#top"):
            assert extension().typed(Style(url=url)).attrs["type"] == "text/x-scss", url

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

        One region's render can see no further than itself, so two regions
        holding different components would compress to two files however
        little is in them. The page sees both.
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
    def test_without_a_placeholder_each_region_keeps_its_own_file(self, render_django):
        """Bundling needs somewhere to put the result.

        A page that named no spot for its stylesheets leaves each group where
        Citry put it, so there is one file per region and nothing is left
        saying they could have been one.
        """
        html = render_django("<body><c-bundle-a />x<c-bundle-b /></body>")

        assert len(link_tags(html)) == 2
        assert "data-citry-bundle" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_one_stylesheet_two_regions_is_one_copy(self, render_django, component):
        """The page drops the repeat before django-compressor ever sees it.

        A region that compressed for itself would hand the page a URL of its
        own, and two such URLs holding identical bytes are two different tags.
        Nothing downstream can tell them apart, so both would go in the file.
        """
        from citry.ext.dependencies import Style
        from django.templatetags.static import static

        shared = type(
            "Dependencies",
            (),
            {"css": [Style(url=static("test.scss"), attrs={"type": "text/x-scss"})]},
        )
        component("<div>x</div>", name="shared-x", Dependencies=shared)
        component("<div>y</div>", name="shared-y", Dependencies=shared)

        html = render_django("<head><c-css /></head><body><c-shared-x /><c-shared-y /></body>")

        # The nested selector, because the outer one is a substring of it and
        # so counts twice per copy.
        assert len(link_tags(html)) == 1
        assert bundle_body(html).count("scss-file-test.nested") == 1


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
        component(
            "<div>second file</div>",
            name="kind-file-two",
            Dependencies=type("Dependencies", (), {"js": [Script(url=static("js/demosite.js"))]}),
        )
        component("<section><c-kind-file /><c-kind-file-two /></section>", name="kind-nested")

    @pytest.mark.usefixtures("compressor_enabled", "kinds")
    def test_static_files_are_bundled_and_island_code_is_not(self, render_django):
        """A component's own `js` makes it a Vue island, whose code stays as
        Citry wrote it. A file a component that needs no Vue declares ends up
        in a file of ours."""
        inline = render_django("<body><c-kind-inline /><c-js /></body>")
        from_file = render_django("<body><c-kind-file /><c-js /></body>")

        assert "CACHE/js" not in inline
        assert "console.log('inline')" in inline
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
            "<body><c-kind-nested />x<c-kind-extern />y<c-kind-file /><c-js /></body>"
        )
        sources = script_src_tags(html)

        assert len(sources) == 2
        assert "CACHE/js" in sources[0]
        assert 'src="https://cdn.example.com/lib.js"' in sources[1]


class TestPerInstanceAssets:
    """What must never reach a shared file."""

    @pytest.fixture
    def product(self, component):
        """A component whose look differs per instance. It needs no Vue: an
        island's tags never reach the compressor at all."""
        from citry.ext.dependencies import Script
        from django.templatetags.static import static

        component(
            '<article class="product">{{ name }}</article>',
            name="bundle-product",
            css=".product { color: var(--accent) }",
            Dependencies=type("Dependencies", (), {"js": [Script(url=static("js/demosite.js"))]}),
            Kwargs=type("Kwargs", (), {"__annotations__": {"pk": int, "accent": str}}),
            template_data=lambda self, kwargs, slots: {"name": f"p{kwargs.pk}"},
            css_data=lambda self, kwargs, slots: {"accent": kwargs.accent},
        )

    @staticmethod
    def catalogue(count):
        products = "".join(
            f'<c-bundle-product c-pk="{pk}" c-accent="\'#00000{pk}\'" />'
            for pk in range(1, count + 1)
        )
        return f"<head><c-css /></head><body>{products}<c-js /></body>"

    @staticmethod
    def bundles(html):
        return set(re.findall(r"/static/CACHE/[a-z]+/[a-f0-9]+\.[a-z]+", html))

    @pytest.mark.usefixtures("compressor_enabled", "product")
    def test_many_instances_do_not_make_many_files(self, render_django):
        """A catalogue has 200k products; it does not have 200k stylesheets.

        Citry splits a component's assets in two. What it declares is the same
        for every instance and worth sharing; what `css_data()` returns
        belongs to one render. `shareable()` only offers the first kind, so a
        primary key can never name a file.
        """
        html = render_django(self.catalogue(5))

        assert len(self.bundles(html)) == 2

    @pytest.mark.usefixtures("compressor_enabled", "product")
    def test_instances_that_look_alike_share_one_block(self, render_django):
        """Where the page's deduplication meets Citry's scoping.

        The page drops a tag it has placed already, by its exact markup. Citry
        names these blocks after the data in them and puts the same name on
        the element, so two instances with the same data are one block that
        both elements point at, and dropping the second is right rather than
        lucky.
        """
        html = render_django(
            "<head><c-css /></head><body>"
            '<c-bundle-product c-pk="1" c-accent="\'#aaaaaa\'" />'
            '<c-bundle-product c-pk="2" c-accent="\'#bbbbbb\'" />'
            '<c-bundle-product c-pk="3" c-accent="\'#aaaaaa\'" />'
            "<c-js /></body>"
        )
        blocks = re.findall(r"\[data-ccss-([a-f0-9]+)\]", html)
        elements = re.findall(r'data-ccss-([a-f0-9]+)=""', html)

        assert len(blocks) == 2
        assert len(elements) == 3
        assert set(elements) == set(blocks)

    @pytest.mark.usefixtures("compressor_enabled", "product")
    def test_what_belongs_to_one_render_stays_in_the_page(self, render_django):
        """Bundling it would put one page's data in a file meant to be shared,
        and give every page a file of its own."""
        html = render_django(self.catalogue(3))

        assert html.count("--accent") == 3


class TestCompilingAComponentsOwnFile:
    """A `css_file` arrives as contents, with no URL to read a suffix from."""

    @pytest.fixture
    def badge(self, component, settings):
        settings.CITRY_COMPRESSOR_FILE_TYPES = {".scss": "text/x-scss"}
        component(
            '<span class="badge"><b class="badge-label">x</b></span>',
            name="scss-badge",
            css_file="badge/badge.scss",
            Kwargs=type("Kwargs", (), {"__annotations__": {"accent": str}}),
            css_data=lambda self, kwargs, slots: {"accent": kwargs.accent},
        )

    @pytest.mark.usefixtures("compressor_enabled", "badge")
    def test_it_is_compiled(self, render_django):
        """django-compressor picks its precompiler on the `type` attribute, and
        a `css_file` carries neither that nor a URL to read a suffix from. The
        component knows: `origin_class_id` names the class, Citry looks it up,
        and what it declared as `css_file` says what the file is. Without that
        the Sass reaches the browser as source.
        """
        html = render_django(
            "<head><c-css /></head><body><c-scss-badge c-accent=\"'#ff0000'\" /></body>"
        )
        compiled = Path(settings.COMPRESS_ROOT) / re.search(
            r"CACHE/css/([a-f0-9]+\.css)", html
        ).group(0)

        assert "&-label" not in compiled.read_text()
        assert ".badge-label" in compiled.read_text()

    @pytest.mark.usefixtures("compressor_enabled", "badge")
    def test_its_variables_still_reach_the_page(self, render_django):
        """Compiling happens server-side and a custom property is resolved by
        the browser, so the two do not get in each other's way."""
        html = render_django(
            "<head><c-css /></head><body>"
            "<c-scss-badge c-accent=\"'#ff0000'\" />"
            "<c-scss-badge c-accent=\"'#00ff00'\" />"
            "</body>"
        )

        assert "--accent: #ff0000" in html
        assert "--accent: #00ff00" in html


class NamedCssCompressor(CssCompressor):
    """A project's own compressor, as `COMPRESSORS` would name it."""


class TestTheConfiguredCompressor:
    def test_the_default_is_used_as_it_is(self):
        assert collecting(Kind.CSS) is GROUPS[Kind.CSS][0]

    def test_a_configured_class_is_built_on(self, settings):
        settings.COMPRESSORS = {
            "css": f"{__name__}.NamedCssCompressor",
            "js": "compressor.js.JsCompressor",
        }

        built = collecting(Kind.CSS)

        assert issubclass(built, NamedCssCompressor)
        assert issubclass(built, GROUPS[Kind.CSS][0])
        assert collecting(Kind.CSS) is built


def test_an_empty_attribute_value_is_read_as_empty():
    from citry_django_compressor import PageTag

    tag = PageTag.read('<link rel="stylesheet" href="" media>')

    assert tag.attrs == {"rel": "stylesheet", "href": "", "media": True}
    assert tag.url is None
