"""Tests for work package G4a — public API hardening.

Covers: chunk_batch() input/validation contract and pool-failure fallback,
register_jurisdiction() override guard, jurisdiction normalisation,
_validate_config() constructor validation, get_defined_terms()/
parse_structure() input-guard parity, logging policy (DEBUG/WARNING),
the thread-safe LRU definition cache, the single-alternation-regex
_attach_defined_terms(), LegalChunk.__post_init__ invariants, and the
saturation-scaled classification confidence formula.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading

import pytest

from lexichunk import (
    ClauseType,
    ConfigurationError,
    InputError,
    LegalChunker,
    ParsingError,
    register_jurisdiction,
    registered_jurisdictions,
    unregister_jurisdiction,
)
from lexichunk.enrichment.clause_type import SATURATION, _classify_detailed
from lexichunk.jurisdiction.uk import UKPatterns
from lexichunk.jurisdiction.uk import detect_level as uk_detect_level
from lexichunk.models import (
    DefinedTerm,
    DocumentSection,
    HierarchyNode,
    Jurisdiction,
    LegalChunk,
)

_UK_DOC = """\
1. Definitions

1.1 In this Agreement, the following terms shall have the meanings set out below:

    "Service" means the software development services described in Schedule 1.

2. Obligations

2.1 The Supplier shall provide the Service in accordance with this Agreement.
"""


# ===========================================================================
# 1. chunk_batch() input contract
# ===========================================================================


class TestChunkBatchInputContract:
    def test_rejects_bare_str(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(InputError, match=r"chunk_batch\(\[text\]\)"):
            chunker.chunk_batch("Payment terms apply to all fees.")

    def test_rejects_bytes(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(InputError):
            chunker.chunk_batch(b"some bytes")

    def test_rejects_bytearray(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(InputError):
            chunker.chunk_batch(bytearray(b"some bytes"))

    def test_accepts_generator_materialised_once(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")

        def gen():
            yield _UK_DOC
            yield _UK_DOC

        result = chunker.chunk_batch(gen(), workers=1)
        assert result.success_count == 2

    def test_non_iterable_raises_input_error(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(InputError):
            chunker.chunk_batch(42, workers=1)  # type: ignore[arg-type]

    def test_workers_bool_raises_configuration_error(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(ConfigurationError, match="workers"):
            chunker.chunk_batch([_UK_DOC], workers=True)  # type: ignore[arg-type]

    def test_workers_non_int_raises_configuration_error(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(ConfigurationError, match="workers"):
            chunker.chunk_batch([_UK_DOC], workers="2")  # type: ignore[arg-type]

    def test_workers_validated_before_pairs_are_processed(self) -> None:
        """A bad `workers` value must win even when the batch also contains
        bad documents — validated before any per-document work happens."""
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(ConfigurationError, match="workers"):
            chunker.chunk_batch([None, 42, _UK_DOC], workers=0)  # type: ignore[list-item]

    def test_empty_iterable_returns_empty_result(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        result = chunker.chunk_batch(iter([]))
        assert result.results == []
        assert result.errors == []


# ===========================================================================
# 2. Parallel batch robustness: pool-start failure and the Windows cap
# ===========================================================================


class _ImmediatePool:
    """Fake ProcessPoolExecutor that runs submitted work inline."""

    last_max_workers: int | None = None

    def __init__(self, max_workers: int | None = None) -> None:
        _ImmediatePool.last_max_workers = max_workers

    def __enter__(self) -> "_ImmediatePool":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def submit(self, fn: object, *args: object) -> "concurrent.futures.Future[object]":
        fut: "concurrent.futures.Future[object]" = concurrent.futures.Future()
        try:
            fut.set_result(fn(*args))  # type: ignore[operator]
        except Exception as exc:  # noqa: BLE001 - propagate via the Future
            fut.set_exception(exc)
        return fut


class _FailingPool:
    """Fake ProcessPoolExecutor whose __enter__ raises, like a spawn failure."""

    def __init__(self, max_workers: int | None = None) -> None:
        pass

    def __enter__(self) -> "_FailingPool":
        raise RuntimeError(
            "An attempt has been made to start a new process before the "
            "current process has finished its bootstrapping phase"
        )

    def __exit__(self, *exc_info: object) -> bool:
        return False


class TestParallelBatchPoolFailureFallback:
    def test_pool_start_failure_falls_back_to_serial_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            "concurrent.futures.ProcessPoolExecutor", _FailingPool
        )
        chunker = LegalChunker(jurisdiction="uk")
        with caplog.at_level(logging.WARNING, logger="lexichunk.chunker"):
            result = chunker.chunk_batch([_UK_DOC, _UK_DOC, _UK_DOC], workers=2)

        # The batch contract still holds: no exception escaped, and every
        # document was processed (via the serial fallback).
        assert result.success_count == 3
        assert result.error_count == 0
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("falling back to serial" in r.message for r in warnings)
        assert any("__main__" in r.message for r in warnings)

    def test_windows_worker_cap_logs_info_and_caps_pool(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            "concurrent.futures.ProcessPoolExecutor", _ImmediatePool
        )
        monkeypatch.setattr("lexichunk.chunker.sys.platform", "win32")
        chunker = LegalChunker(jurisdiction="uk")
        with caplog.at_level(logging.INFO, logger="lexichunk.chunker"):
            result = chunker.chunk_batch(
                [_UK_DOC, _UK_DOC, _UK_DOC], workers=100
            )
        assert result.success_count == 3
        assert _ImmediatePool.last_max_workers == 61
        infos = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("61" in r.message for r in infos)


# ===========================================================================
# 3. register_jurisdiction() override guard, unregister, registered list
# ===========================================================================


class TestRegisterJurisdictionOverrideGuard:
    def test_builtin_refused_without_override(self) -> None:
        with pytest.raises(ConfigurationError, match="built-in"):
            register_jurisdiction("uk", UKPatterns(), uk_detect_level)

    def test_builtin_allowed_with_override_and_restorable(self) -> None:
        from lexichunk.jurisdiction import UK_PATTERNS

        register_jurisdiction("uk", UKPatterns(), uk_detect_level, override=True)
        try:
            from lexichunk.jurisdiction import get_patterns

            assert isinstance(get_patterns("uk"), UKPatterns)
        finally:
            register_jurisdiction("uk", UK_PATTERNS, uk_detect_level, override=True)

    def test_us_and_eu_also_refused_without_override(self) -> None:
        with pytest.raises(ConfigurationError, match="built-in"):
            register_jurisdiction("us", UKPatterns(), uk_detect_level)
        with pytest.raises(ConfigurationError, match="built-in"):
            register_jurisdiction("eu", UKPatterns(), uk_detect_level)

    def test_custom_key_first_registration_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="lexichunk.jurisdiction"):
            register_jurisdiction("g4a_fresh", UKPatterns(), uk_detect_level)
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    def test_custom_key_reregistration_without_override_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        register_jurisdiction("g4a_dup", UKPatterns(), uk_detect_level)
        with caplog.at_level(logging.WARNING, logger="lexichunk.jurisdiction"):
            register_jurisdiction("g4a_dup", UKPatterns(), uk_detect_level)
        assert any(
            "Re-registering" in r.message for r in caplog.records
        )

    def test_custom_key_reregistration_with_override_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        register_jurisdiction("g4a_dup2", UKPatterns(), uk_detect_level)
        with caplog.at_level(logging.WARNING, logger="lexichunk.jurisdiction"):
            register_jurisdiction(
                "g4a_dup2", UKPatterns(), uk_detect_level, override=True
            )
        assert not any(r.levelno == logging.WARNING for r in caplog.records)


class TestUnregisterJurisdiction:
    def test_unregister_builtin_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="built-in"):
            unregister_jurisdiction("uk")

    def test_unregister_unknown_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            unregister_jurisdiction("does-not-exist")

    def test_unregister_removes_custom_key(self) -> None:
        register_jurisdiction("g4a_remove_me", UKPatterns(), uk_detect_level)
        assert "g4a_remove_me" in registered_jurisdictions()
        unregister_jurisdiction("g4a_remove_me")
        assert "g4a_remove_me" not in registered_jurisdictions()

    def test_double_unregister_raises_on_second_call(self) -> None:
        register_jurisdiction("g4a_once", UKPatterns(), uk_detect_level)
        unregister_jurisdiction("g4a_once")
        with pytest.raises(ConfigurationError):
            unregister_jurisdiction("g4a_once")


class TestRegisteredJurisdictions:
    def test_includes_builtins(self) -> None:
        keys = registered_jurisdictions()
        assert {"uk", "us", "eu"}.issubset(set(keys))

    def test_is_sorted_tuple(self) -> None:
        keys = registered_jurisdictions()
        assert isinstance(keys, tuple)
        assert list(keys) == sorted(keys)


# ===========================================================================
# 4. Jurisdiction normalisation
# ===========================================================================


class TestJurisdictionNormalisation:
    def test_padded_uppercase_resolves_to_enum(self) -> None:
        chunker = LegalChunker(jurisdiction=" UK ")
        assert chunker.jurisdiction == Jurisdiction.UK
        assert isinstance(chunker.jurisdiction, Jurisdiction)

    def test_mixed_case_resolves_to_enum(self) -> None:
        chunker = LegalChunker(jurisdiction="Us")
        assert chunker.jurisdiction == Jurisdiction.US

    def test_enum_passed_directly(self) -> None:
        chunker = LegalChunker(jurisdiction=Jurisdiction.EU)
        assert chunker.jurisdiction == Jurisdiction.EU

    def test_non_str_non_enum_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(jurisdiction=123)  # type: ignore[arg-type]

    def test_none_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(jurisdiction=None)  # type: ignore[arg-type]

    def test_jurisdiction_property_is_read_only(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with pytest.raises(AttributeError):
            chunker.jurisdiction = Jurisdiction.US  # type: ignore[misc]

    def test_padded_builtin_jurisdiction_works_with_parallel_batch(self) -> None:
        """Regression: a whitespace/casing variant of a built-in must resolve
        to the real enum, so it is NOT treated as an unpicklable custom
        jurisdiction when workers > 1."""
        chunker = LegalChunker(jurisdiction=" UK ")
        result = chunker.chunk_batch([_UK_DOC, _UK_DOC, _UK_DOC], workers=2)
        assert result.success_count == 3

    def test_custom_registered_jurisdiction_key_is_stripped_lowered(self) -> None:
        register_jurisdiction("g4a_custom", UKPatterns(), uk_detect_level)
        chunker = LegalChunker(jurisdiction=" G4A_CUSTOM ")
        assert chunker.jurisdiction == "g4a_custom"


# ===========================================================================
# 5. _validate_config via LegalChunker.__init__
# ===========================================================================


class TestValidateConfigNumeric:
    def test_max_cache_size_zero_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_cache_size"):
            LegalChunker(max_cache_size=0)

    def test_max_cache_size_negative_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_cache_size"):
            LegalChunker(max_cache_size=-5)

    def test_max_cache_size_no_longer_clamped(self) -> None:
        """Previously max_cache_size<1 silently clamped to 1; now it raises."""
        with pytest.raises(ConfigurationError):
            LegalChunker(max_cache_size=-1000)

    def test_max_cache_size_bool_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_cache_size"):
            LegalChunker(max_cache_size=True)  # type: ignore[arg-type]

    def test_max_chunk_size_bool_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="max_chunk_size"):
            LegalChunker(max_chunk_size=True)  # type: ignore[arg-type]

    def test_chars_per_token_bool_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="chars_per_token"):
            LegalChunker(chars_per_token=False)  # type: ignore[arg-type]

    def test_min_chunk_size_bool_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="min_chunk_size"):
            LegalChunker(min_chunk_size=True)  # type: ignore[arg-type]


class TestValidateConfigBooleans:
    @pytest.mark.parametrize(
        "kwarg", ["include_definitions", "include_context_header", "enable_definition_cache"]
    )
    def test_non_bool_raises(self, kwarg: str) -> None:
        with pytest.raises(ConfigurationError, match=kwarg):
            LegalChunker(**{kwarg: 1})  # type: ignore[arg-type]


class TestValidateConfigExtraAbbreviations:
    def test_non_list_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="extra_abbreviations"):
            LegalChunker(extra_abbreviations="Corp.")  # type: ignore[arg-type]

    def test_element_non_str_raises_with_index(self) -> None:
        with pytest.raises(ConfigurationError, match=r"extra_abbreviations\[1\]"):
            LegalChunker(extra_abbreviations=["Corp.", 123])  # type: ignore[list-item]

    def test_empty_string_element_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="extra_abbreviations"):
            LegalChunker(extra_abbreviations=["Corp.", ""])

    def test_tuple_accepted(self) -> None:
        chunker = LegalChunker(extra_abbreviations=("Corp.", "Inc."))
        assert chunker is not None

    def test_deep_copied_at_construction(self) -> None:
        original = ["Corp."]
        chunker = LegalChunker(extra_abbreviations=original)
        original.append("Inc.")
        original[0] = "MUTATED"
        assert chunker._extra_abbreviations == ["Corp."]


class TestValidateConfigExtraClauseSignals:
    def test_str_key_raises_with_helpful_hint(self) -> None:
        with pytest.raises(ConfigurationError, match=r"ClauseType\.PAYMENT"):
            LegalChunker(extra_clause_signals={"payment": ["zorgblatt"]})  # type: ignore[dict-item]

    def test_non_mapping_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="extra_clause_signals"):
            LegalChunker(extra_clause_signals=[(ClauseType.PAYMENT, ["x"])])  # type: ignore[arg-type]

    def test_blank_string_signal_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(extra_clause_signals={ClauseType.PAYMENT: [""]})

    def test_whitespace_only_signal_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(extra_clause_signals={ClauseType.PAYMENT: ["   "]})

    def test_non_str_signal_element_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            LegalChunker(extra_clause_signals={ClauseType.PAYMENT: [123]})  # type: ignore[list-item]

    def test_valid_signals_still_work(self) -> None:
        chunker = LegalChunker(
            extra_clause_signals={ClauseType.PAYMENT: ["zorgblatt"]}
        )
        chunks = chunker.chunk("1. Clause\nThe zorgblatt fee is due.\n")
        assert chunks[0].clause_type == ClauseType.PAYMENT

    def test_deep_copied_at_construction(self) -> None:
        original = {ClauseType.PAYMENT: ["zorgblatt"]}
        chunker = LegalChunker(extra_clause_signals=original)
        original[ClauseType.PAYMENT].append("MUTATED")
        original[ClauseType.CONFIDENTIALITY] = ["secret"]
        assert chunker._extra_clause_signals == {ClauseType.PAYMENT: ["zorgblatt"]}


class TestChunkerConfigValidationParity:
    """_ChunkerConfig.__post_init__ shares _validate_config with __init__,
    so parallel batch construction cannot silently drop a bad setting."""

    def test_parallel_path_still_works_with_valid_config(self) -> None:
        chunker = LegalChunker(
            jurisdiction="uk", max_cache_size=16, extra_abbreviations=["Corp."]
        )
        result = chunker.chunk_batch([_UK_DOC, _UK_DOC, _UK_DOC], workers=2)
        assert result.success_count == 3


# ===========================================================================
# 6. get_defined_terms() / parse_structure() input-guard parity
# ===========================================================================


class TestInputGuardParity:
    def test_get_defined_terms_rejects_oversized_input(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        huge = "x" * (LegalChunker._MAX_INPUT_CHARS + 1)
        with pytest.raises(InputError, match="too large"):
            chunker.get_defined_terms(huge)

    def test_get_defined_terms_empty_short_circuits(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        assert chunker.get_defined_terms("") == {}
        assert chunker.get_defined_terms("   \n\t  ") == {}

    def test_parse_structure_rejects_oversized_input(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        huge = "x" * (LegalChunker._MAX_INPUT_CHARS + 1)
        with pytest.raises(InputError, match="too large"):
            chunker.parse_structure(huge)

    def test_parse_structure_empty_short_circuits(self) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        assert chunker.parse_structure("") == []
        assert chunker.parse_structure("   \n\t  ") == []

    def test_get_defined_terms_still_works_normally(self, uk_service_agreement: str) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        terms = chunker.get_defined_terms(uk_service_agreement)
        assert len(terms) > 0

    def test_parse_structure_still_works_normally(self, uk_service_agreement: str) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        nodes = chunker.parse_structure(uk_service_agreement)
        assert len(nodes) > 0


# ===========================================================================
# 7. sanitize()
# ===========================================================================


class TestSanitizePublicAlias(object):
    def test_matches_internal_sanitize(self) -> None:
        raw = "﻿Hello\r\nWorld\r\x00!"
        assert LegalChunker.sanitize(raw) == LegalChunker._sanitize_input(raw)

    def test_offsets_index_into_sanitized_text(self) -> None:
        raw = "﻿1. Clause\r\nSome text here.\r\n"
        chunker = LegalChunker(jurisdiction="uk")
        chunks = chunker.chunk(raw)
        sanitized = LegalChunker.sanitize(raw)
        assert chunks[-1].char_end <= len(sanitized)


# ===========================================================================
# 8. Logging policy: DEBUG for progress, WARNING only for the documented cases
# ===========================================================================


class TestLoggingPolicy:
    def test_normal_chunk_emits_nothing_at_info_or_above(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with caplog.at_level(logging.INFO, logger="lexichunk.chunker"):
            chunker.chunk(_UK_DOC)
        assert caplog.records == []

    def test_fallback_chunk_emits_nothing_at_info_or_above(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        chunker = LegalChunker(jurisdiction="uk")
        with caplog.at_level(logging.INFO, logger="lexichunk.chunker"):
            _, metrics = chunker.chunk_with_metrics(
                "Just a plain sentence with no legal structure at all."
            )
        assert metrics is not None
        assert metrics.fallback_used is True
        assert caplog.records == []

    def test_nullhandler_installed_on_package_logger(self) -> None:
        pkg_logger = logging.getLogger("lexichunk")
        assert any(
            isinstance(h, logging.NullHandler) for h in pkg_logger.handlers
        )


# ===========================================================================
# 9. Definition cache: thread-safe LRU
# ===========================================================================


class TestDefinitionCacheLRU:
    def _doc(self, term: str) -> str:
        return (
            "1. Definitions\n\n"
            f'1.1 "{term}" means the thing called {term}.\n\n'
            "2. Obligations\n\n"
            f"2.1 The parties shall use {term} in accordance with this Agreement.\n"
        )

    def test_lru_evicts_least_recently_used(self) -> None:
        chunker = LegalChunker(jurisdiction="uk", max_cache_size=2)
        chunker.chunk(self._doc("Alpha"))
        chunker.chunk(self._doc("Beta"))
        # Touch Alpha again — it becomes most-recently-used.
        chunker.chunk(self._doc("Alpha"))
        # Inserting a third distinct document should evict Beta, not Alpha.
        chunker.chunk(self._doc("Gamma"))
        assert len(chunker._definition_cache) == 2

        keys_after_gamma = set(chunker._definition_cache.keys())
        # Re-chunking Alpha must still be a cache hit: no growth, and the
        # same two keys remain (order may change — a hit moves Alpha to the
        # most-recently-used end, it does not evict or insert anything).
        chunker.chunk(self._doc("Alpha"))
        assert len(chunker._definition_cache) == 2
        assert set(chunker._definition_cache.keys()) == keys_after_gamma

        # Beta was genuinely evicted: re-chunking it is a fresh miss that
        # grows the cache back to (and no further than) max_cache_size.
        chunker.chunk(self._doc("Beta"))
        assert len(chunker._definition_cache) == 2

    def test_thread_safety_no_cross_contamination(self) -> None:
        chunker = LegalChunker(jurisdiction="uk", max_cache_size=16)
        n_threads = 8
        results: dict[int, list[str]] = {}
        errors: list[BaseException] = []
        lock = threading.Lock()

        names = [f"AlphaTermNumber{w}" for w in (
            "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
        )]

        def worker(i: int) -> None:
            try:
                doc = self._doc(names[i])
                chunks = chunker.chunk(doc)
                terms = sorted(
                    {t for c in chunks for t in c.defined_terms_used}
                )
                with lock:
                    results[i] = terms
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(n_threads):
            assert results[i] == [names[i]], (
                f"thread {i} saw cross-contaminated terms: {results[i]}"
            )


# ===========================================================================
# 10. _attach_defined_terms: single alternation regex, 300-term sanity check
# ===========================================================================


class TestAttachDefinedTermsAlternationRegex:
    def test_300_terms_correctness_and_no_crash(self) -> None:
        from lexichunk.chunker import _attach_defined_terms

        n = 300
        defined_terms = {
            f"DefinedTermNumber{i:03d}": DefinedTerm(
                term=f"DefinedTermNumber{i:03d}",
                definition=f"means thing number {i}",
                source_clause="1.1",
            )
            for i in range(n)
        }
        # Only a handful of terms actually appear in each chunk's content.
        chunk_a = LegalChunk(
            content="This clause references DefinedTermNumber007 and DefinedTermNumber199.",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=Jurisdiction.UK,
        )
        chunk_b = LegalChunk(
            content="No defined terms appear in this sentence at all.",
            index=1,
            hierarchy=HierarchyNode(level=0, identifier="2"),
            hierarchy_path="2",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=Jurisdiction.UK,
        )
        chunks = [chunk_a, chunk_b]
        _attach_defined_terms(chunks, defined_terms)

        assert sorted(chunk_a.defined_terms_used) == [
            "DefinedTermNumber007",
            "DefinedTermNumber199",
        ]
        assert chunk_a.defined_terms_context["DefinedTermNumber007"] == (
            "means thing number 7"
        )
        assert chunk_b.defined_terms_used == []

    def test_no_defined_terms_is_noop(self) -> None:
        from lexichunk.chunker import _attach_defined_terms

        chunk = LegalChunk(
            content="Some content.",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=Jurisdiction.UK,
        )
        _attach_defined_terms([chunk], {})
        assert chunk.defined_terms_used == []


# ===========================================================================
# 11. LegalChunk.__post_init__ invariants and jurisdiction_value
# ===========================================================================


def _base_chunk_kwargs() -> dict:
    return dict(
        content="text",
        index=0,
        hierarchy=HierarchyNode(level=0, identifier="1"),
        hierarchy_path="1",
        document_section=DocumentSection.OPERATIVE,
        clause_type=ClauseType.UNKNOWN,
        jurisdiction=Jurisdiction.UK,
    )


class TestLegalChunkPostInit:
    def test_negative_index_raises(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["index"] = -1
        with pytest.raises(ParsingError):
            LegalChunk(**kwargs)

    def test_negative_char_start_raises(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["char_start"] = -1
        with pytest.raises(ParsingError):
            LegalChunk(**kwargs)

    def test_char_end_before_char_start_raises(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["char_start"] = 10
        kwargs["char_end"] = 5
        with pytest.raises(ParsingError):
            LegalChunk(**kwargs)

    def test_confidence_above_one_raises(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["classification_confidence"] = 1.5
        with pytest.raises(ParsingError):
            LegalChunk(**kwargs)

    def test_confidence_below_zero_raises(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["classification_confidence"] = -0.1
        with pytest.raises(ParsingError):
            LegalChunk(**kwargs)

    def test_cross_ref_resolved_exceeds_total_raises(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["cross_ref_total"] = 1
        kwargs["cross_ref_resolved"] = 2
        with pytest.raises(ParsingError):
            LegalChunk(**kwargs)

    def test_valid_chunk_constructs_fine(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["char_start"] = 0
        kwargs["char_end"] = 4
        kwargs["classification_confidence"] = 0.5
        kwargs["cross_ref_total"] = 2
        kwargs["cross_ref_resolved"] = 1
        chunk = LegalChunk(**kwargs)
        assert chunk.index == 0

    def test_parsing_error_is_a_value_error(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["index"] = -1
        with pytest.raises(ValueError):
            LegalChunk(**kwargs)


class TestJurisdictionValue:
    def test_enum_jurisdiction(self) -> None:
        chunk = LegalChunk(**_base_chunk_kwargs())
        assert chunk.jurisdiction_value == "uk"

    def test_string_jurisdiction(self) -> None:
        kwargs = _base_chunk_kwargs()
        kwargs["jurisdiction"] = "custom_jur"
        chunk = LegalChunk(**kwargs)
        assert chunk.jurisdiction_value == "custom_jur"


# ===========================================================================
# 12. Classification confidence saturation
# ===========================================================================


class TestConfidenceSaturation:
    def test_saturation_constant(self) -> None:
        assert SATURATION == 4.0

    def test_single_weak_keyword_reports_well_below_one(self) -> None:
        # "fee" is a single one-word PAYMENT signal with no competing type.
        result = _classify_detailed("The annual fee is due.")
        assert result.clause_type == ClauseType.PAYMENT
        # Old formula gave 1.0 (only one type scored); new formula
        # discounts for weak absolute evidence.
        assert result.confidence < 0.5

    def test_strong_evidence_reaches_saturation(self) -> None:
        result = _classify_detailed(
            "force majeure event beyond reasonable control act of god"
        )
        assert result.clause_type == ClauseType.FORCE_MAJEURE
        assert result.confidence == 1.0

    def test_structural_override_unaffected_by_saturation(self) -> None:
        result = _classify_detailed(
            "anything at all", document_section=DocumentSection.DEFINITIONS
        )
        assert result.confidence == 1.0

    def test_confidence_always_in_bounds(self) -> None:
        for text in [
            "payment",
            "payment fee invoice price consideration payable billing charge",
            "xyzzy nonsense text with no signals",
        ]:
            result = _classify_detailed(text)
            assert 0.0 <= result.confidence <= 1.0


# ===========================================================================
# 13. doc_type docstring accuracy (sanity check against structure.py truth)
# ===========================================================================


class TestDocTypeDocstring:
    def test_docstring_no_longer_claims_informational(self) -> None:
        assert "informational" not in (LegalChunker.__doc__ or "").lower()

    def test_docstring_mentions_signature_and_section_detection(self) -> None:
        doc = LegalChunker.__doc__ or ""
        assert "signature" in doc.lower()
        assert "document-section detection" in doc.lower() or "document section detection" in doc.lower()
