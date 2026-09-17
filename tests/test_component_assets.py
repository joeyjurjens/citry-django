"""The two ways a component can name an asset, and what each one gives back."""

import pytest
from citry.ext.dependencies import Script, Style
from django.templatetags.static import static


@pytest.fixture
def own(component):
    """A component whose stylesheet and behaviour are its own."""
    component(
        "<div>slider</div>",
        name="own-slider",
        css_file="details/details.scss",
        js_file="slider/slider.js",
        js_data=lambda self, kwargs, slots: {"slides": 3},
        css_data=lambda self, kwargs, slots: {"accent": "#abcdef"},
    )


@pytest.fixture
def borrowed(component):
    """A component pointing at code it does not own."""
    component(
        "<div>slider</div>",
        name="borrowed-slider",
        Dependencies=type(
            "Dependencies",
            (),
            {
                "css": [Style(url=static("details/details.scss"))],
                "js": [Script(url=static("slider/slider.js"))],
            },
        ),
        js_data=lambda self, kwargs, slots: {"slides": 3},
        css_data=lambda self, kwargs, slots: {"accent": "#abcdef"},
    )


@pytest.mark.usefixtures("own")
class TestItsOwn:
    def test_the_stylesheet_is_read_and_scoped(self, render_django):
        """`css_data()` becomes custom properties on this instance's elements."""
        html = render_django("<body><c-own-slider /></body>")

        assert "--accent: #abcdef" in html
        assert "data-ccss-" in html

    def test_the_callback_is_registered_with_its_data(self, render_django):
        """`$component(...)` is expanded server-side and `js_data()` reaches it,
        which is the whole reason to keep the file here rather than link it."""
        html = render_django("<body><c-own-slider /></body>")

        assert "registerComponent" in html
        assert "slides" in html


@pytest.mark.usefixtures("borrowed")
class TestBorrowed:
    def test_it_is_a_tag_and_nothing_more(self, render_django):
        """A `Dependencies` entry is a URL the browser fetches, the same as
        writing the tag by hand: no registration and no per-render data."""
        html = render_django("<body><c-borrowed-slider /></body>")

        assert "/static/slider/slider.js" in html
        assert "registerComponent" not in html
        assert "--accent" not in html
