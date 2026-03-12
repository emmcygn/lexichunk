"""basic_usage.py — lexichunk core API walkthrough.

Demonstrates:
  - Creating a LegalChunker for a UK contract
  - Chunking an inline contract snippet (no file loading required)
  - Inspecting all LegalChunk fields
  - Using get_defined_terms() to extract the definitions map
  - Using parse_structure() to inspect the hierarchy before chunking

Run:
    pip install lexichunk
    python examples/basic_usage.py
"""

from lexichunk import LegalChunker

# ---------------------------------------------------------------------------
# Inline UK contract sample
# ---------------------------------------------------------------------------
# A short but structurally complete UK service agreement excerpt.
# It contains: a definitions clause, a services clause with a cross-reference,
# a payment clause referencing a defined term, and a confidentiality clause.

SAMPLE_CONTRACT = """\
SERVICE AGREEMENT

This Service Agreement is entered into as of 1 January 2025 between Acme
Limited, a company incorporated in England and Wales ("Service Provider"),
and Beta Corp Limited ("Client").

1. Definitions

1.1 "Confidential Information" means any information disclosed by one party
to the other, whether orally or in writing, that is designated as confidential
or that reasonably should be understood to be confidential given the nature of
the information and the circumstances of disclosure.

1.2 "Services" means the software development and consultancy services
described in Schedule 1 to this Agreement.

1.3 "Fees" means the amounts payable by the Client to the Service Provider as
set out in Clause 4 of this Agreement.

2. Services

2.1 The Service Provider shall perform the Services with reasonable skill and
care in accordance with the specifications set out in Schedule 1.

2.2 The Service Provider may engage sub-contractors to assist in the delivery
of the Services, subject to the prior written consent of the Client as set out
in Clause 6.

3. Term

3.1 This Agreement shall commence on the Commencement Date and shall continue
for a period of twelve (12) months, unless terminated earlier in accordance
with Clause 7.

4. Fees and Payment

4.1 The Client shall pay the Fees to the Service Provider within thirty (30)
days of receipt of an invoice. All invoices shall be issued monthly in arrears.

4.2 In the event that any invoice remains unpaid after the due date, the
Service Provider shall be entitled to charge interest on the outstanding amount
at the rate of 8% per annum above the Bank of England base rate.

5. Confidentiality

5.1 Each party shall keep the other party's Confidential Information strictly
confidential and shall not disclose it to any third party without the prior
written consent of the disclosing party.

5.2 The obligations in Clause 5.1 shall not apply to information that is or
becomes publicly available through no breach of this Agreement, or that the
receiving party can demonstrate was already in its possession prior to
disclosure.
"""

# ---------------------------------------------------------------------------
# Main demonstration
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("lexichunk — Basic Usage Example")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Create a LegalChunker for a UK contract
    # ------------------------------------------------------------------
    chunker = LegalChunker(
        jurisdiction="uk",           # Apply UK clause-numbering patterns
        doc_type="contract",         # Document type hint
        max_chunk_size=512,          # Max ~512 tokens per chunk
        min_chunk_size=64,           # Merge clauses smaller than ~64 tokens
        include_definitions=True,    # Attach relevant definitions to each chunk
        include_context_header=True, # Generate Contextual Retrieval headers
        document_id="service-agreement-2025-01",  # Propagated to all chunks
    )

    # ------------------------------------------------------------------
    # 2. Chunk the inline contract sample
    # ------------------------------------------------------------------
    chunks = chunker.chunk(SAMPLE_CONTRACT)

    print(f"\nDocument produced {len(chunks)} chunk(s).\n")

    # ------------------------------------------------------------------
    # 3. Inspect each chunk field
    # ------------------------------------------------------------------
    for chunk in chunks:
        print("-" * 70)
        print(f"[Chunk {chunk.index}]")
        print()

        # Content
        preview = chunk.content[:160].replace("\n", " ")
        if len(chunk.content) > 160:
            preview += "..."
        print(f"  content          : {preview!r}")

        # Hierarchy
        print(f"  hierarchy_path   : {chunk.hierarchy_path!r}")
        print(f"  hierarchy.level  : {chunk.hierarchy.level}")
        print(f"  hierarchy.id     : {chunk.hierarchy.identifier!r}")
        if chunk.hierarchy.title:
            print(f"  hierarchy.title  : {chunk.hierarchy.title!r}")

        # Classification
        print(f"  clause_type      : {chunk.clause_type}")
        print(f"  document_section : {chunk.document_section}")
        print(f"  jurisdiction     : {chunk.jurisdiction}")

        # Cross-references
        if chunk.cross_references:
            refs = [r.raw_text for r in chunk.cross_references]
            print(f"  cross_references : {refs}")
        else:
            print(f"  cross_references : (none detected)")

        # Defined terms
        if chunk.defined_terms_used:
            print(f"  defined_terms_used     : {chunk.defined_terms_used}")
            for term in chunk.defined_terms_used:
                defn = chunk.defined_terms_context.get(term, "")
                short = defn[:80].replace("\n", " ")
                if len(defn) > 80:
                    short += "..."
                print(f"    '{term}' => {short!r}")
        else:
            print(f"  defined_terms_used     : (none)")

        # Context header (Contextual Retrieval)
        print(f"  context_header   : {chunk.context_header!r}")

        # Character offsets
        print(f"  char range       : [{chunk.char_start}, {chunk.char_end})")
        print(f"  document_id      : {chunk.document_id!r}")
        print()

    # ------------------------------------------------------------------
    # 4. get_defined_terms() — extract full definitions map without chunking
    # ------------------------------------------------------------------
    print("=" * 70)
    print("get_defined_terms()")
    print("=" * 70)

    terms = chunker.get_defined_terms(SAMPLE_CONTRACT)

    if terms:
        for name, dt in terms.items():
            short_def = dt.definition[:100].replace("\n", " ")
            if len(dt.definition) > 100:
                short_def += "..."
            print(f"  Term         : {dt.term!r}")
            print(f"  Source clause: {dt.source_clause!r}")
            print(f"  Definition   : {short_def!r}")
            print()
    else:
        print("  (no defined terms found — try a document with a Definitions clause)")

    # ------------------------------------------------------------------
    # 5. parse_structure() — inspect the hierarchy before chunking
    # ------------------------------------------------------------------
    print("=" * 70)
    print("parse_structure()")
    print("=" * 70)

    nodes = chunker.parse_structure(SAMPLE_CONTRACT)

    if nodes:
        print(f"  Found {len(nodes)} hierarchy node(s):\n")
        for node in nodes:
            indent = "  " + ("    " * node.level)
            title_part = f" — {node.title}" if node.title else ""
            parent_part = f" (parent: {node.parent})" if node.parent else ""
            print(f"{indent}[L{node.level}] {node.identifier}{title_part}{parent_part}")
    else:
        print("  (no structure nodes detected)")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
