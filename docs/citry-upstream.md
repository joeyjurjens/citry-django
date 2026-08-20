# What Citry needs to add

What Citry has to ship for `citry-django` to work. All of it is generic: no
Django delimiter appears anywhere in Citry.

The working tree is in `citry-src/`, built with maturin and installed editable.

## The capability

An extension declares byte ranges another engine owns. Citry keeps them out of
its grammar and returns them as nodes, in tree order, holding the source
verbatim. Citry knows no other engine's delimiters.

    # in an extension
    def on_template_opaque_spans(self, ctx):
        return [t.position for t in DebugLexer(ctx.content).tokenize()
                if t.token_type is TokenType.BLOCK]

    # arrives in on_template_compiled as:
    #   ForeignNode(position=(8, 18), text='{% if x %}')

Proven with two unrelated hosts: Django (spans from `DebugLexer`) and ERB
(spans from a different lexer). Neither delimiter appears in Citry.

## Rust

| file | change |
|---|---|
| `grammar.pest` | one `foreign_region` rule matching Citry's own marker bytes |
| `ast.rs` | `TemplateElement::Foreign(Text)` |
| `parser.rs` | `parse_template_with_opaque_spans()`, byte-length-preserving masking, dispatch |
| `parser_context.rs` | `source_slice()` to recover the verbatim text |
| `compiler.rs` | emits `ForeignNode(...)`; passes regions through control-flow preprocessing |
| `constants.rs` | `FOREIGN_NODE` |
| `citry_template_formatter` (3 files) | leaves foreign regions exactly as written |
| `citry_core_py/template_parser.rs` | the `opaque_spans` argument |

Masking substitutes each range with marker bytes of the same byte length, so
every offset still indexes the original source: diagnostics stay accurate and
the host's text is sliced back out. The first byte opens a region and the rest
fill it, so two adjacent regions stay two regions.

`parse_template()` keeps its old signature and delegates, so no existing caller
changes.

## Python

| file | change |
|---|---|
| `citry/extension.py` | `on_template_opaque_spans` hook, its context, and the manager that combines and orders every extension's ranges |
| `citry/nodes/__init__.py` | `ForeignNode`, rendering its text verbatim by default |
| `citry/component_render.py` | calls the hook, passes ranges to the parser, registers the node |
| `citry_core/template_parser/parse.py` | the `opaque_spans` argument |

The default rendering matters: a claimed range that no extension replaces
renders as the text it always was, so installing this changes no output.

## `render_fragment`

The other direction needs a way to render Citry source without declaring a
component for it, which is what a `<c-*>` region found in a Django template is::

    Citry.render_fragment(source, variables, *, template_globals, provides)
      -> CitryRender

`citry.py` implements it over an LRU cache of generated component classes, so
a given source is compiled once.

## Verified

- Citry's own Rust parser suite: unchanged and passing.
- The Django adapter: 186 tests, against a real Wagtail project.

## Still to do before landing upstream

- `_rust.pyi` stub, the four non-Python `lang/*.rs` impls, and Python-side
  tests for the hook (Citry's `CLAUDE.md` Mechanism 4).
- A written plan before the grammar change (their Mechanism 2). I edited first.
