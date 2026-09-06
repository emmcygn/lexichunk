"""Raw-offset back-map: OffsetMap, sanitize_with_map, chunk(raw_offsets=True).

The load-bearing property is the round-trip one: for a chunk produced from
*raw* text, re-sanitising ``raw[raw_char_start:raw_char_end]`` must reproduce
``sanitised[char_start:char_end]`` exactly.  It is asserted directly on hand-
written cases, then property-tested with hypothesis over documents built from
the four things sanitisation actually rewrites: BOMs, CRLF, null bytes and NFD
combining sequences.
"""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from lexichunk import LegalChunker, OffsetMap, sanitize_with_map

# ---------------------------------------------------------------------------
# sanitize_with_map agrees with sanitize
# ---------------------------------------------------------------------------

_CASES = [
    "",
    "plain ascii text",
    "\ufeffleading bom",
    "crlf\r\nline\r\nendings\r\n",
    "bare\rcarriage\rreturns",
    "nulls\x00in\x00the\x00middle",
    "combining e\u0301 acute",
    "\ufeffmixed\r\n\x00e\u0301verything\rat once\r\n",
    "\r\ufeff\n",
    "\r\x00\n",
    "trailing bom\ufeff",
    "\u1100\u1161\u11a8 hangul jamo",
]


@pytest.mark.parametrize("text", _CASES)
def test_sanitize_with_map_matches_sanitize(text: str) -> None:
    sanitised, _ = sanitize_with_map(text)
    assert sanitised == LegalChunker.sanitize(text)


@pytest.mark.parametrize("text", _CASES)
def test_map_lengths_agree(text: str) -> None:
    sanitised, offsets = sanitize_with_map(text)
    assert offsets.raw_length == len(text)
    assert offsets.sanitised_length == len(sanitised)


@pytest.mark.parametrize("text", _CASES)
def test_to_raw_is_monotonic(text: str) -> None:
    sanitised, offsets = sanitize_with_map(text)
    previous = -1
    for index in range(len(sanitised) + 1):
        current = offsets.to_raw(index)
        assert current >= previous, f"to_raw({index}) decreased"
        previous = current


@pytest.mark.parametrize("text", _CASES)
def test_round_trip_every_span(text: str) -> None:
    """Every sanitised span re-sanitises from its raw span."""
    sanitised, offsets = sanitize_with_map(text)
    for start in range(len(sanitised) + 1):
        for end in range(start, len(sanitised) + 1):
            raw_start, raw_end = offsets.to_raw_span(start, end)
            assert (
                LegalChunker.sanitize(text[raw_start:raw_end])
                == sanitised[start:end]
            ), f"span ({start}, {end}) of {text!r} did not round-trip"


@pytest.mark.parametrize("text", _CASES)
def test_to_sanitised_inverts_to_raw(text: str) -> None:
    sanitised, offsets = sanitize_with_map(text)
    for index in range(len(sanitised) + 1):
        assert offsets.to_sanitised(offsets.to_raw(index)) == index


# ---------------------------------------------------------------------------
# Identity fast path
# ---------------------------------------------------------------------------


def test_identity_map_for_clean_text() -> None:
    text = "1. Definitions\n\nThis agreement is governed by English law.\n"
    sanitised, offsets = sanitize_with_map(text)
    assert sanitised == text
    assert offsets.is_identity is True
    assert offsets.to_raw(7) == 7
    assert offsets.to_sanitised(7) == 7
    assert offsets.to_raw_span(0, len(text)) == (0, len(text))


def test_non_identity_when_something_changed() -> None:
    _, offsets = sanitize_with_map("a\r\nb")
    assert offsets.is_identity is False


def test_repr_is_informative() -> None:
    _, offsets = sanitize_with_map("a\r\nb")
    text = repr(offsets)
    assert "OffsetMap(" in text and "identity=False" in text


# ---------------------------------------------------------------------------
# Specific run semantics
# ---------------------------------------------------------------------------


def test_crlf_run_maps_to_the_carriage_return() -> None:
    sanitised, offsets = sanitize_with_map("a\r\nb")
    assert sanitised == "a\nb"
    assert [offsets.to_raw(i) for i in range(4)] == [0, 1, 3, 4]


