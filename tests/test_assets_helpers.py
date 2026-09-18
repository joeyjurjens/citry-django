from unittest.mock import patch

from citry_django import scripts, styles


class TestStyles:
    def test_a_path_becomes_a_static_url(self):
        (style,) = styles(["card/card.css"])
        assert style().url.endswith("card/card.css")
        assert "/static/" in style().url

    def test_no_type_is_invented(self):
        """Naming a preprocessor is django-compressor's business, not this."""
        (style,) = styles(["card/card.scss"])
        assert "type" not in style().attrs

    def test_groups_are_flattened_so_constants_can_be_handed_over(self):
        assert len(styles(["a.css", "b.css"], ["c.css"])) == 3

    def test_a_bare_path_needs_no_list(self):
        (style,) = styles("card/card.css")
        assert style().url.endswith("card/card.css")

    def test_extra_attributes_are_carried(self):
        (style,) = styles(["card/card.css"], media="print")
        assert style().attrs["media"] == "print"

    def test_an_explicit_type_is_carried(self):
        (style,) = styles(["card/card.scss"], type="text/plain")
        assert style().attrs["type"] == "text/plain"

    def test_resolving_the_url_is_deferred_until_the_entry_is_called(self):
        """Declaring an asset must never itself call `static()`.

        `Dependencies.css = styles([...])` runs in a component's class body,
        at import time - the same moment any `manage.py` subcommand,
        `collectstatic` included, first loads the app. `static()` needs the
        hashed manifest `collectstatic` produces to already exist, which on
        a fresh `STATIC_ROOT` is exactly what has not happened yet; a helper
        for declaring an asset must not be able to make `collectstatic`
        itself unable to run.
        """
        with patch("citry_django.assets.static") as mock_static:
            (style,) = styles(["card/card.css"])
            mock_static.assert_not_called()

            style()
            mock_static.assert_called_once_with("card/card.css")


class TestScripts:
    def test_a_path_becomes_a_static_url(self):
        (script,) = scripts(["card/card.js"])
        assert script().url.endswith("card/card.js")

    def test_groups_are_flattened(self):
        assert len(scripts(["a.js"], ["b.js", "c.js"])) == 3

    def test_extra_attributes_are_carried(self):
        (script,) = scripts(["card/card.js"], defer="defer")
        assert script().attrs["defer"] == "defer"

    def test_resolving_the_url_is_deferred_until_the_entry_is_called(self):
        with patch("citry_django.assets.static") as mock_static:
            (script,) = scripts(["card/card.js"])
            mock_static.assert_not_called()

            script()
            mock_static.assert_called_once_with("card/card.js")
