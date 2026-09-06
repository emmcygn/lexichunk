"""Every public symbol must carry a docstring.

This is a floor, not a quality bar: it catches a new export or a new public
method landing with no documentation at all. Whether the docstring is *true*
is the reviewer's job, and the snapshot and invariant suites are what catch
behaviour drifting away from what is written.
"""

from __future__ import annotations

import inspect

import pytest

import lexichunk
from lexichunk import LegalChunker


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
        "chunk_iter",
        "chunk_with_metrics",
        "clear_definition_cache",
        "cross_ref_resolution_rate",
        "cross_ref_stats",
        "get_defined_terms",
        "jurisdiction",
        "parse_structure",
        "sanitize",
    ]
