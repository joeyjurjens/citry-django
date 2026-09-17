import pytest

from citry_django.finders import ComponentFinder


@pytest.fixture
def components(tmp_path):
    """A component directory, the way a component is written."""
    details = tmp_path / "details"
    details.mkdir()
    (details / "details.py").write_text("class Details: ...")
    (details / "details.html").write_text("<details></details>")
    (details / "details.scss").write_text(".theme-details {}")
    (details / "details.js").write_text("console.log('x')")
    return tmp_path


@pytest.fixture
def finder(components):
    """The finder, pointed at that directory the way Citry points at it."""

    class Finder(ComponentFinder):
        def dirs(self):
            return (components,)

    return Finder()


class TestFinding:
    def test_an_asset_beside_a_component_is_found(self, finder, components):
        """What `styles(["details/details.scss"])` asks Django to resolve."""
        assert finder.find("details/details.scss") == str(components / "details" / "details.scss")
        assert finder.find("details/details.js") == str(components / "details" / "details.js")

    def test_a_component_is_not_a_static_file(self, finder):
        """A component directory is the one place where a `.py` and a `.html`
        sit beside files a browser may have."""
        assert not finder.find("details/details.py")
        assert not finder.find("details/details.html")

    def test_a_missing_file_is_not_found(self, finder):
        assert not finder.find("details/nothing.scss")


class TestCollecting:
    def test_collectstatic_sees_only_what_it_should(self, finder):
        """`list()` is what `collectstatic` walks."""
        listed = {path for path, _storage in finder.list([])}

        assert listed == {"details/details.scss", "details/details.js"}


class TestConfiguring:
    def test_it_reports_a_directory_that_is_not_there(self, tmp_path):
        class Finder(ComponentFinder):
            def dirs(self):
                return (tmp_path / "gone",)

        assert [error.id for error in Finder().check()] == ["citry_django.W001"]

    def test_it_serves_what_citry_searches(self, citry_app):
        """One list of directories, so the two cannot drift apart: what Citry
        resolves is what Django can find and `collectstatic` collects."""
        assert ComponentFinder().dirs() == tuple(citry_app.settings.dirs)


class TestTheWholeChain:
    """What the finder is for, end to end."""

    def test_a_stylesheet_beside_a_component_is_compiled_and_served(self, settings):
        """A `.scss` in a component directory, through Django's own concept.

        Citry resolves it against its `dirs`, the finder exposes those same
        directories to staticfiles, and django-compressor reads it from there
        like any other static file. Nothing in the compressor package knows
        about components.
        """
        from testproject.components.details.details import Details

        settings.COMPRESS_ENABLED = True
        html = str(Details())

        assert "/static/CACHE/css/" in html
        assert "theme-details" in html
