"""Demonstrate narrow lexical clause selection with offline source evidence.

This synthetic example is not a general legal retriever or relevance model.

Run after an editable source install:
    python -m pip install -e .
    python examples/offline_evidence_retrieval.py
"""

from __future__ import annotations

import json
import re
from typing import Any

from lexichunk import DocumentSection, LegalChunker

CONTRACT = """\
SERVICE AGREEMENT

1. Definitions

1.1 "Confidential Information" means non-public commercial or technical information disclosed by a party.

2. Confidentiality

2.1 The Recipient shall protect Confidential Information and shall use it only to perform this Agreement.

3. Return of Information

3.1 On termination, the Recipient shall return or destroy Confidential Information, subject to Clause 2.1.
"""


def retrieve_evidence(query: str) -> dict[str, Any]:
    chunker = LegalChunker(
        jurisdiction="uk",
        doc_type="contract",
        include_definitions=True,
        document_id="offline-service-agreement",
    )
    source = chunker.sanitize(CONTRACT)
    chunks = chunker.chunk(CONTRACT)
    query_terms = set(re.findall(r"[a-z]+", query.lower()))

    def score(chunk: Any) -> tuple[int, int]:
        content_terms = set(re.findall(r"[a-z]+", chunk.content.lower()))
        return len(query_terms & content_terms), -chunk.index

    clause = max(chunks, key=score)
    definitions = chunker.get_defined_terms(CONTRACT)
    definition_evidence = []

    for term in clause.defined_terms_used:
        definition = definitions.get(term)
        if definition is None:
            continue
        source_chunk = next(
            (
                chunk
                for chunk in chunks
                if chunk.hierarchy.identifier == definition.source_clause
                and chunk.document_section == DocumentSection.DEFINITIONS
            ),
            None,
        )
        definition_evidence.append(
            {
                "term": term,
                "definition": definition.definition,
                "source_clause": definition.source_clause,
                "source_offsets": (
                    [source_chunk.char_start, source_chunk.char_end]
                    if source_chunk is not None
                    else None
                ),
                "source_text": (
                    source[source_chunk.char_start : source_chunk.char_end]
                    if source_chunk is not None
                    else None
                ),
            }
        )

    return {
        "query": query,
        "document_id": clause.document_id,
        "clause": {
            "hierarchy_path": clause.hierarchy_path,
            "source_offsets": [clause.char_start, clause.char_end],
            "source_text": source[clause.char_start : clause.char_end],
        },
        "definitions": definition_evidence,
        "cross_references": [reference.to_dict() for reference in clause.cross_references],
        "provenance": "Offsets index LegalChunker.sanitize(CONTRACT).",
    }


def main() -> None:
    evidence = retrieve_evidence("How may the Recipient use Confidential Information?")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
