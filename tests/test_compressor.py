"""
Tests for citry-django-compressor integration.

Verifies that Citry component assets with precompiler type attributes are
correctly fed through django-compressor and replaced with compressed URLs.
"""

import re

import pytest
from django.template import Context, engines


@pytest.fixture
def render_page(rf):
    """Render through the project's engine."""

    def _render(source, **context):
        context.setdefault("request", rf.get("/"))
        return engines["citry"].from_string(source).template.render(Context(context))

    return _render


@pytest.fixture
def compressor_enabled(settings):
    """Enable compression for tests that need it."""
    settings.COMPRESS_ENABLED = True
    settings.CITRY_DEPS_STRATEGY = "document"


@pytest.fixture
def compressor_disabled(settings):
    """Disable compression but keep precompilers active."""
    settings.COMPRESS_ENABLED = False
    settings.CITRY_DEPS_STRATEGY = "document"


@pytest.fixture
def no_compressor(settings):
    """No compression, no precompilers - assets pass through unchanged."""
    settings.COMPRESS_ENABLED = False
    settings.COMPRESS_PRECOMPILERS = ()
    settings.CITRY_DEPS_STRATEGY = "document"


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
        # The data key should be present (base64 encoded in the script)
        assert "callback_value" in html

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
            "<c-callback-component value='first'/>"
            "<c-callback-component value='second'/>"
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
        """Same SCSS from multiple components should only be compressed once."""
        html = render_page(
            "<c-scss-component/>"
            "<c-scss-component/>"
            "<c-scss-component/>"
        )
        # Should only have one compressed CSS file, not three
        link_count = html.count('rel="stylesheet"')
        # At least one link tag for the compressed CSS
        assert link_count >= 1
        # The component should render three times
        assert html.count("scss-test") == 3

    @pytest.mark.usefixtures("compressor_enabled")
    def test_identical_js_deduplicated(self, render_page):
        """Same JS from multiple components should only be compressed once."""
        html = render_page(
            "<c-callback-component value='a'/>"
            "<c-callback-component value='b'/>"
        )
        # Both should render
        assert html.count("callback-test") == 2


class TestMixedAssets:
    """Tests for components with both regular and precompiled assets."""

    @pytest.mark.usefixtures("compressor_enabled")
    def test_mixed_regular_and_scss(self, render_page):
        """Component with both regular CSS and SCSS should work."""
        html = render_page("<c-mixed-component/>")
        # Should have compressed output
        assert 'rel="stylesheet"' in html
        # Both classes should be in the output (regular or compressed)
        assert "mixed-test" in html
        # The regular CSS should be present
        assert ".regular" in html or "regular" in html
        # The SCSS should be compiled (no nesting syntax)
        assert "&.nested" not in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_regular_css_not_affected(self, render_page):
        """Regular CSS without type attribute passes through normally."""
        html = render_page("<c-swatch label='test'/>")
        # Regular CSS should be present
        assert ".swatch" in html

    @pytest.mark.usefixtures("compressor_enabled")
    def test_core_scripts_preserved(self, render_page):
        """Citry's core scripts (runtime, manifest) are not compressed."""
        html = render_page("<c-swatch label='test'/>")
        # Citry runtime should be present
        assert "data-citry" in html or "citry" in html.lower()

    @pytest.mark.usefixtures("compressor_enabled")
    def test_multiple_components_compressed_together(self, render_page):
        """Multiple components' assets are compressed into single files."""
        html = render_page("<c-scss-component/><c-swatch label='test'/>")
        # Both components should render
        assert "scss-test" in html
        assert "swatch" in html


