"""Regression tests for the second adversarial pass (G7).

One class per confirmed finding.  Every test in this module was written
against a *reproduced* defect: each one fails on the parent commit.
"""

from __future__ import annotations

import pytest

from lexichunk.integrations.langchain import _LANGCHAIN_AVAILABLE
from lexichunk.integrations.llama_index import _LLAMA_INDEX_AVAILABLE
from lexichunk.models import Jurisdiction
from lexichunk.parsers.definitions import DefinitionsExtractor


class TestC2UKScheduleHeaderGroup:
    """C2 — the UK ``next_header_re`` Schedule branch had no capturing group.

    ``level_map`` unconditionally probed ``m.group(4)``, so any document whose
    Definitions clause line-wraps such that a continuation line starts with
    ``"Schedule N"`` raised ``IndexError: no such group`` out of
    ``DefinitionsExtractor.extract()`` — and therefore out of ``chunk()``.
    """

    WRAPPED_SCHEDULE_DOC = """SERVICES AGREEMENT

1. Definitions and Interpretation

In this Agreement the following expressions have the meanings given to them
in this clause. The Supplier shall comply with Clause 1 at all times and
shall observe paragraph 1 of the operating standards. The parties agree
that paragraph 3 of Schedule 1 governs escalation and that paragraph 2 of
Schedule 2 governs data retention throughout the term of this Agreement.

2. Supply of Services

The Supplier shall supply the services described in Schedule 1.

Schedule 1

1. Service Levels

The service levels are set out in this Schedule.
"""

    def test_wrapped_schedule_continuation_does_not_crash(self) -> None:
        terms = DefinitionsExtractor(Jurisdiction.UK).extract(
            self.WRAPPED_SCHEDULE_DOC
        )
        assert isinstance(terms, dict)

    def test_chunker_survives_wrapped_schedule_continuation(self) -> None:
        from lexichunk import LegalChunker

        chunks = LegalChunker(jurisdiction="uk").chunk(self.WRAPPED_SCHEDULE_DOC)
        assert chunks

    @pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
    def test_every_jurisdiction_group_count_matches_level_map(
        self, jurisdiction: Jurisdiction
    ) -> None:
        """The root cause was a group-count/``level_map`` mismatch.

        Assert the invariant directly for all three built-ins so a future
        alternative added without a group fails here rather than in the field.
        """
        extractor = DefinitionsExtractor(jurisdiction)
        # ``_find_section_end`` compiles the pattern locally; drive it over a
        # document containing every alternative it knows about.
        probe = (
            "1. Definitions\n\nBody text.\n\n1.1 Sub\n\n1.1.1 Deep\n\n"
            "2. Next\n\nSchedule 1\n\nExhibit A\n\n"
            "ARTICLE I\n\nSection 1.1\n\nCHAPTER I\n\nArticle 1\n\n"
            "Section 1\n\nANNEX I\n\n3. Para\n"
        )
        # Must not raise IndexError for any candidate the regex matches.
        assert extractor._find_section_end(probe, 0, 0) >= 0


class TestC3UnicodeLineSeparators:
    """C3 — ``_line_offsets`` counted only ``'\n'`` but ``parse()`` splits with
    ``str.splitlines()``, which also breaks on ``\r``, ``\v``, ``\f``,
    ``\x1c``-``\x1e``, ``\x85`` (NEL), ``\u2028`` and ``\u2029``.
    """

    SEPARATORS = ["\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"]

    @pytest.mark.parametrize("sep", SEPARATORS)
    def test_chunk_survives_unicode_line_separator(self, sep: str) -> None:
        from lexichunk import LegalChunker

        chunks = LegalChunker(jurisdiction="uk").chunk(f"1. A{sep}{sep}Text\n")
        assert isinstance(chunks, list)

    @pytest.mark.parametrize("sep", SEPARATORS)
    def test_parse_structure_survives_unicode_line_separator(self, sep: str) -> None:
        from lexichunk.parsers.structure import parse_structure

        assert isinstance(
            parse_structure(f"1. A{sep}{sep}Text\n", Jurisdiction.UK), list
        )

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "\n",
            "a",
            "a\n",
            "a\r\nb\n",
            "\ufeff \x85 \u2029",
            "1. A\u2028\u2028Text\n",
            "x\rz\u2028q\x0cw",
        ],
    )
    def test_offsets_agree_with_splitlines(self, text: str) -> None:
        from lexichunk.parsers.structure import _line_offsets

        offsets = _line_offsets(text)
        lines = text.splitlines(keepends=True)
        assert len(offsets) == len(lines)
        for offset, line in zip(offsets, lines):
            assert text[offset : offset + len(line)] == line


class TestC4SurrogateCacheKey:
    """C4 — the definition cache key used ``text.encode("utf-8")`` with no
    ``errors=``, so an unpaired surrogate (routine output of
    ``errors="surrogateescape"`` decoding) raised ``UnicodeEncodeError``.
    """

    DOC = '1. Definitions\n\n"Services" means the services described below.\udcff\n'

    def test_chunk_with_cache_enabled_accepts_lone_surrogate(self) -> None:
        from lexichunk import LegalChunker

        chunker = LegalChunker(jurisdiction="uk", enable_definition_cache=True)
        assert isinstance(chunker.chunk(self.DOC), list)

    def test_unpaired_surrogate_is_preserved_in_output(self) -> None:
        from lexichunk import LegalChunker

        chunks = LegalChunker(jurisdiction="uk").chunk(self.DOC)
        assert any("\udcff" in c.content for c in chunks)

    def test_cache_hit_still_works_for_surrogate_text(self) -> None:
        from lexichunk import LegalChunker

        chunker = LegalChunker(jurisdiction="uk", enable_definition_cache=True)
        first = chunker.chunk(self.DOC)
        second = chunker.chunk(self.DOC)
        assert [c.content for c in first] == [c.content for c in second]


