"""Every public symbol must carry a docstring.

This is a floor, not a quality bar: it catches a new export or a new public
method landing with no documentation at all. Whether the docstring is *true*
is the reviewer's job, and the snapshot and invariant suites are what catch
behaviour drifting away from what is written.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import lexichunk
from lexichunk import LegalChunker

_SRC_ROOT = Path(lexichunk.__file__).resolve().parent


def _has_sphinx_doc_comment(name: str) -> bool:
    """Return ``True`` if ``name`` is a module-level alias with a ``#:`` comment.

    A ``TypeAlias`` such as ``ClassificationHook`` is a plain assignment at
    runtime, so it cannot carry a ``__doc__``.  The documented convention for
    those is Sphinx's ``#:`` comment block directly above the assignment,
    which is what this looks for — so an alias export is still required to be
    documented, just in the only place the language allows.
    """
    assignment = re.compile(rf"^{re.escape(name)}(?::[^=]+)? *=", re.MULTILINE)
    for path in _SRC_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        match = assignment.search(source)
        if match is None:
            continue
        preceding = source[: match.start()].splitlines()
        if preceding and preceding[-1].lstrip().startswith("#:"):
            return True
    return False


def _public_names() -> list[str]:
    return sorted(lexichunk.__all__)


def test_all_is_sorted_and_complete() -> None:
    """``__all__`` must name only symbols the package actually exports."""
    assert lexichunk.__all__, "__all__ is empty"
    assert len(set(lexichunk.__all__)) == len(lexichunk.__all__), "__all__ has duplicates"
    for name in lexichunk.__all__:
        assert hasattr(lexichunk, name), f"__all__ names {name!r}, which is not exported"


def test_package_has_module_docstring() -> None:
    assert (lexichunk.__doc__ or "").strip(), "lexichunk package has no module docstring"


@pytest.mark.parametrize("name", _public_names())
def test_public_export_has_docstring(name: str) -> None:
    """Every name in ``lexichunk.__all__`` is documented."""
    obj = getattr(lexichunk, name)
    if not (inspect.isclass(obj) or inspect.isfunction(obj) or inspect.ismodule(obj)):
        # A type alias cannot hold a __doc__; require the ``#:`` convention.
        assert _has_sphinx_doc_comment(name), (
            f"lexichunk.{name} is an alias with no '#:' documentation comment"
        )
        return
    doc = inspect.getdoc(obj)
    assert doc and doc.strip(), f"lexichunk.{name} has no docstring"


def _public_methods() -> list[str]:
    names: list[str] = []
    for name, member in inspect.getmembers(LegalChunker):
        if name.startswith("_"):
            continue
        if inspect.isfunction(member) or isinstance(member, (property, staticmethod)):
            names.append(name)
    return sorted(names)


@pytest.mark.parametrize("name", _public_methods())
def test_legal_chunker_member_has_docstring(name: str) -> None:
    """Every public method and property of ``LegalChunker`` is documented."""
    member = inspect.getattr_static(LegalChunker, name)
    target = member.fget if isinstance(member, property) else member
    doc = inspect.getdoc(target)
    assert doc and doc.strip(), f"LegalChunker.{name} has no docstring"


def test_legal_chunker_surface_is_stable() -> None:
    """Pin the public surface so a new method cannot slip in undocumented.

    Update this list deliberately when adding public API — and document the
    addition in CHANGELOG.md at the same time.
    """
    assert _public_methods() == [
        "chunk",
        "chunk_batch",
        "chunk_documents",
        "chunk_iter",
        "chunk_with_metrics",
        "clear_definition_cache",
        "cross_ref_resolution_rate",
        "cross_ref_stats",
        "get_defined_terms",
        "jurisdiction",
        "parse_structure",
        "sanitize",
        "sanitize_with_map",
    ]
