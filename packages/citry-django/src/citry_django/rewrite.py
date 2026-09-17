from __future__ import annotations

from citry_core.template_parser import TemplateElement, parse_template
from django.template.base import TokenType

from .registry import get_tokenizer

#: Elements whose body is text rather than markup, so a `<c-*>` inside one is
#: content and not a region.
RAW_TEXT_TAGS = frozenset({"script", "style", "textarea", "title"})

#: Citry control-flow tags that continue the region before them.
CONTINUATION_TAGS = frozenset({"c-elif", "c-else", "c-empty"})


def load_tags(source: str) -> str:
    """
    The template's ``{% load %}`` tags, verbatim and de-duplicated.

    Taken from Django's lexer rather than matched with a pattern, so quoting,
    newlines inside the tag and ``%}`` in a string are somebody else's solved
    problem.
    """
    seen = {
        source[token.position[0] : token.position[1]]: None
        for token in get_tokenizer()(source)
        if token.token_type is TokenType.BLOCK and token.contents.split()[:1] == ["load"]
    }
    return "".join(seen)


class RegionRewriter:
    """
    Every Citry region in a Django template, marked as ``{% citryfragment %}``.

    Django's lexer only knows ``{% %}``, ``{{ }}`` and ``{# #}``, so a
    ``<c-hero/>`` passes through it as text. Neither grammar is scanned by hand:
    Django's lexer says where its own syntax is, those spans are blanked keeping
    every offset, and Citry's parser then says where the ``<c-*>`` elements are.

    A region is captured verbatim, hex-encoded into the tag's argument because
    it routinely holds quotes, ``%}`` and newlines, and handed back to Citry's
    parser at render time. Everything Citry allows works inside it.
    """

    def __init__(self, source: str, origin: str = "<django template>") -> None:
        self.source = source
        self.origin = origin

    def rewrite(self) -> str:
        """`source` with each region replaced, or unchanged when it has none."""
        if "<c-" not in self.source:
            return self.source
        regions = self.regions()
        if not regions:
            return self.source

        # The template's own `{% load %}` lines travel into every region, so a
        # Django tag written inside `<c-card>...</c-card>` resolves against the
        # libraries loaded at the top of the file.
        loads = load_tags(self.source).encode()
        origin = self.origin.encode().hex()

        source_bytes = self.source.encode()
        out: list[bytes] = []
        last = 0
        for start, end in regions:
            out.append(source_bytes[last:start])
            region = (loads + source_bytes[start:end]).hex()
            out.append(f'{{% citryfragment "{region}" "{origin}" %}}'.encode())
            last = end
        out.append(source_bytes[last:])
        return b"".join(out).decode()

    def regions(self) -> list[tuple[int, int]]:
        """
        Where the ``<c-*>`` elements are, as byte ranges.

        Adjacent regions separated only by whitespace are merged: splitting
        ``<c-if>...</c-if><c-else>...</c-else>`` would hand Citry a stray
        ``<c-else>``. The gap is judged on the original source, because masking
        turns a Django tag between two regions into whitespace and merging
        across it would swallow that tag.
        """
        source_bytes = self.source.encode()
        merged: list[tuple[int, int]] = []
        for start, end in self.scan(self.masked_source()):
            if merged and not source_bytes[merged[-1][1] : start].decode().strip():
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        return merged

    def masked_source(self) -> str:
        """
        Django's syntax blanked out, every offset kept.

        ``{% verbatim %}`` is blanked whole, contents included: Citry syntax
        inside it is meant to be shown rather than rendered.
        """
        chars = list(self.source)
        verbatim_from: int | None = None

        for token in get_tokenizer()(self.source):
            start, end = token.position
            if token.token_type is TokenType.BLOCK:
                command = token.contents.split()[:1]
                if command == ["verbatim"]:
                    verbatim_from = start
                elif command == ["endverbatim"] and verbatim_from is not None:
                    self.blank(chars, verbatim_from, end)
                    verbatim_from = None
                    continue
            if verbatim_from is None and token.token_type is not TokenType.TEXT:
                self.blank(chars, start, end)

        return "".join(chars)

    @staticmethod
    def blank(chars: list[str], start: int, end: int) -> None:
        for index in range(start, end):
            # Keeping a non-ASCII character retains its encoded width. The ASCII
            # delimiters around it are blanked, so the remainder is ordinary
            # text to Citry's parser rather than live Django syntax.
            if chars[index].isascii():
                chars[index] = " "

    def scan(self, masked: str) -> list[tuple[int, int]]:
        """Top-level Citry elements, without requiring valid surrounding HTML."""
        offsets = utf8_byte_offsets(masked)
        spans: list[tuple[int, int]] = []
        index = 0
        while index < len(masked):
            if masked.startswith("<!--", index):
                close = masked.find("-->", index + 4)
                index = len(masked) if close < 0 else close + 3
                continue
            if masked[index] != "<":
                index += 1
                continue

            tag_end = self.tag_end(masked, index)
            if tag_end is None:
                index += 1
                continue
            name = self.tag_name(masked, index, tag_end)
            if name is None:
                index = tag_end
                continue
            name = name.lower()
            closing = masked.startswith("</", index)

            if name.startswith("c-") and not closing:
                joins_previous = bool(
                    name in CONTINUATION_TAGS and spans and not masked[spans[-1][1] : index].strip()
                )
                start = spans.pop()[0] if joins_previous else index
                end = self.region_end(masked, start, minimum_end=tag_end)
                spans.append((start, end))
                index = end
            elif name in RAW_TEXT_TAGS and not closing:
                close_start = masked.lower().find(f"</{name}", tag_end)
                if close_start < 0:
                    break
                close_end = self.tag_end(masked, close_start)
                index = len(masked) if close_end is None else close_end
            else:
                index = tag_end
        return [(offsets[start], offsets[end]) for start, end in spans]

    @staticmethod
    def tag_end(source: str, start: int) -> int | None:
        """The character boundary after one quote-aware `>` delimiter."""
        quote: str | None = None
        for index in range(start + 1, len(source)):
            character = source[index]
            if quote is not None:
                if character == quote:
                    quote = None
                continue
            if character in {'"', "'"}:
                quote = character
            elif character == ">":
                return index + 1
        return None

    @staticmethod
    def tag_name(source: str, start: int, end: int) -> str | None:
        """An HTML-looking tag name, or None for text and declarations."""
        index = start + 1
        if index < end and source[index] == "/":
            index += 1
        name_start = index
        while index < end and (source[index].isalnum() or source[index] in "-_:."):
            index += 1
        return source[name_start:index] or None

    @staticmethod
    def region_end(source: str, start: int, *, minimum_end: int) -> int:
        """The shortest prefix Citry accepts as exactly one component node."""
        search_from = start
        last_error: Exception | None = None
        while True:
            end = source.find(">", search_from)
            if end < 0:
                break
            boundary = end + 1
            if boundary < minimum_end:
                search_from = boundary
                continue
            fragment = source[start:boundary]
            try:
                parsed = parse_template(fragment)
            except Exception as exc:
                last_error = exc
                search_from = boundary
                continue
            nodes = [
                element._0
                for element in parsed.elements
                if isinstance(element, TemplateElement.Node)
            ]
            only_components_and_spacing = bool(nodes) and all(
                (
                    isinstance(element, TemplateElement.Node)
                    and element._0.start_tag.name.content.startswith("c-")
                )
                or (
                    isinstance(element, TemplateElement.Text)
                    and not element._0.token.content.strip()
                )
                for element in parsed.elements
            )
            if only_components_and_spacing:
                node = nodes[-1]
                node_end = getattr(node, "end_tag", None)
                token = node_end.token if node_end is not None else node.start_tag.token
                if token.end_index == len(fragment.encode()):
                    return boundary
            search_from = boundary

        msg = (
            "This Django template contains Citry syntax that Citry's parser could not read"
            f" near {source[start : start + 80]!r}: {last_error}\n\nCitry elements must be "
            "well-formed (every <c-x> closed by </c-x>, or written self-closing as "
            "<c-x/>). Django's own tags are blanked before region discovery."
        )
        raise ValueError(msg) from last_error


def rewrite_source(source: str, *, origin: str = "<django template>") -> str:
    """`source` with every Citry region marked. See :class:`RegionRewriter`."""
    return RegionRewriter(source, origin).rewrite()


def utf8_byte_offsets(source: str) -> list[int]:
    """Map every Python character boundary to its UTF-8 byte offset."""
    offsets = [0]
    total = 0
    for character in source:
        total += len(character.encode())
        offsets.append(total)
    return offsets