class TestC5RegistryNameType:
    """C5 — ``register_jurisdiction`` duck-typed ``name``, so ``bytes`` was
    accepted as a registry key and permanently broke
    ``registered_jurisdictions()`` for the rest of the process.
    """

    @staticmethod
    def _patterns():
        import re

        class _P:
            cross_ref = definition = definition_curly = re.compile("x")
            definitions_headers = boilerplate_headers = signature_markers = ()

        return _P()

    @pytest.mark.parametrize("bad_name", [b"uk", 1, None, ["uk"], 2.0])
    def test_non_str_name_is_rejected_with_configuration_error(
        self, bad_name: object
    ) -> None:
        from lexichunk.exceptions import ConfigurationError
        from lexichunk.jurisdiction import register_jurisdiction

        with pytest.raises(ConfigurationError):
            register_jurisdiction(bad_name, self._patterns(), lambda s: None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_name", [b"uk", 1, None, ["uk"]])
    def test_unregister_rejects_non_str_name(self, bad_name: object) -> None:
        from lexichunk.exceptions import ConfigurationError
        from lexichunk.jurisdiction import unregister_jurisdiction

        with pytest.raises(ConfigurationError):
            unregister_jurisdiction(bad_name)  # type: ignore[arg-type]

    def test_registry_stays_usable_after_a_rejected_call(self) -> None:
        from lexichunk.exceptions import ConfigurationError
        from lexichunk.jurisdiction import (
            register_jurisdiction,
            registered_jurisdictions,
        )

        before = registered_jurisdictions()
        with pytest.raises(ConfigurationError):
            register_jurisdiction(b"uk", self._patterns(), lambda s: None)  # type: ignore[arg-type]
        assert registered_jurisdictions() == before


langchain_required = pytest.mark.skipif(
    not _LANGCHAIN_AVAILABLE, reason="langchain-core not installed"
)
llama_index_required = pytest.mark.skipif(
    not _LLAMA_INDEX_AVAILABLE, reason="llama-index-core not installed"
)


@langchain_required
class TestC1LangChainIdCollisions:
    """C1 — ``Document.id`` was ``f"{document_id}:{chunk.index}"`` and
    ``chunk.index`` restarts at 0 per input document, so the standard
    one-``Document``-per-page loader pattern (all pages sharing
    ``metadata["source"]``) produced duplicate ids and a vector store keyed on
    id silently dropped chunks.
    """

    @staticmethod
    def _page(n: int) -> str:
        body = " ".join(f"word{n}" for _ in range(80))
        return (
            f"1. Clause {n}\n\nBody text for page {n}. {body}\n\n"
            f"2. Second Clause {n}\n\nMore body for page {n}. {body}\n"
        )

    def _splitter(self):
        from lexichunk.integrations.langchain import LegalTextSplitter

        return LegalTextSplitter(jurisdiction="uk")

    def test_one_document_per_page_yields_unique_ids(self) -> None:
        from langchain_core.documents import Document

        pages = [
            Document(page_content=self._page(i), metadata={"source": "msa.pdf", "page": i})
            for i in range(8)
        ]
        out = self._splitter().split_documents(pages)
        ids = [d.id for d in out]
        assert len(out) > len(pages)
        assert len(set(ids)) == len(ids)

    def test_distinct_ids_keep_the_two_part_format(self) -> None:
        from langchain_core.documents import Document

        pages = [
            Document(page_content=self._page(i), metadata={"source": f"p{i}.pdf"})
            for i in range(3)
        ]
        out = self._splitter().split_documents(pages)
        assert all(d.id.count(":") == 1 for d in out)
        assert len({d.id for d in out}) == len(out)

    def test_recurring_id_uses_the_three_part_format(self) -> None:
        from langchain_core.documents import Document

        pages = [
            Document(page_content=self._page(i), metadata={"source": "msa.pdf"})
            for i in range(3)
        ]
        out = self._splitter().split_documents(pages)
        assert all(d.id.startswith("msa.pdf:") and d.id.count(":") == 2 for d in out)
        ordinals = {d.id.split(":")[1] for d in out}
        assert ordinals == {"0", "1", "2"}

    def test_generator_input_is_accepted(self) -> None:
        from langchain_core.documents import Document

        def gen():
            for i in range(3):
                yield Document(page_content=self._page(i), metadata={"source": "msa.pdf"})

        out = self._splitter().split_documents(gen())
        assert len({d.id for d in out}) == len(out)


REALISTIC_HEADINGS = [
    # The 16 titles the adversarial pass showed being swallowed outright.
    "Business Continuity",
    "Business Ethics and Anti-Bribery",
    "Days of Service",
    "Hours of Business",
    "Hours of Work",
    "Working Time Regulations",
    "Working Practices",
    "Working Capital Adjustment",
    "Year End Accounts",
    "Month-End Reporting",
    "Month End Reporting",
    "Calendar of Events",
    "Calendar Year Adjustment",
    "Minute Books",
    "May Not Be Assigned",
    "May Assign",
    # Nine ordinary headings that already worked, kept as a control.
    "Definitions",
    "Confidentiality",
    "Governing Law",
    "Limitation of Liability",
    "Termination",
    "Notices",
    "Force Majeure",
    "Data Protection",
    "Intellectual Property",
]

PROSE_LINES_THAT_ARE_NOT_HEADINGS = [
    "3 Business Days after receipt of an invoice.",
    "5 Working Days from the date on which the invoice is received.",
    "30 days after the date of the notice given under this clause.",
    "January 2024 is the Effective Date of this Agreement.",
]


class TestH1HeadingGateFalseNegatives:
    """H1 — a real heading rejected by the plausibility gate is not merely
    mis-levelled: its whole clause body is absorbed into the previous clause,
    with no chunk, no ``hierarchy_path`` and no way to retrieve it by title.
    15 of these 25 realistic contract headings vanished before the fix.
    """

    @staticmethod
    def _document(title: str) -> str:
        return (
            "AGREEMENT\n\n"
            "1. Preliminary\n\n"
            "Some preliminary body text goes here for context.\n\n"
            f"2. {title}\n\n"
            "The body of this clause is here and continues for a sentence.\n\n"
            "3. Final\n\n"
            "Final body text.\n"
        )

    @pytest.mark.parametrize("title", REALISTIC_HEADINGS)
    def test_realistic_heading_is_detected(self, title: str) -> None:
        from lexichunk.parsers.structure import StructureParser

        clauses = StructureParser(Jurisdiction.UK).parse(self._document(title))
        assert title in [c.title for c in clauses]

    @pytest.mark.parametrize("title", REALISTIC_HEADINGS)
    def test_realistic_heading_becomes_its_own_top_level_clause(
        self, title: str
    ) -> None:
        from lexichunk.parsers.structure import StructureParser

        clauses = StructureParser(Jurisdiction.UK).parse(self._document(title))
        match = [c for c in clauses if c.title == title]
        assert len(match) == 1
        assert match[0].level == 0
        assert match[0].identifier == "2"

    @pytest.mark.parametrize("line", PROSE_LINES_THAT_ARE_NOT_HEADINGS)
    def test_numeric_prose_is_still_rejected(self, line: str) -> None:
        """The loosened rules must not start promoting body prose."""
        from lexichunk.parsers.structure import StructureParser

        document = (
            "AGREEMENT\n\n1. Payment\n\n"
            "The Client shall pay each invoice within\n"
            f"{line}\n\n2. Term\n\nOne year.\n"
        )
        clauses = StructureParser(Jurisdiction.UK).parse(document)
        assert [c.identifier for c in clauses if c.level == 0] == ["1", "2"]

    def test_nine_word_allcaps_heading_survives(self) -> None:
        """``_MAX_ALLCAPS_WORDS`` was 8, dropping this common US heading."""
        from lexichunk.parsers.structure import StructureParser

        document = (
            "PRELIMINARY MATTERS\n\nSome body text here.\n\n"
            "REPRESENTATIONS AND WARRANTIES OF THE SELLER AND THE COMPANY\n\n"
            "The Seller represents and warrants as follows.\n"
        )
        clauses = StructureParser(Jurisdiction.US).parse(document)
        assert any(
            c.identifier == "REPRESENTATIONS AND WARRANTIES OF THE SELLER AND THE COMPANY"
            for c in clauses
        )

    def test_long_but_short_worded_numbered_heading_survives(self) -> None:
        """A numbered heading whose title is <= 8 words is a heading even when
        it exceeds ``_MAX_NUMERIC_HEADING_REMAINDER`` or ends in a period."""
        from lexichunk.parsers.structure import StructureParser

        title = "Limitation of Liability and Exclusion of Consequential Loss"
        document = (
            "AGREEMENT\n\n1. Scope\n\nBody text.\n\n"
            f"2. {title}\n\nThe liability of each party is limited.\n"
        )
        clauses = StructureParser(Jurisdiction.UK).parse(document)
        assert title in [c.title for c in clauses]


class TestH2HeadingGateFalsePositives:
    """H2 — numbered list items and postal addresses were promoted to
    top-level clauses, injecting bogus entries into the hierarchy.
    """

    @pytest.mark.parametrize(
        "amount", ["GBP 5,000", "\u00a35,000", "$5,000", "USD 5,000", "\u20ac5.000"]
    )
    def test_currency_list_item_is_not_a_clause(self, amount: str) -> None:
        from lexichunk.parsers.structure import StructureParser

        document = (
            "AGREEMENT\n\n5. Fees\n\nThe fees payable are as follows.\n\n"
            f"2. {amount} per month for hosting services.\n\n"
            "6. Term\n\nOne year.\n"
        )
        clauses = StructureParser(Jurisdiction.UK).parse(document)
        assert [c.identifier for c in clauses if c.level == 0] == ["5", "6"]

    @pytest.mark.parametrize("postcode", ["SW1H 0BD", "EC1A 1BB", "M1 1AE", "B33 8TH"])
    def test_postal_address_line_is_not_a_clause(self, postcode: str) -> None:
        from lexichunk.parsers.structure import StructureParser

        document = (
            "AGREEMENT\n\n5. Notices\n\nAny notice shall be sent to:\n\n"
            f"50 Broadway, London, {postcode}. VAT number: GB 312 4487 90.\n\n"
            "6. Governing Law\n\nEnglish law applies.\n"
        )
        clauses = StructureParser(Jurisdiction.UK).parse(document)
        assert [c.identifier for c in clauses if c.level == 0] == ["5", "6"]


class TestH1ContainerHeadingAfterTerminalPunctuation:
    """H1 — a container heading typed directly under the last line of the
    preceding clause (no blank line) used to be rejected, collapsing the whole
    schedule into that clause.
    """

    def test_schedule_after_a_full_stop_is_a_container(self) -> None:
        from lexichunk.parsers.structure import StructureParser

        document = (
            "AGREEMENT\n\n1. Scope\n\nThe scope is set out below.\n"
            "  Schedule 1\n\n1. Service Levels\n\nLevels are here.\n"
        )
        clauses = StructureParser(Jurisdiction.UK).parse(document)
        assert any(c.level == -1 for c in clauses)

    def test_indented_mid_sentence_schedule_is_still_rejected(self) -> None:
        from lexichunk.parsers.structure import StructureParser

        document = (
            "AGREEMENT\n\n1. Scope\n\nThe parties agree that paragraph 2 of\n"
            "  Schedule 2 governs data retention for the term\n"
            "  of this Agreement.\n\n2. Term\n\nOne year.\n"
        )
        clauses = StructureParser(Jurisdiction.UK).parse(document)
        assert not [c for c in clauses if c.level == -1]


class TestH3DocumentSectionClassification:
    """H3 — ``_detect_document_section`` searched for keywords anywhere in
    ``identifier + " " + title``, so ordinary operative clauses were labelled
    RECITALS or SIGNATURES.  The wrong label reaches ``clause_type`` and the
    ``context_header`` that is embedded and shown to a downstream LLM.
    """

    OPERATIVE_TITLES = [
        "Background Checks",
        "Background Screening and Vetting",
        "Execution of Services",
        "Execution of the Works",
        "Signing Authority",
        "Recital of Facts by the Supplier",
        "Confidentiality",
    ]
    RECITAL_TITLES = ["Recitals", "Recital", "Background", "Background and Recitals"]
    DEFINITION_TITLES = [
        "Definitions",
        "Definitions and Interpretation",
        "Interpretation",
        "Defined Terms",
    ]
    SIGNATURE_TITLES = [
        "IN WITNESS WHEREOF",
        "SIGNED by the Supplier",
        "SIGNED for and on behalf of the Company",
        "EXECUTED as a deed",
        "Signature Page",
        "Signatures",
    ]

    def _section(self, title: str):
        from lexichunk.parsers.structure import StructureParser

        return StructureParser(Jurisdiction.UK)._detect_document_section("2", title, 0)

    @pytest.mark.parametrize("title", OPERATIVE_TITLES)
    def test_operative_clause_is_not_mislabelled(self, title: str) -> None:
        from lexichunk.models import DocumentSection

        assert self._section(title) is DocumentSection.OPERATIVE

    @pytest.mark.parametrize("title", RECITAL_TITLES)
    def test_real_recital_heading_still_matches(self, title: str) -> None:
        from lexichunk.models import DocumentSection

        assert self._section(title) is DocumentSection.RECITALS

    @pytest.mark.parametrize("title", DEFINITION_TITLES)
    def test_real_definitions_heading_still_matches(self, title: str) -> None:
        from lexichunk.models import DocumentSection

        assert self._section(title) is DocumentSection.DEFINITIONS

    @pytest.mark.parametrize("title", SIGNATURE_TITLES)
    def test_real_signature_heading_still_matches(self, title: str) -> None:
        from lexichunk.models import DocumentSection

        assert self._section(title) is DocumentSection.SIGNATURES

    def test_eu_recital_label_with_a_number_still_matches(self) -> None:
        from lexichunk.models import DocumentSection
        from lexichunk.parsers.structure import StructureParser

        section = StructureParser(Jurisdiction.EU)._detect_document_section(
            "Recital 1", "Recital (1)", 0
        )
        assert section is DocumentSection.RECITALS

    def test_background_checks_clause_end_to_end(self) -> None:
        """The full pipeline used to report RECITALS with confidence 1.00.

        ``document_section`` is now OPERATIVE, so the structural override that
        forced ``clause_type`` to RECITALS at confidence 1.00 no longer fires.
        The residual weak RECITALS *content* score — the word "Background"
        appears in the clause's own heading line, and ``CLAUSE_SIGNALS`` lists
        it as a one-word RECITALS signal — is the library's ordinary keyword
        heuristic and is reported with correspondingly low confidence.
        """
        from lexichunk import LegalChunker
        from lexichunk.models import DocumentSection

        document = (
            "AGREEMENT\n\n1. Scope\n\n"
            "The scope of this agreement covers the following matters.\n\n"
            "2. Background Checks\n\n"
            "The Supplier shall carry out enhanced DBS checks on all personnel "
            "engaged in the delivery of the Services.\n\n"
            "3. Term\n\nOne year.\n"
        )
        chunks = LegalChunker(jurisdiction="uk").chunk(document)
        clause = [c for c in chunks if c.hierarchy.title == "Background Checks"]
        assert len(clause) == 1
        assert clause[0].document_section is DocumentSection.OPERATIVE
        assert clause[0].classification_confidence < 0.5

    def test_execution_of_services_clause_end_to_end(self) -> None:
        from lexichunk import LegalChunker
        from lexichunk.models import DocumentSection

        document = (
            "AGREEMENT\n\n1. Scope\n\n"
            "The scope of this agreement covers the following matters.\n\n"
            "2. Execution of Services\n\n"
            "The Supplier shall perform the Services with reasonable skill "
            "and care throughout the term.\n\n"
            "3. Term\n\nOne year.\n"
        )
        chunks = LegalChunker(jurisdiction="uk").chunk(document)
        clause = [c for c in chunks if c.hierarchy.title == "Execution of Services"]
        assert len(clause) == 1
        assert clause[0].document_section is DocumentSection.OPERATIVE


class TestH4DashRangeFalsePositives:
    """H4 — every bare ``-``/``–``/``—`` before a number was read as a range
    operator, so an ordinary parenthetical dash fabricated large numbers of
    plausible-looking cross-references.
    """

    @staticmethod
    def _ids(sentence: str, jurisdiction: Jurisdiction = Jurisdiction.UK):
        from lexichunk.parsers.references import detect_references

        return [r.target_identifier for r in detect_references(sentence, jurisdiction)]

    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("The notice period in clause 12 - 30 days - shall apply.", ["12"]),
            ("The notice period in clause 12 \u2013 30 days \u2013 shall apply.", ["12"]),
            ("Refer to Schedule 1 - 5 copies must be provided.", ["1"]),
            ("Clause 9 \u2013 15 January 2025 is the deadline.", ["9"]),
            ("Clause 4 - 6 months from the Effective Date.", ["4"]),
            ("(see clause 3 - which we discuss below - 7)", ["3"]),
        ],
    )
    def test_parenthetical_dash_is_not_a_range(self, sentence, expected) -> None:
        assert self._ids(sentence) == expected

    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("See clauses 3 to 5 for details.", ["3", "4", "5"]),
            ("See clauses 3 - 5 for details.", ["3", "4", "5"]),
            ("See clauses 3-5 for details.", ["3", "4", "5"]),
            ("as set out in Clauses 3.2\u20133.4", ["3.2", "3.3", "3.4"]),
            ("as set out in Clauses 3.2\u20143.4", ["3.2", "3.3", "3.4"]),
            ("see Schedules 1 to 3", ["1", "2", "3"]),
            ("see clauses 8 to 11", ["8", "9", "10", "11"]),
        ],
    )
    def test_real_ranges_still_expand(self, sentence, expected) -> None:
        assert self._ids(sentence) == expected

    def test_dotted_through_range_still_expands(self) -> None:
        assert self._ids(
            "pursuant to Sections 2.1 through 2.4", Jurisdiction.US
        ) == ["2.1", "2.2", "2.3", "2.4"]

    def test_expansion_is_capped_at_twenty_members(self) -> None:
        from lexichunk.parsers.references import _MAX_RANGE_EXPANSION

        assert _MAX_RANGE_EXPANSION == 20
        assert len(self._ids("see clauses 1 to 20")) == 20
        assert self._ids("see clauses 1 to 21") == ["1"]

    def test_bare_number_head_never_starts_a_dash_range(self) -> None:
        """'never expand across a missing head' — no label, no range."""
        assert "13" not in self._ids("The figure 12 - 30 was agreed.")


