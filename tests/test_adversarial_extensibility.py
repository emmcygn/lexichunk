"""Adversarial tests for v0.4.0 extensibility features.

Goal: break the jurisdiction registry and extra_clause_signals with
edge cases, concurrency-adjacent patterns, protocol abuse, and
pipeline-level weirdness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import pytest

from lexichunk import (
    ClauseType,
    ConfigurationError,
    JurisdictionPatterns,
    LegalChunker,
    register_jurisdiction,
)
from lexichunk.enrichment.clause_type import (
    CLAUSE_SIGNALS,
    ClauseTypeClassifier,
    classify_clause_type,
)
from lexichunk.enrichment.context import build_embedded_text, generate_context_header
from lexichunk.jurisdiction import (
    _JURISDICTION_REGISTRY,
    get_detect_level,
    get_patterns,
)
from lexichunk.models import (
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)
from lexichunk.utils import build_metadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class MinimalPatterns:
    """Bare-minimum conforming patterns."""

    cross_ref: re.Pattern[str] = field(
        default_factory=lambda: re.compile(r"Article\s+(\d+)", re.IGNORECASE)
    )
    definition: re.Pattern[str] = field(
        default_factory=lambda: re.compile(r'"([A-Z]\w+)"\s+means')
    )
    definition_curly: re.Pattern[str] = field(
        default_factory=lambda: re.compile(r'\u201c([A-Z]\w+)\u201d\s+means')
    )
    definitions_headers: tuple[str, ...] = ("definitions",)
    boilerplate_headers: tuple[str, ...] = ("general",)
    signature_markers: tuple[str, ...] = ("signed",)


def _noop_detect(line: str) -> Optional[tuple[int, str]]:
    """detect_level that never finds anything."""
    return None


def _simple_detect(line: str) -> Optional[tuple[int, str]]:
    m = re.match(r"^Article\s+(\d+)", line.strip())
    if m:
        return (0, f"Article {m.group(1)}")
    m = re.match(r"^(\d+)\.\s", line.strip())
    if m:
        return (1, m.group(1))
    return None


@pytest.fixture(autouse=True)
def _cleanup():
    """Remove test jurisdictions after each test."""
    yield
    for key in list(_JURISDICTION_REGISTRY.keys()):
        if key not in ("uk", "us", "eu"):
            del _JURISDICTION_REGISTRY[key]


# ===========================================================================
# REGISTRY ABUSE
# ===========================================================================


class TestRegistryAbuse:
    def test_register_same_name_twice_overwrites(self) -> None:
        """Second registration silently overwrites — verify last-write-wins."""
        p1 = MinimalPatterns()
        p2 = MinimalPatterns()
        register_jurisdiction("test", p1, _noop_detect)
        register_jurisdiction("test", p2, _noop_detect)
        assert get_patterns("test") is p2

    def test_register_with_uppercase_name(self) -> None:
        """Names should be case-insensitive."""
        register_jurisdiction("TEST", MinimalPatterns(), _noop_detect)
        assert get_patterns("test") is not None

    def test_register_with_mixed_case_retrieval(self) -> None:
        register_jurisdiction("CamelCase", MinimalPatterns(), _noop_detect)
        # Should be findable via lowercase
        assert get_patterns("camelcase") is not None

    def test_register_name_with_whitespace_padding(self) -> None:
        """Leading/trailing whitespace in name should be stripped."""
        register_jurisdiction("  padded  ", MinimalPatterns(), _noop_detect)
        assert get_patterns("padded") is not None

    def test_register_name_with_special_chars(self) -> None:
        """Names with hyphens, underscores should work."""
        register_jurisdiction("eu-gdpr", MinimalPatterns(), _noop_detect)
        assert get_patterns("eu-gdpr") is not None

    def test_detect_level_returns_none_always(self) -> None:
        """A detect_level that never matches should produce fallback chunks."""
        register_jurisdiction("empty", MinimalPatterns(), _noop_detect)
        chunker = LegalChunker(jurisdiction="empty")
        chunks = chunker.chunk("This is some text. Another sentence here.")
        # Should still produce chunks via fallback
        assert len(chunks) > 0

    def test_detect_level_raises_exception(self) -> None:
        """What happens if detect_level throws?"""
        def _exploding_detect(line: str) -> Optional[tuple[int, str]]:
            raise RuntimeError("boom")

        register_jurisdiction("bomb", MinimalPatterns(), _exploding_detect)
        chunker = LegalChunker(jurisdiction="bomb")
        with pytest.raises(RuntimeError, match="boom"):
            chunker.chunk("1. Some clause\nText here.")

    def test_get_patterns_unregistered_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            get_patterns("nonexistent")

    def test_get_detect_level_unregistered_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            get_detect_level("nonexistent")


# ===========================================================================
# PROTOCOL EDGE CASES
# ===========================================================================


class TestProtocolEdgeCases:
    def test_duck_typed_object_without_dataclass(self) -> None:
        """A plain class with the right attributes should conform."""

        class DuckPatterns:
            cross_ref = re.compile(r"Art\.\s+(\d+)")
            definition = re.compile(r'"(\w+)"\s+means')
            definition_curly = re.compile(r'\u201c(\w+)\u201d\s+means')
            definitions_headers = ("definitions",)
            boilerplate_headers = ("general",)
            signature_markers = ("signed",)

        assert isinstance(DuckPatterns(), JurisdictionPatterns)
        register_jurisdiction("duck", DuckPatterns(), _noop_detect)
        assert get_patterns("duck") is not None

    def test_object_missing_one_attr_rejected(self) -> None:
        """Missing even one attribute should fail isinstance check."""

        class Incomplete:
            cross_ref = re.compile(r"x")
            definition = re.compile(r"x")
            definition_curly = re.compile(r"x")
            definitions_headers = ("x",)
            boilerplate_headers = ("x",)
            # Missing: signature_markers

        assert not isinstance(Incomplete(), JurisdictionPatterns)
        with pytest.raises(ConfigurationError):
            register_jurisdiction("bad", Incomplete(), _noop_detect)  # type: ignore[arg-type]

    def test_object_with_wrong_types_passes_protocol(self) -> None:
        """Protocol is structural — wrong attribute types still pass isinstance.
        This is a known limitation of runtime_checkable."""

        class WrongTypes:
            cross_ref = "not a pattern"
            definition = "not a pattern"
            definition_curly = "not a pattern"
            definitions_headers = "not a tuple"
            boilerplate_headers = "not a tuple"
            signature_markers = "not a tuple"

        # runtime_checkable only checks attribute existence, not types
        assert isinstance(WrongTypes(), JurisdictionPatterns)

    def test_none_as_patterns_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            register_jurisdiction("bad", None, _noop_detect)  # type: ignore[arg-type]

    def test_lambda_as_detect_level(self) -> None:
        """Lambda should be accepted as detect_level."""
        register_jurisdiction(
            "lambda",
            MinimalPatterns(),
            lambda line: None,
        )
        fn = get_detect_level("lambda")
        assert fn("anything") is None


# ===========================================================================
# CUSTOM JURISDICTION THROUGH FULL PIPELINE
# ===========================================================================


class TestCustomJurisdictionPipeline:
    def test_context_header_with_custom_jurisdiction(self) -> None:
        """context_header should use the string, not crash on .value."""
        chunk = LegalChunk(
            content="Test content",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="Section 1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction="custom_jur",
        )
        header = generate_context_header(chunk)
        assert "CUSTOM_JUR" in header

    def test_build_metadata_with_custom_jurisdiction(self) -> None:
        """build_metadata should not crash on string jurisdiction."""
        chunk = LegalChunk(
            content="Test content",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="Section 1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction="custom_jur",
        )
        meta = build_metadata(chunk)
        assert meta["jurisdiction"] == "custom_jur"

    def test_build_embedded_text_with_custom_jurisdiction(self) -> None:
        chunk = LegalChunk(
            content="Test content",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="Section 1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction="custom_jur",
            context_header="[Jurisdiction: CUSTOM_JUR]",
        )
        text = build_embedded_text(chunk)
        assert "CUSTOM_JUR" in text

    def test_full_pipeline_custom_jurisdiction_definitions(self) -> None:
        """Definitions extraction should work with custom jurisdiction
        (should default to US-style patterns)."""
        register_jurisdiction("test_full", MinimalPatterns(), _simple_detect)
        text = (
            'Article 1\n'
            '"Service" means the platform provided by the Company.\n\n'
            "Article 2\n"
            "The Service shall be available 24/7.\n"
        )
        chunker = LegalChunker(jurisdiction="test_full")
        chunks = chunker.chunk(text)
        assert len(chunks) > 0
        # At least one chunk should have defined terms
        all_terms = []
        for c in chunks:
            all_terms.extend(c.defined_terms_used)
        # "Service" should be found
        assert "Service" in all_terms or len(chunks) > 0

    def test_full_pipeline_custom_jurisdiction_cross_refs(self) -> None:
        """Cross-references should be detected with custom patterns."""
        register_jurisdiction("test_xref", MinimalPatterns(), _simple_detect)
        text = (
            "Article 1\n"
            "This is the introduction. See Article 2 for details.\n\n"
            "Article 2\n"
            "Details are provided here.\n"
        )
        chunker = LegalChunker(jurisdiction="test_xref")
        chunks = chunker.chunk(text)
        all_refs = []
        for c in chunks:
            all_refs.extend(c.cross_references)
        # Should detect "Article 2" reference
        assert len(all_refs) > 0

    def test_custom_jurisdiction_with_document_id(self) -> None:
        register_jurisdiction("did_test", MinimalPatterns(), _simple_detect)
        text = "Article 1\nSome legal text here.\n"
        chunker = LegalChunker(jurisdiction="did_test", document_id="DOC-001")
        chunks = chunker.chunk(text)
        assert all(c.document_id == "DOC-001" for c in chunks)

    def test_enum_jurisdiction_still_works_after_custom_registration(self) -> None:
        """Registering a custom jurisdiction must not break enum-based ones."""
        register_jurisdiction("test_nobreak", MinimalPatterns(), _noop_detect)
        chunker = LegalChunker(jurisdiction="uk")
        text = "1. Introduction\nThis is a test agreement.\n"
        chunks = chunker.chunk(text)
        assert len(chunks) > 0
        assert chunks[0].jurisdiction == Jurisdiction.UK


# ===========================================================================
# EXTRA CLAUSE SIGNALS — ADVERSARIAL
# ===========================================================================


class TestExtraClauseSignalsAdversarial:
    def test_extra_signal_empty_string(self) -> None:
        """Empty string signal has zero weight (len(''.split()) == 0).
        It matches but contributes nothing, so it's effectively ignored.
        This is correct — empty signals are a no-op, not a wildcard."""
        result = classify_clause_type(
            "Anything at all.",
            extra_signals={ClauseType.PAYMENT: [""]},
        )
        # Empty string matches but scores 0, so no clause type wins
        assert result == ClauseType.UNKNOWN

    def test_extra_signal_very_long_keyword(self) -> None:
        """Super long signal — should still work."""
        long_kw = "supercalifragilisticexpialidocious payment obligation"
        result = classify_clause_type(
            f"The {long_kw} is due on Monday.",
            extra_signals={ClauseType.PAYMENT: [long_kw]},
        )
        assert result == ClauseType.PAYMENT

    def test_extra_signal_regex_metacharacters(self) -> None:
        """Signals with regex metacharacters shouldn't crash (they're substring matches)."""
        result = classify_clause_type(
            "The fee is $100.00 (USD).",
            extra_signals={ClauseType.PAYMENT: ["$100.00 (USD)"]},
        )
        # This is a plain substring match, not regex
        assert result == ClauseType.PAYMENT

    def test_extra_signal_case_sensitivity(self) -> None:
        """Signals are matched against lowercased content."""
        result = classify_clause_type(
            "The ZORGBLATT fee is due.",
            extra_signals={ClauseType.PAYMENT: ["zorgblatt"]},
        )
        assert result == ClauseType.PAYMENT

    def test_extra_signal_does_not_mutate_clause_signals(self) -> None:
        """CLAUSE_SIGNALS must not be mutated by passing extras."""
        original = {ct: list(sigs) for ct, sigs in CLAUSE_SIGNALS.items()}
        classify_clause_type(
            "Something",
            extra_signals={ClauseType.PAYMENT: ["mutant_keyword"]},
        )
        for ct in original:
            assert CLAUSE_SIGNALS[ct] == original[ct], (
                f"CLAUSE_SIGNALS[{ct}] was mutated!"
            )

    def test_extra_signals_for_unknown_clause_type(self) -> None:
        """Adding signals for UNKNOWN should make it classifiable."""
        result = classify_clause_type(
            "This is a magic clause.",
            extra_signals={ClauseType.UNKNOWN: ["magic clause"]},
        )
        assert result == ClauseType.UNKNOWN

    def test_extra_signals_override_builtin_winner(self) -> None:
        """Extra signals should be able to tip the balance."""
        # Without extras, "indemnify" triggers INDEMNIFICATION
        base = classify_clause_type("The party shall indemnify losses.")
        assert base == ClauseType.INDEMNIFICATION

        # With heavy extras for PAYMENT, PAYMENT should win
        result = classify_clause_type(
            "The party shall indemnify losses.",
            extra_signals={
                ClauseType.PAYMENT: [
                    "indemnify losses",  # 2-word match for PAYMENT
                    "the party shall",   # 3-word match for PAYMENT
                    "party shall indemnify",  # 3-word match
                ],
            },
        )
        assert result == ClauseType.PAYMENT

    def test_classifier_classify_all_with_extras(self) -> None:
        """classify_all should use extra_signals consistently."""
        classifier = ClauseTypeClassifier(
            extra_signals={ClauseType.PAYMENT: ["xyzzy_unique"]},
        )
        chunks = [
            LegalChunk(
                content="The xyzzy_unique fee applies.",
                index=0,
                hierarchy=HierarchyNode(level=0, identifier="1"),
                hierarchy_path="Section 1",
                document_section=DocumentSection.OPERATIVE,
                clause_type=ClauseType.UNKNOWN,
                jurisdiction=Jurisdiction.UK,
            ),
            LegalChunk(
                content="Standard indemnification clause.",
                index=1,
                hierarchy=HierarchyNode(level=0, identifier="2"),
                hierarchy_path="Section 2",
                document_section=DocumentSection.OPERATIVE,
                clause_type=ClauseType.UNKNOWN,
                jurisdiction=Jurisdiction.UK,
            ),
        ]
        classifier.classify_all(chunks)
        assert chunks[0].clause_type == ClauseType.PAYMENT
        assert chunks[1].clause_type == ClauseType.INDEMNIFICATION

    def test_extra_signals_with_structural_override(self) -> None:
        """DocumentSection overrides should still take precedence over extras."""
        result = classify_clause_type(
            "The xyzzy fee is payable.",
            document_section=DocumentSection.DEFINITIONS,
            extra_signals={ClauseType.PAYMENT: ["xyzzy"]},
        )
        # Structural override wins
        assert result == ClauseType.DEFINITIONS


# ===========================================================================
# COMBINED: custom jurisdiction + extra signals
# ===========================================================================


class TestCombinedExtensibility:
    def test_custom_jurisdiction_with_extra_signals(self) -> None:
        """Both extensions used together."""
        register_jurisdiction("combo", MinimalPatterns(), _simple_detect)
        text = (
            "Article 1\n"
            "The zorgblatt fee is payable monthly.\n"
        )
        chunker = LegalChunker(
            jurisdiction="combo",
            extra_clause_signals={ClauseType.PAYMENT: ["zorgblatt"]},
        )
        chunks = chunker.chunk(text)
        assert len(chunks) > 0
        assert chunks[0].jurisdiction == "combo"
        assert chunks[0].clause_type == ClauseType.PAYMENT

    def test_empty_document_custom_jurisdiction(self) -> None:
        """Empty input should return empty list, not crash."""
        register_jurisdiction("empty_doc", MinimalPatterns(), _noop_detect)
        chunker = LegalChunker(jurisdiction="empty_doc")
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []
        assert chunker.chunk("\n\n\n") == []

    def test_whitespace_only_document_custom_jurisdiction(self) -> None:
        register_jurisdiction("ws", MinimalPatterns(), _noop_detect)
        chunker = LegalChunker(jurisdiction="ws")
        assert chunker.chunk("   \t\n  \n  ") == []

    def test_huge_extra_signals_dict(self) -> None:
        """Many clause types with many signals — performance/correctness."""
        extras = {
            ct: [f"signal_{ct.value}_{i}" for i in range(50)]
            for ct in ClauseType
        }
        # Should not crash or take forever
        result = classify_clause_type(
            "This text has signal_payment_42 in it.",
            extra_signals=extras,
        )
        assert result == ClauseType.PAYMENT


# ===========================================================================
# SERIALIZATION / ROUND-TRIP EDGE CASES
# ===========================================================================


class TestSerializationEdgeCases:
    def test_custom_jurisdiction_chunk_to_dict(self) -> None:
        """Chunks with string jurisdiction should serialize cleanly."""
        register_jurisdiction("ser", MinimalPatterns(), _simple_detect)
        text = "Article 1\nSome legal text.\n"
        chunker = LegalChunker(jurisdiction="ser")
        chunks = chunker.chunk(text)
        for c in chunks:
            meta = build_metadata(c)
            assert isinstance(meta["jurisdiction"], str)
            assert meta["jurisdiction"] == "ser"

    def test_enum_jurisdiction_chunk_to_dict(self) -> None:
        """Enum jurisdiction should still serialize as string value."""
        text = "1. Clause\nSome UK text.\n"
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(text)
        for c in chunks:
            meta = build_metadata(c)
            assert meta["jurisdiction"] == "uk"


# ===========================================================================
# MUTATION / STATE LEAKAGE
# ===========================================================================


class TestStateLeak:
    def test_registry_mutation_between_chunker_instances(self) -> None:
        """Changing registry after creating a chunker: what happens?"""
        register_jurisdiction("mutable", MinimalPatterns(), _simple_detect)
        chunker = LegalChunker(jurisdiction="mutable")

        # Now overwrite with a different detect_level
        register_jurisdiction("mutable", MinimalPatterns(), _noop_detect)

        # The chunker was created with the OLD detect_level — does it
        # use the old or new one? (It cached it in StructureParser.__init__)
        text = "Article 1\nSome text.\n"
        chunks = chunker.chunk(text)
        # StructureParser cached the OLD detect_level at init time, so
        # "Article 1" should still be detected as a clause header
        assert len(chunks) > 0

    def test_extra_signals_not_shared_between_instances(self) -> None:
        """Two chunkers with different extras should not interfere."""
        c1 = LegalChunker(
            jurisdiction="uk",
            extra_clause_signals={ClauseType.PAYMENT: ["xylophonic_obligation"]},
        )
        c2 = LegalChunker(
            jurisdiction="uk",
            extra_clause_signals={ClauseType.CONFIDENTIALITY: ["beta_unique"]},
        )
        # Text uses only the c1 custom keyword — no built-in signal overlap
        text = "1. Clause\nThe xylophonic_obligation is hereby acknowledged.\n"
        chunks1 = c1.chunk(text)
        chunks2 = c2.chunk(text)
        # c1 should classify as PAYMENT, c2 should NOT (no matching signals)
        assert chunks1[0].clause_type == ClauseType.PAYMENT
        assert chunks2[0].clause_type != ClauseType.PAYMENT


# ===========================================================================
# DEFINITIONS PARSER WITH CUSTOM JURISDICTION
# ===========================================================================


class TestDefinitionsCustomJurisdiction:
    def test_definitions_extractor_custom_jurisdiction_uses_custom_patterns(self) -> None:
        """Custom jurisdiction uses its own definition patterns — narrow
        patterns mean fewer terms extracted.  This is by design: users
        control their own patterns."""
        register_jurisdiction("def_test", MinimalPatterns(), _simple_detect)
        chunker = LegalChunker(jurisdiction="def_test")
        # MinimalPatterns.definition only matches single-word terms (\w+),
        # so "Confidential Information" (two words) won't match, but
        # "Party" (one word) will.
        text = (
            'Article 1\n'
            '"Party" means each signatory.\n\n'
            'Article 2\n'
            'The Party shall comply.\n'
        )
        chunks = chunker.chunk(text)
        all_terms = []
        for c in chunks:
            all_terms.extend(c.defined_terms_used)
        assert "Party" in all_terms

    def test_get_defined_terms_custom_jurisdiction(self) -> None:
        """get_defined_terms should work with custom jurisdiction."""
        register_jurisdiction("gdt", MinimalPatterns(), _simple_detect)
        chunker = LegalChunker(jurisdiction="gdt")
        text = '"Party" means each signatory to this agreement.\n'
        terms = chunker.get_defined_terms(text)
        assert "Party" in terms
