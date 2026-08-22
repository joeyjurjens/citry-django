# Citry host-template APIs used by this adapter

This adapter contains no Django syntax in Citry itself. It uses generic APIs in
Citry 0.4.3 and Citry Core 1.6.0. The workspace resolves those released
packages from PyPI, and the adapter declares `citry>=0.4.3`.

## Foreign spans

An extension declares UTF-8 byte spans owned by another template engine:

```python
from citry import ForeignSpan, ForeignSpanSet

def on_template_foreign_spans(self, ctx):
    return ForeignSpanSet((ForeignSpan(start_byte, end_byte),))
```

Citry validates that spans are sorted, non-empty, non-overlapping UTF-8
boundaries within the immutable root source. The Rust parser masks them without
shifting byte offsets, then emits provider and ordinal-bearing foreign source
parts in body, quoted attribute-value, and start-tag order.

The matching `on_template_foreign_compiled(ctx)` hook runs for each independently
compiled body before `on_template_compiled`. It receives only its provider's
claims and must call `ctx.mark_resolved(...)` for all of them. Unclaimed or
unresolved source fails closed. The hook may convert a list of Citry nodes into
an opaque `CompiledBody` handle with `ctx.compiled_body(nodes)` for later host
callbacks.

This adapter obtains character offsets from Django's `DebugLexer` and converts
them to UTF-8 byte offsets before returning the span set. Django decides its own
block structure later; Citry never matches an opening host tag to a closing one.

## Standalone rendering

The other direction uses:

```python
Citry.render_template(
    source,
    variables,
    slots=None,
    template_globals=None,
    provides=None,
    foreign_compile_contexts=None,
    origin="<render_template>",
)
```

It returns a normal `CitryRender`. The implementation has a bounded per-engine
compiled-template cache and one private transparent root, so it does not create
or register a public component class for every source. Actual components inside
the source keep normal ownership, dependencies, and extension behavior.

When Django renders a loop or block around Citry nodes that were already
compiled, the adapter calls `render_compiled_body`. Fill discovery uses the
matching `collect_compiled_body_fills` API. The adapter therefore imports no
private Citry render functions.

## Bindings and parser surface

The lower-level `citry_core.template_parser.parse_template` accepts a keyword
`ParseOptions` containing `ForeignSpan` values, the projected source offset,
and the immutable root source. The five language emitters, PyO3 registrations,
Python wrapper, and `_rust.pyi` expose the same AST variants and fields.

The low-level formatter accepts the same options through
`citry_core.template_formatter.format_template(source, options=options)`. It
treats claimed ranges as unknown syntax, preserves their bytes exactly, and
rebases the claims internally while Citry-owned edits shift later source. The
app-independent `citry format` command does not discover host extensions; an
adapter or editor integration must supply the claims.

In app-aware mode, `citry --app module:engine check` asks installed extensions
for foreign spans and skips host syntax. If a claim may control a body, the
checker also suppresses the unknown-template-variable lint for that template,
because a host loop or assignment may introduce the name. Static checking does
not import extensions and therefore remains Citry-only.

## Qualified behavior

- Citry's parser and Python runtime suites exercise validation, Unicode byte
  offsets, attributes, nested template projections, fail-closed ownership,
  hook order, cache reuse, and concurrent cold compilation.
- This adapter has 208 passing tests against Django, Wagtail, third-party tag
  libraries, slot/fill combinations, non-ASCII source, and both integration
  directions.
- Django-to-Citry region discovery tolerates host-controlled partial HTML,
  preserves dependent Citry control-flow sibling chains, and ignores
  Citry-looking text in raw-text and attribute positions.
- Host-selected Citry segments remain structured until the enclosing Citry
  render is serialized. This preserves ownership/event graphs, dependency
  placeholder positions, CSP state, and one outer serialization pass. Standard
  Django HTML escaping remains an explicit inert-text boundary.
- A standalone Citry region reads its CSP nonce from the Django context keys
  `csp_nonce` or `CSP_NONCE`, then from `request.csp_nonce`.
- The known fail-loud incompatibility is a Django tag that transforms,
  duplicates, or discards a reached Citry segment marker. For example,
  `{% filter upper %}<c-widget/>{% endfilter %}` raises instead of flattening
  or corrupting Citry's render graph.