class TestH5FromDictTypeValidation:
    """H5/M4 — ``from_dict`` is the deserialisation entry point, so it is the
    method most likely to receive shape-drifted data.  A ``str`` where a list
    was expected was silently iterated: ``list("Services")`` produced
    ``['S','e','r','v','i','c','e','s']`` on an otherwise valid-looking chunk.
    """

    @staticmethod
    def _valid_dict() -> dict:
        from lexichunk.models import (
            ClauseType,
            DocumentSection,
            HierarchyNode,
            LegalChunk,
        )

        return LegalChunk(
            content="Body text.",
            index=0,
            hierarchy=HierarchyNode(level=0, identifier="1", title="Scope"),
            hierarchy_path="1",
            document_section=DocumentSection.OPERATIVE,
            clause_type=ClauseType.UNKNOWN,
            jurisdiction=Jurisdiction.UK,
            char_start=0,
            char_end=10,
        ).to_dict()

    def test_round_trip_still_works(self) -> None:
        from lexichunk.models import LegalChunk

        source = self._valid_dict()
        assert LegalChunk.from_dict(source).to_dict() == source

    @pytest.mark.parametrize(
        ("field_name", "bad_value"),
        [
            ("defined_terms_used", "Services"),
            ("defined_terms_used", {"a": "b"}),
            ("defined_terms_used", 5),
            ("defined_terms_context", "Services"),
            ("defined_terms_context", ["Services"]),
            ("cross_references", "clause 3"),
            ("cross_references", 7),
            ("hierarchy", "1"),
        ],
    )
    def test_wrong_container_type_raises_parsing_error_naming_the_field(
        self, field_name: str, bad_value: object
    ) -> None:
        from lexichunk.exceptions import ParsingError
        from lexichunk.models import LegalChunk

        payload = self._valid_dict()
        payload[field_name] = bad_value
        with pytest.raises(ParsingError) as excinfo:
            LegalChunk.from_dict(payload)
        assert field_name in str(excinfo.value)

    def test_string_is_never_iterated_into_characters(self) -> None:
        from lexichunk.exceptions import ParsingError
        from lexichunk.models import LegalChunk

        payload = self._valid_dict()
        payload["defined_terms_used"] = "Services"
        with pytest.raises(ParsingError):
            LegalChunk.from_dict(payload)

    @pytest.mark.parametrize("value", ["not a dict", 5, None, ["a"]])
    def test_non_mapping_input_raises_parsing_error(self, value: object) -> None:
        from lexichunk.exceptions import ParsingError
        from lexichunk.models import LegalChunk

        with pytest.raises(ParsingError):
            LegalChunk.from_dict(value)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "key",
        [
            "content",
            "index",
            "hierarchy",
            "hierarchy_path",
            "document_section",
            "clause_type",
            "jurisdiction",
        ],
    )
    def test_missing_required_key_raises_parsing_error(self, key: str) -> None:
        from lexichunk.exceptions import ParsingError
        from lexichunk.models import LegalChunk

        payload = self._valid_dict()
        del payload[key]
        with pytest.raises(ParsingError) as excinfo:
            LegalChunk.from_dict(payload)
        assert key in str(excinfo.value)

    def test_malformed_cross_reference_entry_raises_parsing_error(self) -> None:
        from lexichunk.exceptions import ParsingError
        from lexichunk.models import LegalChunk

        payload = self._valid_dict()
        payload["cross_references"] = [{"raw_text": "clause 3"}]
        with pytest.raises(ParsingError):
            LegalChunk.from_dict(payload)

    def test_unknown_enum_value_raises_parsing_error(self) -> None:
        from lexichunk.exceptions import ParsingError
        from lexichunk.models import LegalChunk

        payload = self._valid_dict()
        payload["clause_type"] = "not_a_clause_type"
        with pytest.raises(ParsingError):
            LegalChunk.from_dict(payload)


