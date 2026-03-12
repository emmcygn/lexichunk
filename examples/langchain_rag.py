"""langchain_rag.py — LangChain + FAISS retrieval pipeline with lexichunk.

Demonstrates:
  - LegalTextSplitter: splitting a contract into LangChain Document objects
  - Metadata preservation on each Document
  - Loading chunks into a FAISS vector store
  - Contextual Retrieval pattern: prepend context_header to content before
    embedding so every chunk carries its document-level context

Requirements:
    pip install lexichunk[langchain] faiss-cpu openai

The OpenAI embeddings call requires OPENAI_API_KEY to be set.
If you prefer a local embedding model, swap OpenAIEmbeddings for any
LangChain-compatible embeddings class (e.g. HuggingFaceEmbeddings).

Run:
    python examples/langchain_rag.py
"""

# ---------------------------------------------------------------------------
# Inline contract sample
# ---------------------------------------------------------------------------

SAMPLE_CONTRACT = """\
MASTER SERVICES AGREEMENT

This Master Services Agreement ("Agreement") is entered into as of 1 March
2025 between Acme Software Limited ("Service Provider") and GlobalCorp plc
("Client").

1. Definitions

1.1 "Intellectual Property Rights" means all patents, trade marks, design
rights, copyrights, database rights, know-how, and all other intellectual
property rights, whether registered or unregistered, anywhere in the world.

1.2 "Personal Data" means any information relating to an identified or
identifiable natural person as defined in the UK GDPR.

1.3 "Service Levels" means the performance standards set out in Schedule 2.

2. Services

2.1 The Service Provider shall provide the software development services
described in Schedule 1 in accordance with the Service Levels.

2.2 The Service Provider shall ensure that any sub-processors engaged in the
processing of Personal Data have entered into data processing agreements
meeting the requirements of Clause 8.

3. Intellectual Property

3.1 All Intellectual Property Rights in any work product or deliverables
created by the Service Provider under this Agreement shall vest in the Client
upon payment in full of the applicable Fees.

3.2 The Service Provider grants the Client a perpetual, royalty-free licence
to use any pre-existing Intellectual Property Rights incorporated into the
deliverables, to the extent necessary to enjoy the benefit of those
deliverables.

4. Data Protection

4.1 Each party shall comply with its obligations under applicable data
protection legislation, including the UK GDPR and the Data Protection Act 2018.

4.2 The Service Provider shall process Personal Data only on the documented
instructions of the Client, and shall not transfer Personal Data outside the
United Kingdom without the prior written consent of the Client.

5. Limitation of Liability

5.1 Neither party shall be liable to the other for any indirect, special, or
consequential loss or damage, loss of profits, loss of revenue, or loss of
anticipated savings, howsoever arising.

5.2 The aggregate liability of either party to the other under or in connection
with this Agreement shall not exceed the total Fees paid or payable in the
twelve months preceding the event giving rise to the claim.

6. Governing Law

6.1 This Agreement and any dispute or claim arising out of or in connection
with it shall be governed by and construed in accordance with the law of
England and Wales.

6.2 The parties irrevocably submit to the exclusive jurisdiction of the courts
of England and Wales.
"""


