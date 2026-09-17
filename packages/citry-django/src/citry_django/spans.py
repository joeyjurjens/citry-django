from __future__ import annotations

from typing import Any, cast

from citry import CompiledBody
from citry.nodes import ForeignHtmlAttr as CitryForeignHtmlAttr
from citry.nodes import ForeignNode as CitryForeignNode
from django.template.base import TokenType

from .foreign import DjangoHtmlAttr, ForeignNode

#: The extension's name, as a span's provider. Here rather than on the class so
#: this module does not have to import the extension that imports it.
PROVIDER = "citry_django"


class TemplateScan:
    """The template as Django's lexer sees it.

    Every claim about where Django's syntax starts and stops is read off this,
    so it is built once per template and asked from there.
    """

    def __init__(self, content: str, tokens: list[Any]) -> None:
        self.content = content
        self.tokens = tokens

    def byte_offset(self, index: int) -> int:
        """`index` as a UTF-8 byte offset, which is what a span is measured in."""
        return len(self.content[:index].encode("utf-8"))

    def loads(self) -> str:
        """The template's own `{% load %}` lines.

        An attribute value compiles as its own template with none of its own,
        so the enclosing template's are kept for it.
        """
        return "".join(
            self.content[token.position[0] : token.position[1]]
            for token in self.tokens
            if token.token_type is TokenType.BLOCK and token.contents.split()[:1] == ["load"]
        )

    def libraries(self) -> tuple[str, ...]:
        """Library labels this template loads, so its filters are recognised."""
        labels: list[str] = []
        for token in self.tokens:
            if token.token_type is not TokenType.BLOCK:
                continue
            words = token.contents.split()
            if words and words[0] == "load":
                labels.extend(words[2:] if "from" in words else words[1:])
        return tuple(dict.fromkeys(label for label in labels if label != "from"))

    def inside_attribute_value(self, start: int, end: int) -> bool:
        """Whether `start..end` sits inside a quoted attribute value.

        Citry resolves `{{ ... }}` in text and in a `c-` attribute, so a bare
        name is left to it there. The value of an ordinary attribute is literal
        text to Citry, and leaving a name to an engine that never looks at it
        means the braces reach the page.
        """
        opening = max(self.content.rfind('"', 0, start), self.content.rfind("'", 0, start))
        if opening < 0 or self.content.rfind(">", opening, start) > opening:
            return False
        if not self.content[:opening].rstrip().endswith("="):
            return False
        closing = self.content.find(self.content[opening], end)
        return closing >= 0 and self.content.find(">", end, closing) < 0


class BodyCompiler:
    """One independently compiled body, with its provider claims resolved.

    A body carrying Django's tags is replaced by a single Django-driven node:
    the tags are already in the order they were written, so the block structure
    is rebuilt by handing Django's own parser a template made of those tags plus
    one marker per run of Citry content. Nothing here matches tags; Django
    decides what pairs with what.
    """

    def __init__(self, loads: str, origin: str, compiled_body: Any) -> None:
        self.loads = loads
        self.origin = origin
        self.compiled_body = compiled_body

    def resolve_attrs(self, body: list[Any]) -> None:
        """Replace direct foreign component inputs with Django-rendered attrs."""
        for item in body:
            attrs = getattr(item, "attrs", None)
            if not isinstance(attrs, tuple):
                continue
            replaced = [self.as_django_attr(attr) for attr in attrs]
            if replaced != list(attrs):
                item.attrs = tuple(replaced)

    def splice(self, body: list[Any]) -> list[Any]:
        """`body` as one Django-driven node, or unchanged when we own nothing."""
        if not any(self.is_ours(item) for item in body):
            return body

        # Alternating: Django source from the foreign tags, Citry runs between.
        pieces: list[str] = []
        segments: list[CompiledBody] = []
        run: list[Any] = []
        for item in body:
            if self.is_ours(item):
                if run:
                    self.emit_run(pieces, segments, run)
                    run = []
                pieces.append(item.text)
            else:
                run.append(item)
        if run:
            self.emit_run(pieces, segments, run)

        return [ForeignNode("".join(pieces), segments, self.loads, self.origin)]

    def as_django_attr(self, attr: Any) -> Any:
        if not isinstance(attr, CitryForeignHtmlAttr):
            return attr
        if any(node.provider != PROVIDER for node in attr.foreign_nodes()):
            return attr
        source = "".join(
            part.text if isinstance(part, CitryForeignNode) else part for part in attr.parts
        )
        return DjangoHtmlAttr(source, attr.position, attr.key, self.loads, self.origin)

    @staticmethod
    def is_ours(item: Any) -> bool:
        return isinstance(item, CitryForeignNode) and item.provider == PROVIDER

    def emit_run(self, pieces: list[str], segments: list[CompiledBody], run: list[Any]) -> None:
        equivalents = [self.django_equivalent(item) for item in run]
        if all(source is not None for source in equivalents):
            pieces.append("".join(cast("list[str]", equivalents)))
            return
        pieces.append(f"{{% citryseg {len(segments)} %}}")
        segments.append(self.compiled_body(run))

    @staticmethod
    def django_equivalent(item: Any) -> str | None:
        """The Django source for one body item, when it has an exact one.

        A tag may restrict what its body may contain: `{% blocktranslate %}`
        permits only text and `{{ name }}` and rejects block tags at parse time,
        so a body made only of those has to reach Django as source.
        """
        if isinstance(item, str):
            return item
        expression = getattr(item, "expr", None)
        if isinstance(expression, str) and expression.strip().isidentifier():
            return f"{{{{ {expression.strip()} }}}}"
        return None