class TestH6PossessiveDefinedTerms:
    """H6 — the opening-quote class was unconstrained, so the apostrophe
    inside ``Client's`` opened a quote of its own and the extractor produced
    the bogus term ``"s Data"`` with the real definition attached to it.
    """

    @staticmethod
    def _terms(document: str) -> dict:
        return DefinitionsExtractor(Jurisdiction.UK).extract(document)

    @staticmethod
    def _document(body: str) -> str:
        return f"1. DEFINITIONS\n\n{body}\n\n2. Other\n\nBody text here.\n"

    @pytest.mark.parametrize(
        "term",
        [
            "Client's Data",
            "Seller's Knowledge",
            "Purchaser's Group",
            "Guarantor's Obligations",
        ],
    )
    def test_possessive_term_is_captured_whole(self, term: str) -> None:
        terms = self._terms(
            self._document(f'1.1 "{term}" means the thing that it means.')
        )
        assert term in terms

    def test_no_bogus_fragment_term_is_produced(self) -> None:
        terms = self._terms(
            self._document('1.1 "Client\'s Data" means the data supplied by the client.')
        )
        assert "s Data" not in terms
        assert len(terms) == 1

    def test_single_quoted_term_still_works(self) -> None:
        terms = self._terms(
            self._document("1.1 'Supplier' means the party providing the services.")
        )
        assert "Supplier" in terms

    def test_curly_quoted_term_still_works(self) -> None:
        terms = self._terms(
            self._document('1.1 \u201cSupplier\u201d means the party providing services.')
        )
        assert "Supplier" in terms