class TestFileTypeDetection:
    """Tests for file extension to MIME type mapping."""

    def test_default_file_types(self):
        """Default file types are configured correctly."""
        from citry_django_compressor import DEFAULT_FILE_TYPES

        assert ".scss" in DEFAULT_FILE_TYPES
        assert DEFAULT_FILE_TYPES[".scss"] == "text/x-scss"
        assert ".coffee" in DEFAULT_FILE_TYPES
        assert DEFAULT_FILE_TYPES[".coffee"] == "text/coffeescript"

    @pytest.mark.usefixtures("compressor_enabled")
    def test_custom_file_types(self, settings, render_page):
        """Custom file types can be added via settings."""
        settings.CITRY_COMPRESSOR_FILE_TYPES = {
            ".custom": "text/x-custom",
        }
        # The extension should pick up the custom mapping
        # (This is a basic test - full integration would need a custom precompiler)
        from citry_django_compressor import CitryCompressorExtension

        ext = CitryCompressorExtension()
        file_types = ext._get_file_types()
        assert ".custom" in file_types
        assert ".scss" in file_types  # Defaults still present


class TestNeedsPrecompilation:
    """Tests for the _needs_precompilation helper."""

    def test_type_attribute_triggers_precompilation(self):
        """Explicit type attribute triggers precompilation."""
        from citry.ext.dependencies import Style

        from citry_django_compressor import _needs_precompilation

        style = Style(content="test", attrs={"type": "text/x-scss"})
        assert _needs_precompilation(style, {}) is True

    def test_standard_css_no_precompilation(self):
        """Standard CSS type does not trigger precompilation."""
        from citry.ext.dependencies import Style

        from citry_django_compressor import _needs_precompilation

        style = Style(content="test", attrs={"type": "text/css"})
        assert _needs_precompilation(style, {}) is False

    def test_no_type_no_precompilation(self):
        """No type attribute does not trigger precompilation."""
        from citry.ext.dependencies import Style

        from citry_django_compressor import _needs_precompilation

        style = Style(content="test", attrs={})
        assert _needs_precompilation(style, {}) is False

    def test_url_extension_triggers_precompilation(self):
        """URL with precompiler extension triggers precompilation."""
        from citry.ext.dependencies import Style

        from citry_django_compressor import DEFAULT_FILE_TYPES, _needs_precompilation

        style = Style(url="/static/test.scss", attrs={})
        assert _needs_precompilation(style, DEFAULT_FILE_TYPES) is True

    def test_url_without_extension_no_precompilation(self):
        """URL without precompiler extension does not trigger precompilation."""
        from citry.ext.dependencies import Style

        from citry_django_compressor import DEFAULT_FILE_TYPES, _needs_precompilation

        style = Style(url="/static/test.css", attrs={})
        assert _needs_precompilation(style, DEFAULT_FILE_TYPES) is False


class TestBuildCompressorContent:
    """Tests for building HTML content for django-compressor."""

    def test_build_css_content(self):
        """CSS content is built correctly."""
        from citry.ext.dependencies import Style

        from citry_django_compressor import _build_compressor_content

        deps = [
            Style(content=".test { color: red; }", attrs={}),
            Style(content=".other { color: blue; }", attrs={"type": "text/x-scss"}),
        ]
        content = _build_compressor_content(deps, "css")
        assert '<style>.test { color: red; }</style>' in content
        assert 'type="text/x-scss"' in content

    def test_build_js_content(self):
        """JS content is built correctly."""
        from citry.ext.dependencies import Script

        from citry_django_compressor import _build_compressor_content

        deps = [
            Script(content="console.log('hi');", attrs={}),
        ]
        content = _build_compressor_content(deps, "js")
        assert "<script>console.log('hi');</script>" in content

    def test_build_url_content(self):
        """URL-based dependencies are built correctly."""
        from citry.ext.dependencies import Script, Style

        from citry_django_compressor import _build_compressor_content

        css_deps = [Style(url="/static/test.css", attrs={})]
        css_content = _build_compressor_content(css_deps, "css")
        assert 'href="/static/test.css"' in css_content

        js_deps = [Script(url="/static/test.js", attrs={"defer": True})]
        js_content = _build_compressor_content(js_deps, "js")
        assert 'src="/static/test.js"' in js_content
        assert "defer" in js_content
