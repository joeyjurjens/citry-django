"""Django output inside a Vue app: what Citry refuses, said in Django's terms.

Inside an interactive component, Citry writes the HTML that Django renders as
finished blocks that Vue inserts but never compiles. Citry refuses HTML it
cannot write that way, and names the reason: HTML that is not complete, a
component that needs Vue inside one of its elements, a `<script>` or
`<noscript>`, HTML under `<svg>`, `<math>` or a text-only element, and Vue
syntax in a template that also has Django tags.

Citry raises a plain `ValueError` or `TypeError` for each of these, so this
module tells them apart by the text Citry writes, and raises
`IslandContentError` with what to change in the Django template instead.
Citry's own message stays attached as the cause, with the HTML it refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class IslandContentError(ValueError):
    """Django output inside an interactive component that Vue cannot hold."""


#: How Citry names the HTML a template with Django tags produced.
STATIC_HTML = "HTML that Citry did not compile"


@dataclass(frozen=True)
class Refusal:
    """One reason Citry gives, and what citry-django says about it."""

    #: Text that only Citry's message for this reason contains.
    signature: re.Pattern[str]
    #: What citry-django says, as a `str.format` template: `{name}` and
    #: `{syntax}` come from the signature's groups, and a literal brace is
    #: doubled.
    message: str


REFUSALS = (
    Refusal(
        re.compile(
            rf"{STATIC_HTML} \(.*?\) is not (?:a complete HTML fragment|well-formed HTML)", re.S
        ),
        "A Django tag inside an interactive component wrote HTML that is not complete: it "
        "leaves a tag open, closes one it did not open, or the browser would read it "
        "differently than it was written. Vue inserts Django's output as finished blocks of "
        "HTML, so each block must be complete. Keep each Django tag inside the element it "
        "opens and closes, or write the condition or loop in Citry with <c-if> or <c-for>.",
    ),
    Refusal(
        re.compile(
            r"The component (?P<name>\w+), which needs Vue, "
            rf"sits inside an element of {STATIC_HTML}"
        ),
        "{name} needs Vue, and it sits inside an HTML element that a Django template wrote, "
        "inside an interactive component. Vue cannot place a component inside HTML it does not "
        "compile. Migrate that part to Citry: write the element, and any Django tag around "
        "{name}, in Citry syntax (<c-if> and <c-for> for {{% if %}} and {{% for %}}), or move "
        "{name} out of the element.",
    ),
    Refusal(
        re.compile(rf"A part that needs Vue sits inside an element of {STATIC_HTML}"),
        "Something that needs Vue sits inside an HTML element that a Django template wrote, "
        "inside an interactive component. Vue cannot place it inside HTML it does not compile. "
        "Migrate that part to Citry: write the element, and any Django tag around it, in "
        "Citry syntax (<c-if> and <c-for> for {{% if %}} and {{% for %}}).",
    ),
    Refusal(
        re.compile(rf"{STATIC_HTML} \(.*?\) holds a <script> element", re.S),
        "A Django template wrote a <script> inside an interactive component. Vue inserts "
        "Django's output as a block of HTML, and the browser does not run a script inserted "
        "that way, so it would run only on the first load of the page. Move the script into "
        "the component's js, or onto the page outside the component.",
    ),
    Refusal(
        re.compile(rf"{STATIC_HTML} \(.*?\) holds a <noscript> element", re.S),
        "A Django template wrote a <noscript> inside an interactive component. Vue inserts "
        "Django's output as a block of HTML that some browsers read with scripts turned off, "
        "so they would show and run what the <noscript> holds. Move the <noscript> onto the "
        "page outside the component.",
    ),
    Refusal(
        re.compile(rf"{STATIC_HTML} \(.*?\) cannot sit inside <", re.S),
        "A Django template wrote HTML inside <svg>, <math>, or an element that holds only "
        "text, such as <textarea>, inside an interactive component. Vue inserts Django's "
        "output with the HTML parser, which reads it differently there. Write that markup in "
        "Citry syntax, or pass the text in as a value.",
    ),
    Refusal(
        re.compile(
            r"(?P<name>\w+) has Vue syntax \((?P<syntax>.*?)\) in a template with foreign spans",
            re.S,
        ),
        "{name} uses Vue syntax ({syntax}) in a template that also has Django tags, inside an "
        "interactive component. A template with Django tags is written as HTML that Vue does "
        "not compile, so the Vue syntax would do nothing. Migrate the Django part to Citry: "
        "compute the value in template_data() (with reverse(), static() or gettext()) so the "
        "template has no Django tags, or move the Vue syntax into a component whose template "
        "has none.",
    ),
)


def refused_content(error: Exception) -> IslandContentError | None:
    """`error` in citry-django's words, or None when it is not one of these refusals."""
    text = str(error)
    for refusal in REFUSALS:
        match = refusal.signature.search(text)
        if match is not None:
            return IslandContentError(refusal.message.format(**match.groupdict()))
    return None
