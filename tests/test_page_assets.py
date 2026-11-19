"""How the page writes the asset tags its regions hand back.

Citry returns a region's tags in three groups: the browser runtime, component
assets, and one island's own tags. The page keeps one copy of each runtime
and component tag, keeps each island's configuration and start script, writes
one stylesheet tag for the islands that share it, and only the component tags
reach `on_page_assets`.
"""

from __future__ import annotations

import json
import re

import pytest
from citry import Citry, Component, Extension
from citry.ext.dependencies import Script

from citry_django import CitryDjangoExtension
from citry_django.registry import citry_app_source
from islands import islands, runtime_scripts


class RecordPageAssets(Extension):
    name = "record_page_assets"

    def __init__(self) -> None:
        self.seen: list = []

    def on_page_assets(self, asset):
        self.seen.append(asset)
        return asset.tags


@pytest.fixture
def recorded(monkeypatch, settings):
    """An engine with mounted routes and a recording extension, set as CITRY_APP."""
    import testproject.citry_app as app_module

    recorder = RecordPageAssets()
    app = Citry(extensions=[CitryDjangoExtension(), recorder], secret="page-assets-" * 4)
    app.set_mounted_prefix("/citry")

    class Live(Component):
        citry = app
        css = ".live{color:red}"
        js = "live()"
        template = "<b>{{ label }}</b>"

    class Other(Component):
        citry = app
        css = ".other{color:blue}"
        js = "other()"
        template = "<i>other</i>"

    class Still(Component):
        citry = app
        css = ".still{color:green}"
        template = "<s>still</s>"

        class Dependencies:
            js = (Script(url="https://cdn.example/still.js"),)

    app.register(Live, "pa-live")
    app.register(Other, "pa-other")
    app.register(Still, "pa-still")
    monkeypatch.setattr(app_module, "page_assets_app", app, raising=False)
    settings.CITRY_APP = "testproject.citry_app:page_assets_app"
    citry_app_source.cache_clear()
    yield recorder
    citry_app_source.cache_clear()


def test_a_spot_takes_runtime_then_component_then_island_tags(recorded, render_django):
    html = render_django(
        "<head><c-css/></head><body>"
        '<c-pa-live label="a"/><p>between</p><c-pa-still/><p>and</p><c-pa-other/>'
        "<c-js/></body>"
    )
    head, body = html.split("</head>")
    found = islands(html)

    assert runtime_scripts(html) == 1
    assert len(found) == len(found.configs) == len(found.starts) == 2
    # Every tag moved to a spot: the region HTML holds only the hosts.
    regions = body[: body.index('<script src="/citry/')]
    assert "<script" not in regions
    assert "<link" not in regions
    assert "<style" not in regions
    # Runtime, then component, then island tags, within each spot.
    assert body.index("/citry/citry.") < body.index("cdn.example/still.js")
    assert body.index("cdn.example/still.js") < body.index("startDocument")
    assert head.index('rel="preload"') < head.index(".still{")
    assert head.index(".still{") < head.index("data-citry-vue-style-app")
    # Two islands, two stylesheet links: each island keeps its own.
    assert head.count("data-citry-vue-style-app") == 2


#: The app ids one island stylesheet tag names.
STYLE_APPS = re.compile(r'data-citry-vue-style-app="(?P<apps>[0-9a-f ]+)"')


def test_islands_of_one_component_share_one_stylesheet_tag(recorded, render_django):
    html = render_django(
        "<head><c-css/></head><body>"
        '<c-pa-live label="a"/><p>between</p><c-pa-live label="b"/>'
        "<c-js/></body>"
    )
    head = html.split("</head>")[0]
    found = islands(html)

    assert len(found) == 2
    # One link names both apps, so each app adopts it and it stays loaded
    # until the last of them is gone.
    [apps] = [match.group("apps").split(" ") for match in STYLE_APPS.finditer(head)]
    assert sorted(apps) == sorted(found.hosts)


def test_without_a_spot_the_shared_stylesheet_stays_with_the_first_island(recorded, render_django):
    html = render_django('<c-pa-live label="a"/><p>between</p><c-pa-live label="b"/>')
    first, second = html.split("<p>between</p>")

    [apps] = [match.group("apps").split(" ") for match in STYLE_APPS.finditer(first)]
    assert sorted(apps) == sorted(islands(html).hosts)
    assert "data-citry-vue-style-app" not in second
    # Each island keeps its own configuration and start script.
    assert len(islands(first).starts) == len(islands(second).starts) == 1


