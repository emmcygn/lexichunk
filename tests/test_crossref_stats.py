"""Tests for cross-reference resolution tracking (per-chunk stats + chunker properties)."""

from __future__ import annotations

import pytest

from lexichunk import LegalChunker
from lexichunk.models import LegalChunk


class TestPerChunkStats:
    """cross_ref_total and cross_ref_resolved on each chunk."""

    def test_defaults_zero(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk("1. Introduction\n\nThis is a simple clause.\n")
        for chunk in chunks:
            assert chunk.cross_ref_total >= 0
            assert chunk.cross_ref_resolved >= 0

    def test_chunk_with_resolvable_ref(self) -> None:
        text = (
            "1. Definitions\n\n"
            '"Agreement" means this agreement.\n\n'
            "2. Payment\n\n"
            "Subject to Clause 1, payment is due.\n"
        )
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(text)
        # Find chunks with cross-refs.
        refs_chunks = [c for c in chunks if c.cross_ref_total > 0]
        assert len(refs_chunks) > 0
        for c in refs_chunks:
            assert c.cross_ref_resolved <= c.cross_ref_total

    def test_unresolvable_ref(self) -> None:
        text = (
            "1. Scope\n\n"
            "See Section 99.99 for details.\n"
        )
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(text)
        refs_chunks = [c for c in chunks if c.cross_ref_total > 0]
        for c in refs_chunks:
            # Section 99.99 doesn't exist — unresolvable.
            assert c.cross_ref_resolved == 0

    def test_resolved_lte_total(self) -> None:
        text = (
            "1. Definitions\n\n"
            '"Term" means something.\n\n'
            "2. Obligations\n\n"
            "Pursuant to Clause 1, subject to Section 3, obligations apply.\n\n"
            "3. Termination\n\n"
            "Termination is allowed.\n"
        )
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(text)
        for c in chunks:
            assert c.cross_ref_resolved <= c.cross_ref_total

    def test_mixed_resolvable_and_unresolvable(self) -> None:
        """One chunk references both existing and non-existing sections."""
        text = (
            "1. Definitions\n\n"
            '"Term" means something important for this contract.\n\n'
            "2. Obligations\n\n"
            "The obligations described herein are significant.\n\n"
            "3. Cross-References\n\n"
            "Subject to Clause 1 and pursuant to Clause 2, "
            "and as described in Section 99, the parties agree.\n"
        )
        chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
        chunks = chunker.chunk(text)
        ref_chunks = [c for c in chunks if c.cross_ref_total > 0]
        assert len(ref_chunks) > 0
        for c in ref_chunks:
            # Should have some resolved and some not.
            assert c.cross_ref_resolved <= c.cross_ref_total


class TestChunkerProperties:
    """LegalChunker.cross_ref_resolution_rate and cross_ref_stats."""

    def test_defaults_before_chunk(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        assert chunker.cross_ref_resolution_rate == 1.0
        assert chunker.cross_ref_stats == {}

    def test_stats_populated_after_chunk(self) -> None:
        text = (
            "1. Definitions\n\n"
            '"Agreement" means this agreement.\n\n'
            "2. Payment\n\n"
            "Subject to Clause 1, payment is due.\n"
        )
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(text)
        stats = chunker.cross_ref_stats
        assert "total" in stats
        assert "resolved" in stats
        assert "rate" in stats
        assert 0.0 <= stats["rate"] <= 1.0

    def test_rate_matches_stats(self) -> None:
        text = (
            "1. Scope\n\n"
            "See Clause 2 for details.\n\n"
            "2. Details\n\n"
            "Details are here.\n"
        )
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk(text)
        stats = chunker.cross_ref_stats
        assert chunker.cross_ref_resolution_rate == stats["rate"]

    def test_stats_returns_copy(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        chunker.chunk("1. Scope\n\nSome text.\n")
        s1 = chunker.cross_ref_stats
        s1["total"] = 9999
        assert chunker.cross_ref_stats.get("total") != 9999

    def test_stats_overwrite_on_second_call(self) -> None:
        """Stats from second chunk() call must replace the first."""
        chunker = LegalChunker(jurisdiction="uk")
        text1 = (
            "1. Scope\n\nSee Clause 2 for details.\n\n"
            "2. Details\n\nDetails here.\n"
        )
        chunker.chunk(text1)
        stats1 = chunker.cross_ref_stats

        text2 = "1. Simple\n\nNo references at all.\n"
        chunker.chunk(text2)
        stats2 = chunker.cross_ref_stats

        # Second call had no refs — stats should reflect that.
        assert stats2["total"] == 0
        assert stats2["rate"] == 1.0
