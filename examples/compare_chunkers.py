"""compare_chunkers.py — lexichunk vs RecursiveCharacterTextSplitter.

Demonstrates the five failure modes of naive chunking on legal text, then
shows a side-by-side comparison of naive vs lexichunk output on the same
contract excerpt.

Failure modes shown:
  1. Clause fragmentation  — liability clause split from its proviso
  2. Orphaned cross-refs   — "subject to Clause 8.2" with no context
  3. Lost defined terms    — "Material Adverse Effect" without definition
  4. Destroyed hierarchy   — sub-clause becomes floating fragment
  5. Cross-doc contamination — no document-level metadata on chunks

Requirements:
    pip install lexichunk
    pip install langchain-text-splitters    # optional, for naive splitter demo

Run:
    python examples/compare_chunkers.py
"""

# ---------------------------------------------------------------------------
# Contract excerpt — used for the side-by-side comparison
# ---------------------------------------------------------------------------

CONTRACT_EXCERPT = """\
SERVICE AGREEMENT

This Service Agreement ("Agreement") is entered into between TechVentures
Limited ("Service Provider") and Enterprise Solutions plc ("Client").

1. Definitions

1.1 "Material Adverse Effect" means any event, circumstance, change, or effect
that, individually or in the aggregate, has had, or would reasonably be
expected to have, a material adverse effect on the business, assets,
operations, financial condition, or results of operations of the relevant
party, excluding any effect arising from: (a) general economic or market
conditions; (b) changes in applicable law or regulation; or (c) acts of God,
terrorism, or natural disasters.

1.2 "Losses" means all losses, liabilities, damages, costs, expenses
(including reasonable legal fees), and claims of whatsoever nature.

1.3 "Confidential Information" means any information disclosed by one party to
the other that is designated as confidential or that reasonably should be
understood to be confidential, but excluding information that is publicly
available or already known to the receiving party.

2. Services

2.1 The Service Provider shall provide the services described in Schedule 1,
subject to the restrictions set out in Clause 8.2 regarding prohibited use
cases and export control requirements.

2.2 Service levels are as set out in Schedule 2 to this Agreement.

3. Limitation of Liability

3.1 Neither party shall be liable to the other for any indirect, consequential,
special, incidental, or punitive loss or damage, including loss of profit,
revenue, business, data, or goodwill, howsoever arising, whether in contract,
tort, or otherwise.

3.2 The aggregate liability of each party to the other under this Agreement
shall in no event exceed the total Fees paid or payable in the twelve-month
period immediately preceding the event giving rise to the claim.

3.3 Nothing in this Agreement shall limit or exclude either party's liability
for: (a) death or personal injury caused by negligence; (b) fraud or fraudulent
misrepresentation; or (c) any other liability that cannot be limited or
excluded by applicable law.

4. Indemnification

4.1 The Service Provider shall indemnify, defend, and hold harmless the Client
and its officers, directors, and employees from and against any and all Losses
arising out of or in connection with: (a) any Material Adverse Effect caused
by a material breach of this Agreement by the Service Provider; or (b) any
infringement of a third party's intellectual property rights by the Services.

5. Governing Law

5.1 This Agreement shall be governed by and construed in accordance with the
laws of England and Wales. Any dispute arising in connection with this
Agreement shall be referred to arbitration in accordance with the rules of the
London Court of International Arbitration.
"""

# ---------------------------------------------------------------------------
# Targeted failure-mode excerpts — short snippets to isolate each failure
# ---------------------------------------------------------------------------

# Failure mode 1: Clause fragmentation
FRAGMENTATION_TEXT = (
    "3.1 Neither party shall be liable to the other for any indirect, "
    "consequential, special, incidental, or punitive loss or damage, including "
    "loss of profit, revenue, business, data, or goodwill, howsoever arising, "
    "whether in contract, tort, or otherwise.\n"
    "3.2 The aggregate liability of each party to the other under this "
    "Agreement shall in no event exceed the total Fees paid or payable in the "
    "twelve-month period immediately preceding the event giving rise to the "
    "claim.\n"
    "3.3 Nothing in this Agreement shall limit or exclude either party's "
    "liability for: (a) death or personal injury caused by negligence; "
    "(b) fraud or fraudulent misrepresentation; or (c) any other liability "
    "that cannot be limited or excluded by applicable law."
)

# Failure mode 2: Orphaned cross-references
CROSSREF_TEXT = (
    "2.1 The Service Provider shall provide the services described in "
    "Schedule 1, subject to the restrictions set out in Clause 8.2 regarding "
    "prohibited use cases and export control requirements."
)

# Failure mode 3: Lost defined terms
DEFINED_TERMS_TEXT = (
    "1.1 \"Material Adverse Effect\" means any event, circumstance, change, or "
    "effect that, individually or in the aggregate, has had, or would "
    "reasonably be expected to have, a material adverse effect on the business, "
    "assets, operations, financial condition, or results of operations of the "
    "relevant party.\n\n"
    "4.1 The Service Provider shall indemnify the Client against any and all "
    "Losses arising out of any Material Adverse Effect caused by a material "
    "breach of this Agreement by the Service Provider."
)

