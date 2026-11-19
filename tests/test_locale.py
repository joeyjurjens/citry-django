"""A region renders in the language Django activated for the request."""

from __future__ import annotations

import logging

import pytest
from citry import Citry, Component
from django.utils import translation

from citry_django import CitryDjangoExtension
from citry_django.i18n import reported
from citry_django.registry import citry_app_source


@pytest.fixture
def i18n_app(monkeypatch, settings):
    """An engine with three locales, and a component that shows its own."""
    import testproject.citry_app as app_module

    app = Citry(
        extensions=[CitryDjangoExtension()],
        extensions_defaults={"i18n": {"source_locale": "en", "locales": ["en", "de", "pt-BR"]}},
    )

    class ShowLocale(Component):
        citry = app

        def template_data(self, kwargs, slots) -> dict:
            return {"locale": self.inject("citry_i18n").locale}

        template = "<b>{{ locale }}</b>"

    app.register(ShowLocale, "show-locale")
    monkeypatch.setattr(app_module, "i18n_app", app, raising=False)
    settings.CITRY_APP = "testproject.citry_app:i18n_app"
    citry_app_source.cache_clear()
    reported.clear()
    yield app
    citry_app_source.cache_clear()


@pytest.mark.parametrize(
    ("language", "locale"),
    [("de", "de"), ("pt-br", "pt-BR"), ("en-us", "en"), ("de-at", "de")],
)
def test_the_region_follows_djangos_language(i18n_app, render_django, language, locale):
    with translation.override(language):
        assert f">{locale}</b>" in render_django("<c-show-locale/>")


def test_an_unknown_language_falls_back_and_says_so_once(i18n_app, render_django, caplog):
    with caplog.at_level(logging.WARNING, logger="citry_django"), translation.override("fr"):
        first = render_django("<c-show-locale/>")
        render_django("<c-show-locale/>")

    assert ">en</b>" in first
    assert [record.getMessage().count("'fr'") for record in caplog.records] == [1]


def test_an_app_without_i18n_renders_as_before(render_django, component):
    component("<i>plain</i>", name="no-i18n")
    with translation.override("de"):
        assert "plain" in render_django("<c-no-i18n/>")