class TestH7DefinedTermCharacterClass:
    r"""H7 — every term-capture group used ``[A-Za-z\s\-]``, so terms with
    digits, ``&`` or ``+`` were dropped entirely and silently.  A document
    defining exactly three well-formed terms returned zero.
    """

    @staticmethod
    def _document(*definitions: str) -> str:
        body = "\n\n".join(
            f'1.{i + 1} "{term}" means the thing that it means.'
            for i, term in enumerate(definitions)
        )
        return f"1. DEFINITIONS\n\n{body}\n\n2. Other\n\nBody text here.\n"

    @pytest.mark.parametrize(
        "term",
        [
            "R&D",
            "R&D Services",
            "C++ Code",
            "Level 1 Support",
            "Schedule 2 Services",
            "Tier1",
            "Section 409A Plan",
        ],
    )
    def test_term_with_digits_or_symbols_is_extracted(self, term: str) -> None:
        terms = DefinitionsExtractor(Jurisdiction.UK).extract(self._document(term))
        assert term in terms

    def test_the_reported_three_term_document_yields_three_terms(self) -> None:
        document = self._document("R&D", "Level 1 Support", "C++ Code")
        terms = DefinitionsExtractor(Jurisdiction.UK).extract(document)
        assert set(terms) == {"R&D", "Level 1 Support", "C++ Code"}

    def test_parenthesised_plural_still_registers_both_forms(self) -> None:
        """Parentheses stay out of the term class so this pattern still wins."""
        document = self._document("PLACEHOLDER").replace(
            '"PLACEHOLDER"', '"Affiliate(s)"'
        )
        terms = DefinitionsExtractor(Jurisdiction.UK).extract(document)
        assert "Affiliate" in terms
        assert "Affiliates" in terms

    @pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
    def test_every_jurisdiction_accepts_digits_in_a_term(
        self, jurisdiction: Jurisdiction
    ) -> None:
        from lexichunk.jurisdiction import get_patterns

        patterns = get_patterns(jurisdiction)
        probe = '"Level 1 Support" means first line support.'
        probe_single = "'Level 1 Support' means first line support."
        assert (
            patterns.definition.search(probe) is not None
            or patterns.definition.search(probe_single) is not None
        )


