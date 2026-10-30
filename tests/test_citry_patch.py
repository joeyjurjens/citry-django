from __future__ import annotations

import json
import re
import sys
import warnings
from importlib import import_module
from importlib.metadata import version
from pathlib import Path

import pytest
from wagtail.blocks import StructBlock

from citry_django import citry_patch

CITRY_VERSION = version("citry")
PATCHED_CITRY = CITRY_VERSION == citry_patch.AFFECTED_VERSION

BLOCKS = [
    "events_only",
    "slotted_only",
    "events_then_slotted",
    "slotted_then_events",
    "events_then_fills",
    "fills_then_events",
    "events_then_js_fills",
    "js_fills_then_events",
]


class Events:
    def ping(self):
        return None


class Fixture:
    """The block a Django template places inside another component's slot."""

    def __init__(self, name):
        class NestedBlock(StructBlock):
            class Meta:
                template = f"nested_blocks/{name}.html"

        self.value = NestedBlock().to_python({})


@pytest.fixture
def mounted(citry_app):
    previous = citry_app.mounted_prefix
    citry_app.set_mounted_prefix("/citry")
    yield
    citry_app._mounted_prefix = previous


@pytest.fixture
def components(component, mounted):
    component('<button @c-click="ping">ping</button>', "patch-probe", Events=Events)
    component("<aside><c-slot/></aside>", "patch-slotted")
    component("<aside><c-slot name='toggle'/><c-slot name='default'/></aside>", "patch-fills")
    component(
        "<aside><c-slot name='toggle'/><c-slot name='default'/></aside>",
        "patch-js-fills",
        js="console.log('patch-js-fills')",
    )
    component("<section><c-slot/></section>", "patch-wrapper")


@pytest.mark.parametrize("name", BLOCKS)
def test_a_block_with_events_renders_inside_another_regions_slot(
    components, render_django, rf, name
):
    html = render_django(
        "{% load wagtailcore_tags %}"
        "<html><head><c-css/></head><body>"
        "<c-patch-wrapper>{% include_block value %}</c-patch-wrapper>"
        "<c-js/></body></html>",
        request=rf.get("/"),
        value=Fixture(name).value,
    )

    assert "<section" in html
    assert ("ping</button>" in html) == ("events" in name)


@pytest.mark.skipif(not PATCHED_CITRY, reason="the manifest differs in other Citry releases")
@pytest.mark.parametrize("name", [name for name in BLOCKS if "events" in name])
def test_the_events_of_such_a_block_reach_the_client(components, render_django, rf, name):
    html = render_django(
        "{% load wagtailcore_tags %}"
        "<html><head><c-css/></head><body>"
        "<c-patch-wrapper>{% include_block value %}</c-patch-wrapper>"
        "<c-js/></body></html>",
        request=rf.get("/"),
        value=Fixture(name).value,
    )

    manifests = re.findall(r"data-citry-events[^>]*>(.*?)</script>", html, re.S)
    assert len(manifests) == 1
    assert len(json.loads(manifests[0])["componentInstances"]) == 1
    assert html.count('data-citry-root=""') == 1


@pytest.mark.skipif(not PATCHED_CITRY, reason="only Citry 0.5.1 is patched")
def test_citry_is_patched_when_it_is_the_release_the_patch_is_for():
    module = import_module("citry.ownership_manifest")

    assert module.citry_django_patched is True
    assert (
        import_module("citry.serialize").prepare_ownership_manifest
        is module.prepare_ownership_manifest
    )


@pytest.mark.skipif(not PATCHED_CITRY, reason="only Citry 0.5.1 is patched")
def test_every_replacement_still_matches_the_citry_source():
    module = import_module("citry.ownership_manifest")
    source = function_source_of(module)

    assert source is not None, "Citry no longer defines prepare_ownership_manifest"
    for old, _ in citry_patch.REPLACEMENTS:
        assert source.count(old) == 1, f"Citry's manifest changed; this no longer matches:\n{old}"
    assert citry_patch.patched_source(source) is not None


@pytest.mark.skipif(PATCHED_CITRY, reason="the patch is applied here")
def test_a_citry_other_than_the_patched_one_is_left_alone():
    module = sys.modules.get("citry.ownership_manifest")

    assert getattr(module, "citry_django_patched", False) is False


def test_patching_does_nothing_for_another_citry_release(monkeypatch):
    monkeypatch.setattr(citry_patch, "version", lambda name: "0.0.0")

    assert citry_patch.apply() is False


@pytest.mark.skipif(not PATCHED_CITRY, reason="only Citry 0.5.1 is patched")
def test_patching_warns_and_leaves_citry_alone_when_the_source_changed(monkeypatch):
    module = import_module("citry.ownership_manifest")
    before = module.prepare_ownership_manifest
    monkeypatch.setattr(module, "citry_django_patched", False, raising=False)
    monkeypatch.setattr(citry_patch, "REPLACEMENTS", [("a line Citry never had", "anything")])

    with pytest.warns(RuntimeWarning, match="could not patch Citry"):
        assert citry_patch.apply() is False
    assert module.prepare_ownership_manifest is before


def test_patched_source_refuses_text_that_no_longer_matches():
    assert citry_patch.patched_source("def prepare_ownership_manifest(): pass") is None


def test_patching_twice_changes_nothing():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert citry_patch.apply() == citry_patch.apply()


def function_source_of(module):
    return citry_patch.function_source(Path(module.__file__).read_text(encoding="utf-8"))