def test_extensions_see_only_component_tags(recorded, render_django):
    render_django(
        "<head><c-css/></head><body><c-pa-live label='a'/><p>x</p><c-pa-still/><c-js/></body>"
    )

    assert sorted(str(asset.kind) for asset in recorded.seen) == ["css", "js"]
    assert all(asset.collected for asset in recorded.seen)
    tags = [tag for asset in recorded.seen for tag in asset.tags]
    assert any(".still{" in tag for tag in tags)
    assert any("cdn.example/still.js" in tag for tag in tags)
    # Neither the runtime nor an island's own tags.
    assert not any("/citry/citry." in tag or "/definitions/" in tag for tag in tags)
    assert not any("data-citry-vue" in tag for tag in tags)


def test_without_a_spot_each_tag_stays_beside_its_region(recorded, render_django):
    html = render_django(
        '<c-pa-live label="a"/><c-pa-still/><p>between</p><c-pa-still/><c-pa-live label="b"/>'
    )
    first, second = html.split("<p>between</p>")

    assert runtime_scripts(first) == 1
    assert runtime_scripts(second) == 0
    # The second island still has its own configuration and start script.
    assert len(islands(second).starts) == 1
    assert "<!--citry-django" not in html


def test_without_a_spot_extensions_see_each_region_on_its_own(recorded, render_django):
    html = render_django("<c-pa-still/><p>between</p><c-pa-other/><p>and</p><c-pa-still/>")

    assert html.count(".still{") == 1
    assert [len(asset.tags) for asset in recorded.seen] == [1, 1]
    assert not any(asset.collected for asset in recorded.seen)


def test_without_a_page_a_region_writes_its_tags_beside_it(recorded, render_django, settings):
    settings.CITRY_COLLECT_PAGE_ASSETS = False
    html = render_django('<c-pa-live label="a"/><p>between</p><c-pa-live label="b"/>')

    assert runtime_scripts(html) == 2
    assert "<!--citry-django" not in html
    assert recorded.seen == []


def test_a_spot_next_to_a_component_is_not_part_of_its_region(recorded, render_django):
    """`<c-pa-still/><c-css/>` is one region and one spot, not one region."""
    html = render_django("<body><p>first</p><c-pa-still/><c-css/></body>")

    assert html.index("<s") < html.index(".still{")


def test_extensions_learn_which_component_declared_each_tag(recorded, render_django):
    render_django("<head><c-css/></head><body><c-pa-still/><c-js/></body>")

    entries = [entry for asset in recorded.seen for entry in asset.entries]
    assert [entry.tag for entry in entries] == [
        tag for asset in recorded.seen for tag in asset.tags
    ]
    # A class id is the class name and a hash of its import path.
    assert len({entry.class_ids for entry in entries}) == 1
    assert all(entry.class_ids[0].startswith("Still_") for entry in entries)
    assert not any(entry.instance for entry in entries)


@pytest.fixture
def i18n_regions(monkeypatch, settings):
    """Two components that translate in the browser, on an engine with i18n."""
    import testproject.citry_app as app_module

    app = Citry(
        extensions=[CitryDjangoExtension()],
        extensions_defaults={"i18n": {"source_locale": "en", "locales": ["en", "de"]}},
        secret="page-assets-i18n-" * 3,
    )
    app.set_mounted_prefix("/citry")

    class First(Component):
        citry = app
        template = """
            <c-i18n c-client="True" tag="main">
              <output v-text="$i18n.tr('title')">x</output>
            </c-i18n>
        """
        messages = """
            title = First
        """

    class Second(Component):
        citry = app
        template = """
            <c-i18n c-client="True" tag="main">
              <output v-text="$i18n.tr('other')">x</output>
            </c-i18n>
        """
        messages = """
            other = Second
        """

    app.register(First, "pa-i18n-first")
    app.register(Second, "pa-i18n-second")
    monkeypatch.setattr(app_module, "page_assets_i18n_app", app, raising=False)
    settings.CITRY_APP = "testproject.citry_app:page_assets_i18n_app"
    citry_app_source.cache_clear()
    yield
    citry_app_source.cache_clear()


@pytest.mark.usefixtures("i18n_regions")
def test_two_regions_with_i18n_share_one_i18n_runtime(render_django):
    """Each island carries its own messages in its configuration block, and
    the i18n runtime they share is written once."""
    html = render_django(
        "<head><c-css/></head><body><c-pa-i18n-first/><p>x</p><c-pa-i18n-second/><c-js/></body>"
    )
    found = islands(html)

    assert len(found) == 2
    assert len(re.findall(r'<script\b[^>]*src="/citry/ext/i18n/runtime\.', html)) == 1
    # No page-wide i18n block that two islands would have to share.
    assert "data-citry-i18n" not in html
    assert all('"i18n"' in json.dumps(config) for config in found.configs)
