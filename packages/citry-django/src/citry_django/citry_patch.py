from __future__ import annotations

import ast
import warnings
from importlib import import_module
from importlib.metadata import version
from pathlib import Path

#: The one Citry release this patch is written for. Anything else is left alone:
#: a newer Citry has either fixed the bug or changed the function beyond what a
#: text replacement can follow.
AFFECTED_VERSION = "0.5.1"

FUNCTION = "prepare_ownership_manifest"

#: Citry 0.5.1 refuses to serialize a render whose components sit in a slot
#: region of an *enclosing* render, and writes the manifest the browser checks
#: with references to regions and invocations that are not in it. Both happen
#: whenever a Django template renders a block inside another region's slot while
#: that block holds a component with Events next to one that takes a slot:
#:
#:     A nested component included in the graph refers to a slot region outside
#:     that graph.
#:
#: A region of a nested render has parents outside the part being serialized by
#: construction. The manifest already writes such a parent as `None` for logical
#: instances; these replacements do the same for invocations, slot regions and
#: fills, and let a render that shares the enclosing graph pass the check.
REPLACEMENTS = [
    (
        """                and invocation.physical_parent_region_id not in active_region_ids
            ):""",
        """                and invocation.physical_parent_region_id not in active_region_ids
                and capture.graph is not root_graph
            ):""",
    ),
    (
        """                parent_region_id=(
                    None if record.physical_parent_region_id is None else int(record.physical_parent_region_id)
                ),""",
        """                parent_region_id=(
                    int(record.physical_parent_region_id)
                    if record.physical_parent_region_id is not None
                    and int(record.physical_parent_region_id) in active_region_ids
                    else None
                ),""",
    ),
    (
        """                source_invocation_id=(
                    None if record.source_invocation_id is None else int(record.source_invocation_id)
                ),""",
        """                source_invocation_id=(
                    int(record.source_invocation_id)
                    if record.source_invocation_id is not None and record.source_invocation_id in invocation_ids
                    else None
                ),""",
    ),
    (
        """                parent_region_id=(None if record.containing_region_id is None else int(record.containing_region_id)),""",
        """                parent_region_id=(
                    int(record.containing_region_id)
                    if record.containing_region_id is not None and record.containing_region_id in active_region_ids
                    else None
                ),""",
    ),
]


def function_source(module_source: str) -> str | None:
    """The text of Citry's manifest function, read from the module's own file.

    Read from the file rather than with `inspect.getsource`: once the patched
    function replaces the original, its line numbers no longer match the file.
    """
    tree = ast.parse(module_source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNCTION:
            return ast.get_source_segment(module_source, node)
    return None


def patched_source(source: str) -> str | None:
    """`source` with every replacement made, or `None` if one no longer matches."""
    for old, new in REPLACEMENTS:
        if source.count(old) != 1:
            return None
        source = source.replace(old, new)
    return source


def apply() -> bool:
    """Patch Citry's manifest function in place. Returns whether it is patched.

    Runs when `citry_django` is imported, before any render. It compiles the
    patched function into the module it came from, so it keeps the module's
    globals, and rebinds the one other module that imported it by name.
    """
    if version("citry") != AFFECTED_VERSION:
        return False
    module = import_module("citry.ownership_manifest")
    if getattr(module, "citry_django_patched", False):
        return True

    try:
        original = function_source(Path(module.__file__).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        original = None
    source = None if original is None else patched_source(original)
    if source is None:
        warnings.warn(
            f"citry-django could not patch Citry {AFFECTED_VERSION}: its ownership manifest no longer "
            "matches. Components with Events next to a component with a slot fail to render in a "
            "block that a Django template places in another region's slot.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    exec(compile(source, module.__file__, "exec"), module.__dict__)
    module.citry_django_patched = True
    import_module("citry.serialize").prepare_ownership_manifest = getattr(module, FUNCTION)
    return True