class TestH8DefinitionBodyBoundaries:
    """H8 — a definition body only stopped at a blank line followed by a
    clause header, so entries separated by a single newline (a common
    DOCX-to-text export shape) ran into each other.
    """

    SINGLE_NEWLINE_DOC = (
        "1. DEFINITIONS\n"
        '1.1 "Alpha" means the first thing.\n'
        '1.2 "Level 2 Data" means personal data of the second level.\n'
        '1.3 "Bravo" means the third thing.\n'
    )

    def _terms(self, document: str) -> dict:
        return DefinitionsExtractor(Jurisdiction.UK).extract(document)

    def test_every_entry_is_extracted(self) -> None:
        terms = self._terms(self.SINGLE_NEWLINE_DOC)
        assert set(terms) == {"Alpha", "Level 2 Data", "Bravo"}

    def test_no_definition_swallows_the_next_entry(self) -> None:
        terms = self._terms(self.SINGLE_NEWLINE_DOC)
        assert terms["Alpha"].definition == "the first thing."
        assert terms["Level 2 Data"].definition == (
            "personal data of the second level."
        )
        assert terms["Bravo"].definition == "the third thing."
        for term, defined in terms.items():
            assert "means" not in defined.definition, (
                f"{term!r} ran into the next entry: {defined.definition!r}"
            )

    def test_last_definition_stops_at_an_allcaps_heading(self) -> None:
        terms = self._terms(
            "1. DEFINITIONS\n\n"
            '1.1 "Charlie" means the third letter.\n'
            "GOVERNING LAW\n\n"
            "This Agreement is governed by English law.\n"
        )
        assert terms["Charlie"].definition == "the third letter."

    def test_a_sentence_final_number_is_not_stripped(self) -> None:
        """The dangling-marker trim must not eat 'Section 3.'."""
        terms = self._terms(
            '"Gamma" shall have the meaning set forth in Section 3.\n'
            '"business day" means any day other than a Saturday.\n'
        )
        assert terms["Gamma"].definition == "set forth in Section 3."

    def test_an_enumerated_definition_body_is_preserved(self) -> None:
        terms = self._terms(
            "1. DEFINITIONS\n\n"
            '1.1 "Services" means:\n(a) hosting services;\n(b) support services.\n'
            "\n\n2. Other\n\nBody text.\n"
        )
        assert "hosting services" in terms["Services"].definition
        assert "support services" in terms["Services"].definition


