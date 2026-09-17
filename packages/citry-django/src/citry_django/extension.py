from __future__ import annotations

from collections.abc import Callable
from typing import Any

from citry.extension import Extension, ForeignSpan, ForeignSpanSet
from citry.nodes import ForeignNode as CitryForeignNode
from django.template.base import TokenType

from .context import CONTEXT_BEHAVIORS, ContextBehavior
from .engine import django_lexer, get_django_engine
from .expressions import is_django_expression
from .registry import get_tokenizer
from .spans import PROVIDER, BodyCompiler, TemplateScan


class CitryDjangoExtension(Extension):
    """
    Install with ``Citry(extensions=[CitryDjangoExtension()])``.

    Every ``{% ... %}`` is run by Django's own engine. No tag is named here: the
    regions come from Django's lexer, and Django's parser builds their
    structure. Which engine owns a given ``{{ ... }}`` is decided from the
    template itself. The one thing worth passing is ``tokenizer``, when
    something other than Django compiles your templates.

    ``context_behavior`` decides what a component's own template can read of the
    context the host template was rendered with. ``"isolated"``, the default, is
    Citry's rule: a component takes its inputs and nothing else. ``"django"`` is
    Django's: the host's context is there to fall back on, the way it is in an
    ``{% include %}``. The name and the values follow django-components, whose
    setting does the same job.
    """

    name = PROVIDER

    def __init__(
        self,
        *,
        tokenizer: Callable[[str], list[Any]] | None = None,
        context_behavior: str = ContextBehavior.ISOLATED,
    ) -> None:
        # Every claim about where Django's syntax starts and stops is read with
        # this. Django's own lexer unless the template stack compiles templates
        # with something else, in which case the two have to agree.
        self.tokenizer = tokenizer or django_lexer
        if context_behavior not in CONTEXT_BEHAVIORS:
            allowed = ", ".join(sorted(CONTEXT_BEHAVIORS))
            msg = f"context_behavior must be one of {allowed}; got {context_behavior!r}"
            raise ValueError(msg)
        self.context_behavior = context_behavior

    def on_template_foreign_spans(self, ctx: Any) -> ForeignSpanSet | None:
        """
        Claim every span Django owns, using Django's own lexer.

        This is the whole of the adapter's parsing: Django says where its syntax
        is, and Citry keeps it out of its grammar.
        """
        scan = TemplateScan(ctx.content, get_tokenizer()(ctx.content))
        spans = list(self.claim(scan))
        if not spans:
            return None
        return ForeignSpanSet(tuple(spans), provider_metadata={"loads": scan.loads()})

    def on_template_foreign_compiled(self, ctx: Any) -> list[Any] | None:
        compiler = BodyCompiler(self.loads_for(ctx), ctx.origin, ctx.compiled_body)
        compiler.resolve_attrs(ctx.nodes)
        result = compiler.splice(ctx.nodes)
        ctx.mark_resolved(*ctx.claims)
        return result

    def claim(self, scan: TemplateScan):
        engine = get_django_engine().engine
        libraries = scan.libraries()
        verbatim_from: int | None = None
        for token in scan.tokens:
            command = token.contents.split()[:1] if token.token_type is TokenType.BLOCK else []

            # Claimed whole, body included: Django's lexer returns that body as
            # plain text, which Citry would otherwise parse.
            if command == ["verbatim"]:
                verbatim_from = token.position[0]
                continue
            if command == ["endverbatim"] and verbatim_from is not None:
                yield ForeignSpan(
                    scan.byte_offset(verbatim_from),
                    scan.byte_offset(token.position[1]),
                    may_control_body=True,
                )
                verbatim_from = None
                continue
            if verbatim_from is not None or token.token_type is TokenType.TEXT:
                continue

            start, end = token.position
            if token.token_type is TokenType.VAR and not self.is_djangos(
                token, scan, engine, libraries, start, end
            ):
                continue
            yield ForeignSpan(
                scan.byte_offset(start),
                scan.byte_offset(end),
                may_control_body=token.token_type is TokenType.BLOCK,
            )

    @staticmethod
    def is_djangos(token, scan: TemplateScan, engine, libraries, start: int, end: int) -> bool:
        """Whether a ``{{ ... }}`` is Django's.

        Both engines spell interpolation the same way, so this is decided per
        expression - except inside a quoted attribute value, where Citry reads
        literal text and would resolve nothing at all.
        """
        return is_django_expression(token.contents, engine, libraries) or (
            scan.inside_attribute_value(start, end)
        )

    def loads_for(self, ctx: Any) -> str:
        """The ``{% load %}`` lines this body may use.

        Taken from the body itself when it holds them, since a nested body is
        compiled apart from the template that declared them.
        """
        metadata = ctx.provider_metadata if isinstance(ctx.provider_metadata, dict) else {}
        return "".join(
            node.text
            for node in ctx.nodes
            if isinstance(node, CitryForeignNode)
            if node.provider == self.name
            if node.text.lstrip("{% ").startswith("load")
        ) or metadata.get("loads", "")
