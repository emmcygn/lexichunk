"""Tests for the definition extraction cache in LegalChunker."""

from __future__ import annotations

from lexichunk import LegalChunker

# A minimal UK contract with a defined term.
_UK_DOC = """\
1. Definitions

1.1 In this Agreement, the following terms shall have the meanings set out below:

    "Service" means the software development services described in Schedule 1.

2. Obligations

2.1 The Supplier shall provide the Service in accordance with this Agreement.
"""


class TestDefinitionCacheHit:
    """Cache returns stored results on second call with identical text."""

    def test_cache_hit_skips_extraction(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunks_1 = chunker.chunk(_UK_DOC)
        chunks_2 = chunker.chunk(_UK_DOC)

        # Same results both times.
        assert len(chunks_1) == len(chunks_2)
        for c1, c2 in zip(chunks_1, chunks_2):
            assert c1.content == c2.content
            assert c1.defined_terms_used == c2.defined_terms_used

        # Exactly one entry in the cache.
        assert len(chunker._definition_cache) == 1


class TestDefinitionCacheMiss:
    """Different text produces a different cache entry."""

    def test_different_text_is_cache_miss(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(_UK_DOC)

        other_doc = _UK_DOC.replace("Service", "Platform")
        chunker.chunk(other_doc)

        assert len(chunker._definition_cache) == 2


class TestDefinitionCacheDisabled:
    """When disabled, no cache entries are created."""

    def test_no_cache_when_disabled(self) -> None:
        chunker = LegalChunker(jurisdiction="uk", enable_definition_cache=False)
        chunker.chunk(_UK_DOC)
        chunker.chunk(_UK_DOC)

        assert len(chunker._definition_cache) == 0


class TestDefinitionCacheClear:
    """clear_definition_cache() empties the cache."""

    def test_clear_removes_all_entries(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(_UK_DOC)
        assert len(chunker._definition_cache) == 1

        chunker.clear_definition_cache()
        assert len(chunker._definition_cache) == 0


class TestDefinitionCacheBOMInvariant:
    """BOM prefix should not affect cache key (sanitized before hashing)."""

    def test_bom_text_same_cache_key(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(_UK_DOC)
        chunker.chunk("\ufeff" + _UK_DOC)

        # Both should produce the same cache entry after BOM stripping.
        assert len(chunker._definition_cache) == 1


class TestDefinitionCacheLineEndingInvariant:
    r"""\\r\\n vs \\n should not affect cache key (sanitized before hashing)."""

    def test_crlf_text_same_cache_key(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(_UK_DOC)
        chunker.chunk(_UK_DOC.replace("\n", "\r\n"))

        # Both should produce the same cache entry after line-ending normalization.
        assert len(chunker._definition_cache) == 1