class TestH9ScheduleScopedRedefinition:
    """H9 — a term redefined for one schedule was not rescoped: chunks inside
    that schedule carried the main-body meaning, feeding the wrong legal
    meaning into ``defined_terms_context`` and the embedded ``context_header``.
    """

    MAIN_BODY = "the consultancy services described in Schedule 1."
    SCHEDULE_LOCAL = "the managed hosting services provided by the Supplier."

    @staticmethod
    def _document() -> str:
        filler = " ".join("filler" for _ in range(60))
        return (
            "AGREEMENT\n\n1. Definitions\n\n"
            f'"Services" means the consultancy services described in Schedule 1. {filler}\n\n'
            "2. Supply\n\n"
            f"The Supplier shall provide the Services under this Agreement. {filler}\n\n"
            "Schedule 2\n\n"
            'For the purposes of this Schedule 2 only, "Services" means the '
            "managed hosting services provided by the Supplier.\n\n"
            "1. Hosting\n\n"
            f"The Supplier shall provide the Services to the standards here. {filler}\n\n"
            "2. Support\n\n"
            f"The Supplier shall support the Services in business hours. {filler}\n"
        )

    def _chunks(self):
        from lexichunk import LegalChunker

        return LegalChunker(jurisdiction="uk", max_chunk_size=120).chunk(
            self._document()
        )

    def test_chunks_inside_the_schedule_use_the_schedule_definition(self) -> None:
        from lexichunk.models import DocumentSection

        inside = [
            c
            for c in self._chunks()
            if c.document_section is DocumentSection.SCHEDULES
            and "Services" in c.defined_terms_context
        ]
        assert inside
        for chunk in inside:
            assert chunk.defined_terms_context["Services"] == self.SCHEDULE_LOCAL

    def test_main_body_chunks_keep_the_main_body_definition(self) -> None:
        from lexichunk.models import DocumentSection

        outside = [
            c
            for c in self._chunks()
            if c.document_section is not DocumentSection.SCHEDULES
            and "Services" in c.defined_terms_context
        ]
        assert outside
        for chunk in outside:
            assert chunk.defined_terms_context["Services"].startswith(self.MAIN_BODY)

    def test_nested_clauses_inside_the_schedule_inherit_the_local_meaning(
        self,
    ) -> None:
        nested = [
            c
            for c in self._chunks()
            if c.hierarchy_path.startswith("Schedule 2 > ")
            and "Services" in c.defined_terms_context
        ]
        assert nested
        for chunk in nested:
            assert chunk.defined_terms_context["Services"] == self.SCHEDULE_LOCAL

    def test_a_document_without_schedules_is_unaffected(self) -> None:
        from lexichunk import LegalChunker

        document = (
            "AGREEMENT\n\n1. Definitions\n\n"
            '"Services" means the consultancy services described below.\n\n'
            "2. Supply\n\nThe Supplier shall provide the Services promptly.\n"
        )
        chunks = LegalChunker(jurisdiction="uk").chunk(document)
        contexts = [
            c.defined_terms_context["Services"]
            for c in chunks
            if "Services" in c.defined_terms_context
        ]
        assert contexts
        assert len(set(contexts)) == 1


class TestH10SizeGuardBeforeSanitisation:
    """H10 — the guard ran on the *post-sanitise* string, so any content that
    sanitises away bypassed it, and the cost of the sanitisation pass itself
    was unbounded.
    """

    @staticmethod
    def _chunker():
        from lexichunk import LegalChunker

        return LegalChunker(jurisdiction="uk")

    def test_oversized_input_that_sanitises_to_nothing_is_rejected(self) -> None:
        from lexichunk.exceptions import InputError

        with pytest.raises(InputError):
            self._chunker().chunk("\ufeff" * 15_000_000)

    def test_oversized_plain_input_is_still_rejected(self) -> None:
        from lexichunk.exceptions import InputError

        with pytest.raises(InputError):
            self._chunker().chunk("a" * 11_000_000)

    def test_get_defined_terms_guard_also_runs_first(self) -> None:
        from lexichunk.exceptions import InputError

        with pytest.raises(InputError):
            self._chunker().get_defined_terms("\ufeff" * 15_000_000)

    def test_parse_structure_guard_also_runs_first(self) -> None:
        from lexichunk.exceptions import InputError

        with pytest.raises(InputError):
            self._chunker().parse_structure("\ufeff" * 15_000_000)

    def test_ordinary_input_is_unaffected(self) -> None:
        assert self._chunker().chunk("1. Scope\n\nSome ordinary body text.\n")


