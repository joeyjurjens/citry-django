"""
StreamField blocks for the demo site.

An accordion is a good shape to test against: it nests a ListBlock of
StructBlocks, and each item holds a StreamBlock with several child types.
"""

import uuid

from wagtail import blocks
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.images.blocks import ImageChooserBlock


class AccordionItemBlock(blocks.StructBlock):
    title = blocks.CharBlock(required=True)
    content = blocks.StreamBlock(
        [
            ("paragraph", blocks.RichTextBlock()),
            ("page", blocks.PageChooserBlock()),
            ("image", ImageChooserBlock()),
            ("document", DocumentChooserBlock()),
            (
                "inline_structblock",
                blocks.StructBlock(
                    [
                        ("heading", blocks.CharBlock()),
                        ("content", blocks.RichTextBlock()),
                    ]
                ),
            ),
        ],
        required=False,
    )

    class Meta:
        template = "testproject/accordion_item.html"


class AccordionBlock(blocks.StructBlock):
    items = blocks.ListBlock(AccordionItemBlock())

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        # Generate unique accordion ID for children to use
        context["accordion_id"] = f"accordion-{uuid.uuid4().hex[:8]}"
        return context

    class Meta:
        template = "testproject/accordion.html"