# Failure mode 4: Destroyed hierarchy
HIERARCHY_TEXT = (
    "3.3 Nothing in this Agreement shall limit or exclude either party's "
    "liability for: (a) death or personal injury caused by negligence; "
    "(b) fraud or fraudulent misrepresentation; or (c) any other liability "
    "that cannot be limited or excluded by applicable law."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def section_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def subsection(title: str) -> None:
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


# ---------------------------------------------------------------------------
# Failure mode demonstrations
# ---------------------------------------------------------------------------


def demo_failure_modes() -> None:
    section_header("PART 1: The 5 Failure Modes of Naive Chunking")

    # ---- Failure 1: Clause fragmentation --------------------------------
    subsection("Failure Mode 1: Clause Fragmentation")
    print(
        "A fixed-size window can split a limitation of liability clause (3.1)\n"
        "from its critical carve-out (3.3). A retrieval query about liability\n"
        "limits may return only 3.1, omitting the fraud/negligence exceptions.\n"
    )
    # Simulate a naive 200-character split
    chunk_size = 200
    naive_chunks = [
        FRAGMENTATION_TEXT[i : i + chunk_size]
        for i in range(0, len(FRAGMENTATION_TEXT), chunk_size)
    ]
    print(f"  Naive split ({chunk_size} chars) produces {len(naive_chunks)} chunk(s):")
    for i, c in enumerate(naive_chunks):
        print(f"    [{i}] {c[:80].replace(chr(10), ' ')!r}...")
    print(
        "\n  Problem: chunk [0] contains the exclusion rule; chunk [1] contains\n"
        "  the carve-outs. They will rarely be retrieved together."
    )

    # ---- Failure 2: Orphaned cross-references ---------------------------
    subsection("Failure Mode 2: Orphaned Cross-References")
    print(
        "This chunk references 'Clause 8.2' but contains no information about\n"
        "what Clause 8.2 says. A naive chunker has no mechanism to resolve or\n"
        "attach the referenced content.\n"
    )
    print(f"  Chunk text:\n    {CROSSREF_TEXT!r}")
    print(
        "\n  The retriever cannot follow 'Clause 8.2'. The LLM will answer\n"
        "  without the relevant restrictions."
    )

    # ---- Failure 3: Lost defined terms ----------------------------------
    subsection("Failure Mode 3: Lost Defined Terms")
    print(
        "The definition of 'Material Adverse Effect' is in clause 1.1.\n"
        "The indemnification clause (4.1) uses it. A naive chunker produces\n"
        "separate chunks — 4.1 never sees the 200-word negotiated definition.\n"
    )
    # Show the two chunks a naive splitter would produce
    print("  Naive chunks:")
    print(f"    [Definitions chunk] {DEFINED_TERMS_TEXT[:160].replace(chr(10), ' ')!r}...")
    print(f"    [Indemnification chunk] ...Losses arising out of any Material Adverse Effect...")
    print(
        "\n  The LLM uses its pre-training sense of 'material adverse effect'\n"
        "  rather than the contract-specific definition — a silent hallucination."
    )

    # ---- Failure 4: Destroyed hierarchy ---------------------------------
    subsection("Failure Mode 4: Destroyed Hierarchy")
    print(
        "Sub-clauses (a), (b), (c) under clause 3.3 become floating fragments\n"
        "when split naively. There is no indication they are carve-outs inside\n"
        "the Limitation of Liability section.\n"
    )
    # Simulate splitting at sub-clause level naively
    naive_sub_chunks = [line.strip() for line in HIERARCHY_TEXT.split(";") if line.strip()]
    print(f"  Naive sub-clause split produces {len(naive_sub_chunks)} fragment(s):")
    for i, c in enumerate(naive_sub_chunks):
        print(f"    [{i}] {c[:100]!r}")
    print(
        "\n  Fragment [1] — '(b) fraud or fraudulent misrepresentation' — is\n"
        "  meaningless without knowing it qualifies clause 3.3 of the\n"
        "  Limitation of Liability section."
    )

    # ---- Failure 5: Cross-document contamination ------------------------
    subsection("Failure Mode 5: Cross-Document Contamination")
    print(
        "Without document-level metadata on every chunk, vector retrieval\n"
        "cannot distinguish between identically-worded boilerplate clauses\n"
        "from different contracts.\n"
    )
    boilerplate = (
        "This Agreement shall be governed by and construed in accordance with "
        "the laws of England and Wales."
    )
    print(f"  This governing-law text appears verbatim in thousands of UK contracts:")
    print(f"    {boilerplate!r}")
    print(
        "\n  A naive chunk carries no document identifier. At query time the\n"
        "  retriever pulls governing-law clauses from whichever contract is\n"
        "  nearest in embedding space — often the wrong one."
    )


# ---------------------------------------------------------------------------
# Side-by-side comparison
# ---------------------------------------------------------------------------


def demo_side_by_side() -> None:
    section_header("PART 2: Side-by-Side — Naive vs lexichunk")

    # ---- Naive chunker --------------------------------------------------
    subsection("Naive: RecursiveCharacterTextSplitter (chunk_size=300, overlap=0)")

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore

        naive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=300,
            chunk_overlap=0,
        )
        naive_chunks = naive_splitter.split_text(CONTRACT_EXCERPT)

        print(f"\n  Produced {len(naive_chunks)} chunk(s). First 4 shown:\n")
        for i, c in enumerate(naive_chunks[:4]):
            print(f"  [{i}] ({len(c)} chars)")
            print(f"       {c[:120].replace(chr(10), ' ')!r}...")
            print()

        # Check for boundary violations
        print("  Boundary analysis:")
        violations = 0
        for i, c in enumerate(naive_chunks):
            # A clause boundary violation: chunk starts mid-sentence (no
            # leading clause number or section heading)
            import re
            has_boundary = bool(re.match(r"^\s*(\d+\.|\([a-z]\)|[A-Z]{2,})", c))
            if not has_boundary and i > 0:
                violations += 1
                print(f"    [!] Chunk [{i}] starts mid-text (no clause boundary): "
                      f"{c[:60].replace(chr(10), ' ')!r}...")
        if violations == 0:
            print("    (no obvious boundary violations — try smaller chunk_size)")

        # Check for missing defined terms
        print("\n  Defined terms analysis:")
        has_mae_def = any("Material Adverse Effect\" means" in c for c in naive_chunks)
        has_mae_use = any(
            "Material Adverse Effect" in c and "means" not in c for c in naive_chunks
        )
        if has_mae_use and not any(
            "Material Adverse Effect\" means" in c and "Material Adverse Effect caused" in c
            for c in naive_chunks
        ):
            print(
                "    [!] 'Material Adverse Effect' appears in an indemnification chunk\n"
                "        without its definition — the definition is in a separate chunk."
            )
        else:
            print("    (definition and usage may be in the same chunk at this chunk_size)")

    except ImportError:
        print(
            "\n  langchain-text-splitters not installed. Showing simulated output instead.\n"
            "  Install with: pip install langchain-text-splitters\n"
        )
        print("  Simulated naive chunks (300-char fixed splits):\n")
        chunk_size = 300
        simulated = [
            CONTRACT_EXCERPT[i : i + chunk_size]
            for i in range(0, min(len(CONTRACT_EXCERPT), chunk_size * 4), chunk_size)
        ]
        for i, c in enumerate(simulated):
            print(f"  [{i}] ({len(c)} chars)")
            print(f"       {c[:120].replace(chr(10), ' ')!r}...")
            print()
        print(
            "  Note: fixed-size splits have no awareness of clause boundaries.\n"
            "  Chunk [1] above likely starts mid-sentence inside a definition."
        )

    # ---- lexichunk ------------------------------------------------------
    subsection("lexichunk: LegalChunker(jurisdiction='uk', max_chunk_size=512)")

    from lexichunk import LegalChunker

    chunker = LegalChunker(
        jurisdiction="uk",
        doc_type="contract",
        max_chunk_size=512,
        min_chunk_size=64,
        include_definitions=True,
        include_context_header=True,
        document_id="service-agreement-techventures",
    )

    chunks = chunker.chunk(CONTRACT_EXCERPT)

    print(f"\n  Produced {len(chunks)} chunk(s):\n")

    for chunk in chunks:
        print(f"  [Chunk {chunk.index}] {chunk.clause_type.value.upper()}")
        print(f"    hierarchy_path   : {chunk.hierarchy_path!r}")
        print(f"    document_section : {chunk.document_section.value}")
        preview = chunk.content[:120].replace("\n", " ")
        print(f"    content          : {preview!r}...")

        if chunk.cross_references:
            refs = [r.raw_text for r in chunk.cross_references]
            print(f"    cross_references : {refs}")

        if chunk.defined_terms_used:
            print(f"    defined_terms    : {chunk.defined_terms_used}")
            for term in chunk.defined_terms_used[:1]:
                defn = chunk.defined_terms_context.get(term, "")
                short = defn[:80].replace("\n", " ")
                print(f"      '{term}' => {short!r}{'...' if len(defn) > 80 else ''}")

        print(f"    document_id      : {chunk.document_id!r}")
        print()

    # ---- Summary --------------------------------------------------------
    subsection("Comparison Summary")

    print(
        "\n  NAIVE CHUNKER                     | LEXICHUNK\n"
        "  ----------------------------------|-----------------------------------\n"
        "  Fixed character/token window      | Splits at clause boundaries only\n"
        "  No clause boundary awareness      | Hierarchy path on every chunk\n"
        "  No defined terms                  | Definitions attached to each chunk\n"
        "  No cross-reference tracking       | Cross-references detected & resolved\n"
        "  No clause type classification     | 24 clause types classified\n"
        "  No document-level metadata        | document_id on every chunk\n"
        "  No context for embedding          | context_header for Contextual Retrieval\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("lexichunk vs Naive Chunking — Comparison Script")
    print("=" * 70)

    demo_failure_modes()
    demo_side_by_side()

    print("\n" + "=" * 70)
    print("Done.")
    print("=" * 70)


if __name__ == "__main__":
    main()
