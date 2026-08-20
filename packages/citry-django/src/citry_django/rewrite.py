"""
Finding Citry regions in Django template source.

Django's lexer only knows ``{% %}``, ``{{ }}`` and ``{# #}``, so a ``<c-hero/>``
would pass through as text. Neither grammar is scanned by hand: Django's lexer
says where its own syntax is (those spans are blanked, keeping every offset),
and Citry's parser then says where the ``<c-*>`` elements are.

A region is captured verbatim and handed back to Citry's parser at render time,
so everything Citry allows works inside it.
"""

from __future__ import annotations

from citry_core.template_parser import TemplateElement, parse_template
from django.template.base import DebugLexer, TokenType


def load_tags(source: str) -> str:
    """
    The template's ``{% load %}`` tags, verbatim and de-duplicated.

    Taken from Django's lexer rather than matched with a pattern, so quoting,
    newlines inside the tag and ``%}`` in a string are somebody else's solved
    problem.
    """
    seen = {
        source[token.position[0] : token.position[1]]: None
        for token in DebugLexer(source).tokenize()
        if token.token_type is TokenType.BLOCK and token.contents.split()[:1] == ["load"]
    }
    return "".join(seen)


def rewrite_source(source: str) -> str:
    """
    Mark every Citry region as ``{% citryfragment %}``.

    The source is hex-encoded into the tag's argument, because a region
    routinely contains quotes, ``%}`` and newlines, none of which survive
    ``smart_split``. A template with no Citry syntax is returned unchanged.
    """
    if "<c-" not in source:
        return source

    regions = _citry_regions(_mask_django(source), source)
    if not regions:
        return source

    # The template's own `{% load %}` lines travel into every region, so a
    # Django tag written inside `<c-card>...</c-card>` resolves against the
    # libraries loaded at the top of the file.
    loads = load_tags(source)

    out: list[str] = []
    last = 0
    for start, end in regions:
        out.append(source[last:start])
        region = loads + source[start:end]
        out.append(f'{{% citryfragment "{region.encode().hex()}" %}}')
        last = end
    out.append(source[last:])
    return "".join(out)


def _mask_django(source: str) -> str:
    """
    Blank out Django's syntax, keeping every offset.

    ``{% verbatim %}`` is blanked whole, contents included: Citry syntax inside
    it is meant to be shown rather than rendered.
    """
    chars = list(source)
    verbatim_from: int | None = None

    for token in DebugLexer(source).tokenize():
        start, end = token.position
        if token.token_type is TokenType.BLOCK:
            command = token.contents.split()[:1]
            if command == ["verbatim"]:
                verbatim_from = start
            elif command == ["endverbatim"] and verbatim_from is not None:
                chars[verbatim_from:end] = " " * (end - verbatim_from)
                verbatim_from = None
                continue
        if verbatim_from is None and token.token_type is not TokenType.TEXT:
            chars[start:end] = " " * (end - start)

    return "".join(chars)


def _citry_regions(masked: str, source: str) -> list[tuple[int, int]]:
    """
    Ask Citry's parser where the ``<c-*>`` elements are.

    Adjacent regions separated only by whitespace are merged: splitting
    ``<c-if>...</c-if><c-else>...</c-else>`` would hand Citry a stray
    ``<c-else>``. The gap is judged on the original source, because masking
    turns a Django tag between two regions into whitespace and merging across
    it would swallow that tag.
    """
    spans: list[tuple[int, int]] = []

    def walk(elements) -> None:
        for element in elements:
            if not isinstance(element, TemplateElement.Node):
                continue
            node = element._0
            start_tag = node.start_tag
            end_tag = getattr(node, "end_tag", None)
            span = (
                start_tag.token.start_index,
                end_tag.token.end_index if end_tag is not None else start_tag.token.end_index,
            )
            if start_tag.name.content.startswith("c-"):
                # The whole subtree is Citry's; do not look inside it.
                spans.append(span)
                continue
            body = getattr(node, "body", None)
            if body is not None:
                walk(body.elements)

    try:
        parsed = parse_template(masked)
    except Exception as exc:
        msg = (
            "This Django template contains Citry syntax that Citry's parser "
            f"could not read: {exc}\n\nCitry elements must be well-formed "
            "(every <c-x> closed by </c-x>, or written self-closing as "
            "<c-x/>). Django's own tags are blanked out before this parse, so "
            "the position above refers to the HTML around them."
        )
        raise ValueError(msg) from exc

    walk(parsed.elements)
    spans.sort()

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and not source[merged[-1][1] : start].strip():
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged
