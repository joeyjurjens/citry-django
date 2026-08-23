from django.db import models
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.models import Page


class HomePage(Page):
    """The landing page, whose template embeds Citry components directly."""

    intro = RichTextField(blank=True)
    hero_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    content_panels = [
        *Page.content_panels,
        FieldPanel("intro"),
        FieldPanel("hero_image"),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        context["articles"] = ArticlePage.objects.child_of(self).live()
        return context


class ArticlePage(Page):
    """A child page, so `{% pageurl %}` has something real to resolve."""

    summary = models.CharField(max_length=255, blank=True)
    # StreamField is how real Wagtail sites are built, and `{% include_block %}`
    # renders each block through its own template.
    body_stream = StreamField(
        [
            ("heading", blocks.CharBlock()),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock()),
        ],
        blank=True,
        use_json_field=True,
    )
    body = RichTextField(blank=True)
    featured = models.BooleanField(default=False)

    content_panels = [
        *Page.content_panels,
        FieldPanel("summary"),
        FieldPanel("body"),
        FieldPanel("body_stream"),
        FieldPanel("featured"),
    ]