def test_bom_is_skipped_at_the_front() -> None:
    sanitised, offsets = sanitize_with_map("\ufeffab")
    assert sanitised == "ab"
    assert offsets.to_raw(0) == 1
    # A raw index inside a removed run collapses onto the surviving character.
    assert offsets.to_sanitised(0) == 0


def test_null_bytes_are_dropped() -> None:
    sanitised, offsets = sanitize_with_map("a\x00b")
    assert sanitised == "ab"
    assert offsets.to_raw_span(0, 1) == (0, 2)
    assert LegalChunker.sanitize("a\x00b"[0:2]) == "a"


def test_nfd_sequence_collapses_to_its_base_character() -> None:
    raw = "e\u0301x"
    sanitised, offsets = sanitize_with_map(raw)
    assert sanitised == "\u00e9x"
    assert offsets.to_raw(0) == 0
    assert offsets.to_raw(1) == 2
    start, end = offsets.to_raw_span(0, 1)
    assert unicodedata.normalize("NFC", raw[start:end]) == "\u00e9"


def test_hangul_jamo_compose_across_starters() -> None:
    """L + V + T are three starters that NFC folds into one syllable."""
    raw = "\u1100\u1161\u11a8z"
    sanitised, offsets = sanitize_with_map(raw)
    assert sanitised == unicodedata.normalize("NFC", raw)
    assert len(sanitised) == 2
    assert offsets.to_raw(0) == 0
    assert offsets.to_raw(1) == 3
    assert LegalChunker.sanitize(raw[0:3]) == sanitised[0:1]


def test_expanding_composition_widens_to_the_run_start() -> None:
    """U+0958 NFC-expands to two characters; both share one raw offset.

    This is the documented exception to the span round-trip: a span that
    starts *inside* such a run is widened to the run start rather than
    reproduced exactly, because there is no raw offset that names the middle
    of a one-character run.
    """
    raw = "\u0958"
    sanitised, offsets = sanitize_with_map(raw)
    assert len(sanitised) == 2
    assert offsets.to_raw(0) == offsets.to_raw(1) == 0
    assert offsets.to_sanitised(0) == 0


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_sanitize_with_map_rejects_non_str() -> None:
    with pytest.raises(TypeError, match="expects a str"):
        sanitize_with_map(b"bytes")  # type: ignore[arg-type]


def test_to_raw_rejects_out_of_range() -> None:
    _, offsets = sanitize_with_map("a\r\nb")
    with pytest.raises(IndexError, match="sanitised offset"):
        offsets.to_raw(len("a\nb") + 1)
    with pytest.raises(IndexError):
        offsets.to_raw(-1)


def test_to_sanitised_rejects_out_of_range() -> None:
    _, offsets = sanitize_with_map("a\r\nb")
    with pytest.raises(IndexError, match="raw offset"):
        offsets.to_sanitised(5)


def test_offsets_reject_non_int() -> None:
    _, offsets = sanitize_with_map("a\r\nb")
    with pytest.raises(TypeError, match="must be an int"):
        offsets.to_raw("0")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be an int"):
        offsets.to_raw(True)  # type: ignore[arg-type]


def test_to_raw_span_rejects_reversed_span() -> None:
    _, offsets = sanitize_with_map("a\r\nb")
    with pytest.raises(ValueError, match="must be >="):
        offsets.to_raw_span(2, 1)


def test_identity_map_constructed_directly() -> None:
    offsets = OffsetMap(None, 5, 5)
    assert offsets.is_identity
    assert offsets.to_raw(5) == 5
    assert offsets.to_sanitised(5) == 5


# ---------------------------------------------------------------------------
# chunk(raw_offsets=True)
# ---------------------------------------------------------------------------

_RAW_DOCUMENT = (
    "\ufeff1. Definitions\r\n"
    "In this agreement the following terms have the meanings given to "
    "them below.\r\n"
    "\r\n"
    "2. Confidentiality\r\n"
    "Each party shall keep confidential all information disclosed by the "
    "other party under this agreement.\r\n"
    "\r\n"
    "3. Termination\r\n"
    "Either party may terminate this agreement on thirty days written "
    "notice.\r\n"
)


def test_raw_offsets_default_to_the_unset_sentinel() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    for chunk in chunker.chunk(_RAW_DOCUMENT):
        assert chunk.raw_char_start == -1
        assert chunk.raw_char_end == -1


