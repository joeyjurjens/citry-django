"""Custom tags in the shapes a third-party library uses, for the ESC tests in `test_robustness`."""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def echo(value):
    """Return the value as is, for Django to escape."""
    return value


@register.simple_tag
def bold(value):
    """Escape the value with `format_html`, as most third-party tags do."""
    return format_html("<b>{}</b>", value)


@register.inclusion_tag("esc/value.html")
def shown(value):
    """Render the value through a template of its own."""
    return {"n": value}


@register.simple_block_tag
def boxed(content, value):
    """Wrap the block's content and the value."""
    return format_html("<div>{}{}</div>", content, value)
