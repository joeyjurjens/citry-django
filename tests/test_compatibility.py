"""
Real packages, installed and unmodified.

The adapter names no tag, no loader and no framework, so the way to show that
is to point it at things people actually install and check they behave as they
would without it. Each class here covers one shape of integration that could
plausibly break.
"""

from __future__ import annotations

import re

import pytest
from django import forms
from django.template.backends.django import get_installed_libraries
from django_components import Component as DjcComponent
from django_components import registry as djc_registry

from citry_django.backend import CitryTemplates


def library_names(library):
    """Every tag and filter a library registers, read from the live registry."""
    from importlib import import_module

    module = import_module(get_installed_libraries()[library])
    return sorted(module.register.tags) + sorted(module.register.filters)


class Contact(forms.Form):
    name = forms.CharField(label="Name")
    email = forms.EmailField(label="Email")


@pytest.fixture
def same(render, render_vanilla, strip_cids):
    """Render through both engines and require the Citry one to match Django."""

    def check(source, **context):
        expected = render_vanilla(source, **context)
        actual = strip_cids(render(source, **context))
        assert actual.strip() == expected.strip()

    return check


class TestTagLibraries:
    """
    Third-party tags and filters, each picked for an awkward shape.

    ``{% compress %}`` reads its own body to hash it. ``{% crispy %}`` renders a
    form through the library's own templates and is ``takes_context``.
    ``{% thumbnail %}`` binds a variable for the length of its body.
    ``{% render_field %}`` takes arbitrary keyword arguments.
    """

    @pytest.mark.parametrize(
        ("source", "context"),
        [
            pytest.param(
                "{% load compress %}{% compress css %}"
                '<style type="text/css">.a{color:red}</style>'
                "{% endcompress %}",
                {},
                id="compress-css",
            ),
            pytest.param(
                "{% load crispy_forms_tags %}{% crispy form %}", {"form": Contact}, id="crispy-tag"
            ),
            pytest.param(
                "{% load crispy_forms_filters %}{{ form|crispy }}",
                {"form": Contact},
                id="crispy-filter",
            ),
            pytest.param(
                "{% load widget_tweaks %}{% render_field form.name "
                'class="form-control" placeholder="Your name" %}',
                {"form": Contact},
                id="render_field",
            ),
            pytest.param(
                '{% load widget_tweaks %}{{ form.email|add_class:"x" }}',
                {"form": Contact},
                id="add_class",
            ),
            pytest.param("{% load humanize %}{{ n|intcomma }}", {"n": 1234567}, id="intcomma"),
            pytest.param("{% load humanize %}{{ n|apnumber }}", {"n": 4}, id="apnumber"),
            pytest.param("{% load humanize %}{{ n|ordinal }}", {"n": 23}, id="ordinal"),
            pytest.param(
                '{% load django_bootstrap5 %}{% bootstrap_button "Save" button_type="submit" %}',
                {},
                id="bootstrap_button",
            ),
            pytest.param(
                "{% load django_bootstrap5 %}{% bootstrap_form form %}",
                {"form": Contact},
                id="bootstrap_form",
            ),
        ],
    )
    def test_matches_a_plain_django_render(self, same, source, context):
        # Forms go in as the class so each engine builds its own instance; a
        # shared bound form would compare its own generated ids.
        same(source, **{k: v() if isinstance(v, type) else v for k, v in context.items()})

    def test_a_body_hashing_tag_receives_real_text(self, render):
        """`{% compress %}` can only rewrite a body it actually received."""
        out = render(
            "{% load compress %}{% compress css %}"
            '<style type="text/css">.a{color:{{ shade }}}</style>'
            "{% endcompress %}",
            shade="red",
        )
        assert "<style" in out or "<link" in out
        assert "{{" not in out and "\x00" not in out

    def test_a_tag_that_binds_a_variable_its_body_reads(self, render, site):
        """
        sorl-thumbnail binds `th` for the length of its body, and the
        interpolation inside reads it. Django binds names at render time, so
        this only works against the live context.
        """
        out = render(
            '{% load thumbnail %}{% thumbnail img.file "100x100" as th %}'
            '<img src="{{ th.url }}" width="{{ th.width }}">'
            "{% endthumbnail %}",
            img=site["image"],
        )
        assert "/media/cache/" in out
        assert 'width="100"' in out

    def test_a_library_tag_inside_a_citry_loop(self, render):
        out = render(
            '{% load humanize %}<ul><c-for each="i in nums"><li>{{ i }}</li></c-for></ul>',
            nums=[1, 2],
        )
        assert out.count("<li>") == 2

    def test_a_citry_expression_beside_a_library_filter(self, render):
        out = render(
            "{% load humanize %}<p>{{ ', '.join(names) }}</p><p>{{ n|intcomma }}</p>",
            names=["a", "b"],
            n=9999,
        )
        assert "a, b" in out and "9,999" in out

    def test_a_library_tag_inside_a_nested_component(self, render, component):
        component(
            '{% load widget_tweaks %}<div class="row">{% render_field field class="fc" %}</div>',
            name="field-row",
        )
        out = render("""<c-field-row c-field="form['name']"/>""", form=Contact())
        assert 'class="fc"' in out and 'class="row"' in out