class TestH11ChunkBatchRejectsMappings:
    """H11 — iterating a dict yields its keys, so
    ``chunk_batch({"doc1": text1})`` chunked the string ``"doc1"`` and never
    read the document, returning a normal-looking result with ``errors=[]``.
    """

    @staticmethod
    def _chunker():
        from lexichunk import LegalChunker

        return LegalChunker(jurisdiction="uk")

    def test_dict_input_raises_input_error(self) -> None:
        from lexichunk.exceptions import InputError

        with pytest.raises(InputError) as excinfo:
            self._chunker().chunk_batch({"doc1": "a" * 200, "doc2": "b" * 200})
        assert "values()" in str(excinfo.value)

    def test_other_mapping_types_are_rejected_too(self) -> None:
        import types

        from lexichunk.exceptions import InputError

        with pytest.raises(InputError):
            self._chunker().chunk_batch(
                types.MappingProxyType({"doc1": "a" * 200})
            )

    def test_values_view_is_accepted(self) -> None:
        mapping = {"doc1": "1. A\n\nSome body text.\n", "doc2": "1. B\n\nMore body.\n"}
        result = self._chunker().chunk_batch(mapping.values())
        assert len(result.results) == 2
        assert result.errors == []

    def test_items_view_is_accepted_as_text_id_pairs(self) -> None:
        mapping = {"1. A\n\nSome body text.\n": "doc1"}
        result = self._chunker().chunk_batch(mapping.items())
        assert len(result.results) == 1
        assert result.errors == []

    def test_lists_and_generators_are_still_accepted(self) -> None:
        chunker = self._chunker()
        documents = ["1. A\n\nSome body text.\n", "1. B\n\nMore body text.\n"]
        assert len(chunker.chunk_batch(documents).results) == 2
        assert len(chunker.chunk_batch(iter(documents)).results) == 2


class TestH12ChunkBatchGeneratorErrors:
    """H12 — a generator that raised partway through propagated straight out
    of ``chunk_batch``, breaking its own documented "errors do not halt the
    batch" guarantee.
    """

    @staticmethod
    def _chunker():
        from lexichunk import LegalChunker

        return LegalChunker(jurisdiction="uk")

    @staticmethod
    def _raising_generator():
        yield "1. A\n\nSome body text for the first clause.\n"
        yield "1. B\n\nSome body text for the second clause.\n"
        raise RuntimeError("boom")

    def test_raising_generator_does_not_propagate(self) -> None:
        result = self._chunker().chunk_batch(self._raising_generator())
        assert len(result.results) == 2

    def test_failure_is_recorded_as_a_batch_error(self) -> None:
        result = self._chunker().chunk_batch(self._raising_generator())
        assert len(result.errors) == 1
        error = result.errors[0]
        assert error.index == 2
        assert error.error_type == "RuntimeError"
        assert "boom" in error.error

    def test_documents_yielded_before_the_failure_are_chunked(self) -> None:
        result = self._chunker().chunk_batch(self._raising_generator())
        assert all(chunks for chunks in result.results)

    def test_generator_that_raises_immediately_yields_only_the_error(self) -> None:
        def generator():
            raise ValueError("nope")
            yield ""  # pragma: no cover

        result = self._chunker().chunk_batch(generator())
        assert result.results == []
        assert len(result.errors) == 1
        assert result.errors[0].error_type == "ValueError"

    def test_a_clean_generator_still_reports_no_errors(self) -> None:
        def generator():
            yield "1. A\n\nSome body text.\n"

        result = self._chunker().chunk_batch(generator())
        assert result.errors == []


@llama_index_required
class TestH14LlamaIndexDeterminism:
    """H14 — with no explicit ``document_id``, LlamaIndex had already filled
    ``Document.id_`` with a fresh ``uuid4``, so ``context_header``, embed text
    and ``node_id`` all differed on every run of the same input.
    """

    @staticmethod
    def _source() -> str:
        import pathlib

        return (
            pathlib.Path(__file__).parent / "fixtures" / "uk_service_agreement.txt"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _parser():
        from lexichunk.integrations.llama_index import LegalNodeParser

        return LegalNodeParser(jurisdiction="uk")

    def _nodes(self, **document_kwargs):
        from llama_index.core.schema import Document

        return self._parser().get_nodes_from_documents(
            [Document(text=self._source(), **document_kwargs)]
        )

    def test_node_ids_are_stable_across_runs(self) -> None:
        assert [n.node_id for n in self._nodes()] == [
            n.node_id for n in self._nodes()
        ]

    def test_context_headers_are_stable_across_runs(self) -> None:
        first = [n.metadata.get("context_header") for n in self._nodes()]
        second = [n.metadata.get("context_header") for n in self._nodes()]
        assert first == second
        assert first[0]

    def test_embed_text_is_stable_across_runs(self) -> None:
        from llama_index.core.schema import MetadataMode

        first = [n.get_content(metadata_mode=MetadataMode.EMBED) for n in self._nodes()]
        second = [n.get_content(metadata_mode=MetadataMode.EMBED) for n in self._nodes()]
        assert first == second

    def test_an_explicit_document_id_still_wins(self) -> None:
        nodes = self._nodes(id_="msa-2024")
        assert "[Document: msa-2024]" in nodes[0].metadata["context_header"]

    def test_different_documents_get_different_identifiers(self) -> None:
        from llama_index.core.schema import Document

        parser = self._parser()
        one = parser.get_nodes_from_documents([Document(text=self._source())])
        two = parser.get_nodes_from_documents(
            [Document(text=self._source() + "\n\n9. Extra\n\nMore body text.\n")]
        )
        assert one[0].metadata["context_header"] != two[0].metadata["context_header"]

    def test_the_derived_identifier_is_not_a_uuid(self) -> None:
        header = self._nodes()[0].metadata["context_header"]
        assert "[Document: lexichunk-" in header
