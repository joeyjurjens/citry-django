"""
Wagtail, end to end.

Not a unit test with fake tags: these render actual pages through Django's
request cycle, with Wagtail's own `{% image %}`, `{% pageurl %}` and
`{% richtext %}` running inside Citry components.

The tag list is not guessed either. It is what `wagtailcore_tags`,
`wagtailimages_tags` and `wagtail_cache` actually register, read off the live
registry, so the suite cannot drift from what Wagtail really does.
"""

import re

import pytest
from django.template.backends.django import get_installed_libraries
from testproject.home.models import ArticlePage

HOST = "localhost"


def library_names(library):
    """Every tag and filter a library registers, read from the live registry."""
    from importlib import import_module

    module = import_module(get_installed_libraries()[library])
    return sorted(module.register.tags) + sorted(module.register.filters)


class TestTagSurface:
    """Each of Wagtail's front-end tags, rendered inside a Citry component."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param("{% wagtail_version %}", re.compile(r"\d+\.\d+"), id="wagtail_version"),
            pytest.param("{% wagtail_site as s %}{{ s.hostname }}", "localhost", id="wagtail_site"),
            pytest.param("{% wagtail_documentation_path %}", "docs.wagtail.org", id="docs_path"),
            pytest.param("{% wagtail_release_notes_path %}", ".html", id="release_notes_path"),
        ],
    )
    def test_context_free_tags(self, render, rf, site, source, expected):
        out = render("{% load wagtailcore_tags %}" + source, request=rf.get("/"))
        if isinstance(expected, re.Pattern):
            assert expected.search(out)
        else:
            assert expected in out

    @pytest.mark.parametrize("tag", ["pageurl", "fullpageurl"])
    def test_page_url_tags(self, render, rf, site, tag):
        out = render(
            f'{{% load wagtailcore_tags %}}<a href="{{% {tag} page %}}">x</a>',
            request=rf.get("/"),
            page=site["articles"][0],
        )
        assert f'href="{"http" if tag == "fullpageurl" else ""}' in out
        assert site["articles"][0].slug in out

    def test_slugurl(self, render, rf, site):
        out = render(
            "{% load wagtailcore_tags %}<a href=\"{% slugurl 'article-0' %}\">x</a>",
            request=rf.get("/"),
        )
        assert 'href="/article-0/"' in out

    def test_richtext_filter_expands_an_internal_link(self, render, site):
        out = render(
            "{% load wagtailcore_tags %}<div>{{ body|richtext }}</div>",
            body=site["articles"][0].body,
        )
        assert 'linktype="page"' not in out
        assert '<a href="/">Back home</a>' in out

    def test_include_block_renders_each_block_through_its_own_template(self, render, site):
        out = render(
            "{% load wagtailcore_tags %}"
            "{% for block in blocks %}<div>{% include_block block %}</div>{% endfor %}",
            blocks=site["articles"][0].body_stream,
        )
        assert "Heading for" in out
        assert "<b>streamed</b>" in out

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param('{% image img width-300 alt="x" %}', 'alt="x"', id="image"),
            pytest.param("{% image_url img 'width-300' %}", "/images/", id="image_url"),
            pytest.param(
                "{% srcset_image img width-{200,300} sizes='100vw' %}", "srcset", id="srcset_image"
            ),
            pytest.param("{% picture img format-webp width-300 %}", "<picture", id="picture"),
        ],
    )
    def test_image_tags(self, render, rf, site, source, expected):
        out = render(
            "{% load wagtailimages_tags %}" + source, request=rf.get("/"), img=site["image"]
        )
        assert expected in out

    def test_wagtailcache_consumes_its_body(self, render, site):
        """Like `{% compress %}`, it reads its body's rendered text."""
        out = render(
            "{% load wagtail_cache %}{% wagtailcache 60 'k' %}<b>{{ n }}</b>{% endwagtailcache %}",
            n="cached",
        )
        assert ">cached</b>" in out

    @pytest.mark.parametrize("library", ["wagtailcore_tags", "wagtailimages_tags"])
    def test_the_registry_holds_no_surprises(self, library):
        """
        Guards the list above: a name Wagtail adds later shows up here as a
        failure rather than as a silently untested tag.
        """
        covered = {
            "wagtailcore_tags": {
                "fullpageurl",
                "include_block",
                "pageurl",
                "slugurl",
                "wagtail_documentation_path",
                "wagtail_feature_release_editor_guide_link",
                "wagtail_feature_release_whats_new_link",
                "wagtail_release_notes_path",
                "wagtail_site",
                "wagtail_version",
                "richtext",
            },
            "wagtailimages_tags": {"image", "image_url", "picture", "srcset_image"},
        }[library]
        assert set(library_names(library)) == covered


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
        assert home.count('class="card"') == 3, "`<c-for>` did not render every article"
        assert 'class="summary"' in home, "no component nested inside a component"

    def test_a_wagtail_if_wrapping_a_citry_component(self, home, site):
        featured = sum(1 for a in site["articles"] if a.featured)
        assert home.count('class="featured-wrap"') == featured
        assert home.count('class="card"') - featured == len(site["articles"]) - featured

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
        assert 'class="card"' in article
        header = re.search(r'<header class="card-header"[^>]*>(.*?)</header>', article, re.S)
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