class TestWagtailTags:
    """
    Wagtail's whole front-end tag surface, inside Citry components.

    The list is not guessed. `test_the_registry_holds_no_surprises` compares it
    against what the libraries actually register, so a tag Wagtail adds later
    shows up as a failure rather than as a silently untested one.
    """

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


class TestNodeInspectingTags:
    """
    Tags that walk their own nodelist rather than rendering it.

    `{% wagtail_block %}` and `{% block_field %}` look for specific node *types*
    in their body, assemble a raw value from what they find, and hand it to
    Wagtail. A stand-in node in the body would be invisible to them, so the
    field would silently come out empty.
    """

    @pytest.fixture
    def block(self, render):
        def _render(source, **context):
            return render("{% load wagtail_block_components %}" + source, **context)

        return _render

    def test_keyword_arguments(self, block, db):
        assert "From kwargs" in block(
            '{% wagtail_block "AccordionItemBlock" title="From kwargs" / %}'
        )

    def test_a_field_with_body_content(self, block, db):
        out = block(
            '{% wagtail_block "AccordionItemBlock" %}'
            '{% block_field "title" %}Question {{ n }}{% endblock_field %}'
            "{% endwagtail_block %}",
            n=1,
        )
        assert "Question 1" in out

    def test_a_field_shorthand_with_a_variable(self, block, db):
        out = block(
            '{% wagtail_block "AccordionItemBlock" %}'
            '{% block_field "title" heading / %}'
            "{% endwagtail_block %}",
            heading="From a variable",
        )
        assert "From a variable" in out

    def test_a_streamblock_with_nested_typed_fields(self, block, db):
        out = block(
            '{% wagtail_block "AccordionItemBlock" title="T" %}'
            '{% block_field "content" %}'
            '{% block_field "paragraph" %}<p>First</p>{% endblock_field %}'
            '{% block_field "paragraph" %}<p>Second</p>{% endblock_field %}'
            "{% endblock_field %}"
            "{% endwagtail_block %}"
        )
        assert "First" in out and "Second" in out

    def test_a_listblock_repeating_one_field(self, block, db):
        out = block(
            '{% wagtail_block "AccordionBlock" %}'
            '{% block_field "items" %}'
            '{% wagtail_block "AccordionItemBlock" title="One" / %}'
            "{% endblock_field %}"
            '{% block_field "items" %}'
            '{% wagtail_block "AccordionItemBlock" title="Two" / %}'
            "{% endblock_field %}"
            "{% endwagtail_block %}"
        )
        assert "One" in out and "Two" in out and 'class="accordion"' in out

    def test_a_citry_component_inside_a_field_body(self, block, component, db):
        """
        The tag renders this body with `nodelist.render()`, so the adapter has
        to return real text at exactly that point.

        `title` is a CharBlock, so Wagtail escapes what it is given. The markup
        arriving escaped is the proof: the tag received the component's real
        rendered text, not a stand-in and not the source.
        """
        component('<em class="badge">{{ text }}</em>', name="block-badge")
        out = block(
            '{% wagtail_block "AccordionItemBlock" %}'
            '{% block_field "title" %}<c-block-badge text="Cited"/>{% endblock_field %}'
            "{% endwagtail_block %}"
        )
        assert "Cited" in out
        assert "&lt;em" in out
        assert "<c-block-badge" not in out

    def test_a_block_tag_inside_a_citry_loop(self, block, db):
        # `title=i` is Django's own kwarg syntax, reading the loop variable
        # Citry bound. `c-title` is Citry element syntax, which a Django tag has
        # no reason to understand.
        out = block(
            '<c-for each="i in items">{% wagtail_block "AccordionItemBlock" title=i / %}</c-for>',
            items=["Alpha", "Beta"],
        )
        assert "Alpha" in out and "Beta" in out