def main() -> None:
    print("=" * 70)
    print("lexichunk + LangChain RAG Example")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Import LegalTextSplitter
    # ------------------------------------------------------------------
    try:
        from lexichunk.integrations.langchain import LegalTextSplitter
    except ImportError as exc:
        print(f"\nERROR: {exc}")
        print("Install the LangChain extra with: pip install lexichunk[langchain]")
        return

    # ------------------------------------------------------------------
    # 2. Create the splitter and chunk the contract
    # ------------------------------------------------------------------
    splitter = LegalTextSplitter(
        jurisdiction="uk",
        doc_type="contract",
        max_chunk_size=512,
        min_chunk_size=64,
        include_definitions=True,
        include_context_header=True,
    )

    documents = splitter.split_text(SAMPLE_CONTRACT)
    print(f"\nSplit contract into {len(documents)} Document(s).\n")

    # ------------------------------------------------------------------
    # 3. Inspect metadata preserved on each Document
    # ------------------------------------------------------------------
    print("-" * 70)
    print("Metadata on each LangChain Document")
    print("-" * 70)

    for doc in documents:
        print(f"\n  page_content (preview): {doc.page_content[:80].replace(chr(10), ' ')!r}...")
        print(f"  metadata['clause_type']      : {doc.metadata['clause_type']}")
        print(f"  metadata['hierarchy_path']   : {doc.metadata['hierarchy_path']}")
        print(f"  metadata['document_section'] : {doc.metadata['document_section']}")
        print(f"  metadata['defined_terms_used']: {doc.metadata['defined_terms_used']}")
        print(f"  metadata['context_header']   : {doc.metadata['context_header']!r}")
        if doc.metadata["cross_references"]:
            refs = [r["raw_text"] for r in doc.metadata["cross_references"]]
            print(f"  metadata['cross_references'] : {refs}")

    # ------------------------------------------------------------------
    # 4. Contextual Retrieval pattern
    #
    # The standard RAG approach embeds doc.page_content directly. This
    # loses the document-level context for each chunk — a limitation
    # identified by Anthropic's Contextual Retrieval research, which showed
    # a 35% reduction in retrieval failures when chunk-specific context is
    # prepended before embedding.
    #
    # lexichunk generates a context_header for every chunk:
    #
    #   "[Document: MSA] [Section: 5 > 5.1] [Type: Limitation of Liability]
    #    [Jurisdiction: UK]"
    #
    # Prepend this to page_content before passing to the embeddings model
    # so the vector representation captures both position and content.
    # ------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("Contextual Retrieval: texts prepared for embedding")
    print("-" * 70)
    print(
        "\nPattern: embed (context_header + '\\n\\n' + page_content) "
        "but store only page_content in the vector store."
    )
    print(
        "This way the embedding carries full context while retrieval "
        "returns clean chunk text.\n"
    )

    texts_to_embed = [
        doc.metadata["context_header"] + "\n\n" + doc.page_content
        for doc in documents
    ]

    for i, text in enumerate(texts_to_embed[:2]):
        preview = text[:200].replace("\n", " ")
        print(f"  Embedding text [{i}]: {preview!r}...\n")

    # ------------------------------------------------------------------
    # 5. Load into FAISS vector store (requires faiss-cpu + openai)
    # ------------------------------------------------------------------
    print("-" * 70)
    print("FAISS Vector Store (requires faiss-cpu and openai)")
    print("-" * 70)

    try:
        from langchain_community.vectorstores import FAISS  # type: ignore
        from langchain_openai import OpenAIEmbeddings       # type: ignore
        import os

        if not os.getenv("OPENAI_API_KEY"):
            print("\n  Skipping FAISS indexing: OPENAI_API_KEY not set.")
            print("  Set the environment variable and re-run to build the index.")
            return

        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

        # Use the contextually-enriched texts for embedding but store the
        # original documents so retrieval returns clean page_content.
        vector_store = FAISS.from_texts(
            texts=texts_to_embed,
            embedding=embeddings,
            metadatas=[doc.metadata for doc in documents],
        )

        print(f"\n  Indexed {len(documents)} chunk(s) into FAISS.")

        # Example query
        query = "What are the limitations on liability?"
        results = vector_store.similarity_search(query, k=3)

        print(f"\n  Query: {query!r}")
        print(f"  Top {len(results)} result(s):\n")
        for rank, result in enumerate(results, 1):
            print(f"    [{rank}] clause_type={result.metadata['clause_type']!r}")
            print(f"         hierarchy_path={result.metadata['hierarchy_path']!r}")
            preview = result.page_content[:120].replace("\n", " ")
            print(f"         content: {preview!r}...")
            print()

    except ImportError:
        print(
            "\n  FAISS or OpenAI not installed. To run this section:\n"
            "      pip install faiss-cpu langchain-community langchain-openai openai"
        )


if __name__ == "__main__":
    main()
