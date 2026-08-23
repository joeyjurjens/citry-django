"""
Real pages, through Django's whole request cycle.

Everything else renders a template. These render a Wagtail site: pages really in
the tree, an image with a real file behind it, and templates that both extend a
base and hold Citry regions.
"""

from __future__ import annotations

import re

import pytest
from testproject.models import ArticlePage

HOST = "localhost"


@pytest.mark.django_db
class TestRenderedPages:
    """The whole request cycle, against pages really in the tree."""

    @pytest.fixture
    def home(self, client, site):
        response = client.get("/", HTTP_HOST=HOST)
        assert response.status_code == 200, response.content[:2000]
        return response.content.decode()

    def test_django_template_layer_still_works(self, home):
        assert "<!DOCTYPE html>" in home, "`{% extends %}` did not run"
        assert "Citry + Wagtail" in home, "`{% block title %}` was not filled"
        assert "/static/css/demosite.css" in home, "`{% static %}` did not run"

    def test_image_tag_generated_a_rendition(self, home):
        rendition = re.search(r'<img[^>]+src="(/media/images/[^"]+)"', home)
        assert rendition, "no /media/images/ <img> found"
        assert "width-600" in rendition.group(1)
        assert 'alt="Citry + Wagtail"' in home

    def test_pageurl_resolved_every_article(self, home, site):
        for article in site["articles"]:
            assert f'href="/{article.slug}/"' in home

    def test_citry_did_its_own_half(self, home):
        assert "3 articles" in home, "expected `{{ len(articles) }}` to have run"
        assert home.count("cui-card article-card") == 3, "`<c-for>` did not render every article"
        assert 'class="summary"' in home, "no component nested inside a component"

    def test_a_wagtail_if_wrapping_a_citry_component(self, home, site):
        featured = sum(1 for a in site["articles"] if a.featured)
        assert home.count('class="featured-wrap"') == featured
        assert home.count("cui-card article-card") - featured == len(site["articles"]) - featured

    def test_citry_syntax_written_in_a_django_template(self, home):
        assert 'class="hero"' in home
        assert 'class="articles"' in home
        # `<c-if cond="len(articles) > 0">`: Citry control flow and a Python
        # expression, compiled by Citry inside a Django template.
        assert 'class="empty"' not in home
        assert "<c-" not in home, "a raw Citry element leaked into the output"

    def test_plain_django_around_the_components(self, home):
        assert "Rendered by Django." in home
        assert "<b>existing</b>" in home, "`{{ intro|safe }}` came through escaped"

    @pytest.fixture
    def article(self, client, site):
        response = client.get(site["articles"][0].url, HTTP_HOST=HOST)
        assert response.status_code == 200, response.content[:2000]
        return response.content.decode()

    def test_richtext_ran_on_the_article_page(self, article):
        assert 'linktype="page"' not in article
        assert '<a href="/">Back home</a>' in article

    def test_both_slots_were_filled_from_the_django_template(self, article):
        """The named fill lands in the header, the default one in the body."""
        assert 'class="aside"' in article
        header = re.search(r'<header class="aside-header"[^>]*>(.*?)</header>', article, re.S)
        assert header, "the component's named slot did not render"
        assert "Filed under <b>Citry + Wagtail</b>" in header.group(1)
        assert "Untitled" not in article, "the fallback showed even though a fill was given"

    def test_a_wagtail_tag_inside_a_region_used_the_templates_own_load(self, article):
        assert '<a href="/">Back</a>' in article
        assert "<c-" not in article


@pytest.mark.django_db
def test_pages_render_identically_to_their_source_intent(client, site):
    """A StreamField rendered through `{% include_block %}` inside a component."""
    html = client.get(site["articles"][0].url, HTTP_HOST=HOST).content.decode()
    assert 'class="stream"' in html
    assert "block-heading" in html and "block-paragraph" in html and "block-image" in html


def test_article_pages_exist(db, site):
    assert ArticlePage.objects.count() == len(site["articles"])