class TestTemplateLoaders:
    """
    A project's own loaders keep working, and keep rewriting.

    Rewriting is added to whichever loader finally reads the file rather than by
    substituting loader classes, so a package that ships a loader of its own is
    not a special case. Configuring `loaders` used to silently disable Citry
    syntax in template files while leaving it working in strings.
    """

    @pytest.fixture
    def backend_with(self, tmp_path):
        def build(loaders):
            (tmp_path / "probe.html").write_text('<c-swatch label="from a file"/>')
            return CitryTemplates(
                {
                    "NAME": "probe",
                    "DIRS": [str(tmp_path)],
                    "APP_DIRS": False,
                    "OPTIONS": {"loaders": loaders},
                }
            )

        return build

    def test_a_configured_loader_still_rewrites(self, backend_with):
        backend = backend_with(["django.template.loaders.filesystem.Loader"])
        assert 'class="swatch"' in backend.get_template("probe.html").render({})

    def test_a_loader_nested_in_the_cached_loader_still_rewrites(self, backend_with):
        backend = backend_with(
            [
                (
                    "django.template.loaders.cached.Loader",
                    ["django.template.loaders.filesystem.Loader"],
                )
            ]
        )
        assert 'class="swatch"' in backend.get_template("probe.html").render({})

    def test_a_third_party_loader_still_rewrites(self, backend_with):
        """django-components ships a loader; it is reached the same way."""
        backend = backend_with(
            [
                (
                    "django.template.loaders.cached.Loader",
                    [
                        "django.template.loaders.filesystem.Loader",
                        "django_components.template_loader.Loader",
                    ],
                )
            ]
        )
        assert 'class="swatch"' in backend.get_template("probe.html").render({})


class TestOtherComponentFrameworks:
    """
    django-components renders alongside Citry in one template.

    It brings a loader, a tag library and a replacement for Django's tokenizer.
    Nothing in the adapter knows about any of that: the project configures it
    the way its own documentation says, and both frameworks work.
    """

    @pytest.fixture(autouse=True)
    def _djc_component(self):
        class CompatButton(DjcComponent):
            template = '<button class="djc-btn">{{ label }}</button>'

            def get_template_data(self, args, kwargs, slots, context):
                return {"label": kwargs["label"]}

        # Registered per test and taken back out again: the registry is global,
        # so leaving it behind would make the next test's registration fail.
        djc_registry.register("compat_button", CompatButton)
        yield CompatButton
        djc_registry.unregister("compat_button")

    def test_both_frameworks_render_in_one_template(self, render_django):
        out = render_django(
            '<div class="page">'
            '<c-swatch label="citry"/>'
            '{% component "compat_button" label="django-components" %}{% endcomponent %}'
            "</div>"
        )
        assert 'class="swatch"' in out and ">citry</span>" in out
        assert 'class="djc-btn"' in out and ">django-components</button>" in out

    def test_a_tag_carrying_template_source_as_data(self, render_django):
        """
        django-components reads a `%}` inside a quoted argument; Django's own
        lexer ends the tag there instead. Handing the extension the same
        tokenizer keeps both halves agreeing on where a tag ends.
        """
        out = render_django(
            '{% component "compat_button" label="a %} b" %}{% endcomponent %}'
            '<c-swatch label="beside"/>'
        )
        assert ">a %} b</button>" in out
        assert 'class="swatch"' in out

    def test_a_citry_component_inside_a_django_components_slot(self, render_django, component):
        component('<b class="inner">{{ text }}</b>', name="compat-inner")
        out = render_django(
            '{% component "compat_button" label="outer" %}{% endcomponent %}'
            '<c-compat-inner text="beside"/>'
        )
        assert 'class="djc-btn"' in out and 'class="inner"' in out