def test_raw_offsets_round_trip_on_a_real_document() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    sanitised = LegalChunker.sanitize(_RAW_DOCUMENT)
    chunks = chunker.chunk(_RAW_DOCUMENT, raw_offsets=True)
    assert chunks
    for chunk in chunks:
        assert chunk.raw_char_start >= 0
        assert chunk.raw_char_end >= chunk.raw_char_start
        raw_slice = _RAW_DOCUMENT[chunk.raw_char_start : chunk.raw_char_end]
        assert (
            LegalChunker.sanitize(raw_slice)
            == sanitised[chunk.char_start : chunk.char_end]
        )


def test_raw_offsets_available_from_metrics_and_iter() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    with_metrics, _ = chunker.chunk_with_metrics(_RAW_DOCUMENT, raw_offsets=True)
    via_iter = list(chunker.chunk_iter(_RAW_DOCUMENT, raw_offsets=True))
    assert [c.to_dict() for c in with_metrics] == [c.to_dict() for c in via_iter]
    assert all(c.raw_char_start >= 0 for c in with_metrics)


def test_raw_offsets_do_not_change_chunking() -> None:
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    plain = chunker.chunk(_RAW_DOCUMENT)
    with_raw = chunker.chunk(_RAW_DOCUMENT, raw_offsets=True)
    assert [c.char_start for c in plain] == [c.char_start for c in with_raw]
    assert [c.content for c in plain] == [c.content for c in with_raw]


def test_raw_offsets_are_serialised() -> None:
    from lexichunk.models import LegalChunk

    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    chunk = chunker.chunk(_RAW_DOCUMENT, raw_offsets=True)[0]
    payload = chunk.to_dict()
    assert payload["raw_char_start"] == chunk.raw_char_start
    assert payload["raw_char_end"] == chunk.raw_char_end
    assert LegalChunk.from_dict(payload).raw_char_start == chunk.raw_char_start


def test_raw_offsets_reject_a_half_populated_pair() -> None:
    from lexichunk.exceptions import ParsingError
    from lexichunk.models import (
        ClauseType,
        DocumentSection,
        HierarchyNode,
        LegalChunk,
    )

    with pytest.raises(ParsingError, match="both be -1"):
        LegalChunk(
            content="x",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1"),
            hierarchy_path="1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction="uk",
            raw_char_start=3,
            raw_char_end=-1,
        )


# ---------------------------------------------------------------------------
# Hypothesis: random documents built from what sanitisation actually rewrites
# ---------------------------------------------------------------------------

# Only shrinking or one-for-one runs, which is what BOM / CRLF / nulls / NFD
# sequences all are. Expanding compositions (U+0958) are excluded on purpose
# and covered by their own test above.
_FRAGMENTS = st.sampled_from(
    [
        "a",
        "b",
        " ",
        "\n",
        "\r\n",
        "\r",
        "\x00",
        "\ufeff",
        "e\u0301",
        "n\u0303",
        "A\u030a",
        "1. Clause\n",
        "text with words ",
    ]
)


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_FRAGMENTS, max_size=40))
def test_property_raw_span_round_trips(fragments: list[str]) -> None:
    raw = "".join(fragments)
    sanitised, offsets = sanitize_with_map(raw)
    assert sanitised == LegalChunker.sanitize(raw)
    for start in range(len(sanitised) + 1):
        end = len(sanitised)
        raw_start, raw_end = offsets.to_raw_span(start, end)
        assert (
            LegalChunker.sanitize(raw[raw_start:raw_end]) == sanitised[start:end]
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_FRAGMENTS, max_size=30))
def test_property_to_sanitised_is_a_left_inverse(fragments: list[str]) -> None:
    raw = "".join(fragments)
    sanitised, offsets = sanitize_with_map(raw)
    for index in range(len(sanitised) + 1):
        assert offsets.to_sanitised(offsets.to_raw(index)) == index


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_FRAGMENTS, min_size=1, max_size=60))
def test_property_chunk_raw_offsets_round_trip(fragments: list[str]) -> None:
    raw = "".join(fragments)
    chunker = LegalChunker(jurisdiction="uk", min_chunk_size=0)
    sanitised = LegalChunker.sanitize(raw)
    for chunk in chunker.chunk(raw, raw_offsets=True):
        assert (
            LegalChunker.sanitize(raw[chunk.raw_char_start : chunk.raw_char_end])
            == sanitised[chunk.char_start : chunk.char_end]
        )
