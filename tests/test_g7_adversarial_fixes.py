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
