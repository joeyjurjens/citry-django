"""
Static paths as Citry dependencies.

A project writes the paths it already writes; these turn them into the objects
Citry collects, with the ``type`` that tells django-compressor what to compile.
"""

from citry_django import scripts, styles


class TestStyles:
    def test_a_path_becomes_a_static_url(self):
        (style,) = styles(["card/card.css"])
        assert style.url.endswith("card/card.css")
        assert "/static/" in style.url

    def test_no_type_is_invented(self):
        """Naming a preprocessor is django-compressor's business, not this."""
        (style,) = styles(["card/card.scss"])
        assert "type" not in style.attrs

    def test_groups_are_flattened_so_constants_can_be_handed_over(self):
        assert len(styles(["a.css", "b.css"], ["c.css"])) == 3

    def test_a_bare_path_needs_no_list(self):
        (style,) = styles("card/card.css")
        assert style.url.endswith("card/card.css")

    def test_extra_attributes_are_carried(self):
        (style,) = styles(["card/card.css"], media="print")
        assert style.attrs["media"] == "print"

    def test_an_explicit_type_is_carried(self):
        (style,) = styles(["card/card.scss"], type="text/plain")
        assert style.attrs["type"] == "text/plain"


class TestScripts:
    def test_a_path_becomes_a_static_url(self):
        (script,) = scripts(["card/card.js"])
        assert script.url.endswith("card/card.js")

    def test_groups_are_flattened(self):
        assert len(scripts(["a.js"], ["b.js", "c.js"])) == 3

    def test_extra_attributes_are_carried(self):
        (script,) = scripts(["card/card.js"], defer="defer")
        assert script.attrs["defer"] == "defer"
