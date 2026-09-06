# Adoption guide: evaluate the fit before shipping

## The useful, narrow job

lexichunk is a local, rule-based preprocessing component for teams that already
have legal documents as text and want clause-aware chunks, hierarchy, definition
context, and reference metadata. A practical first workflow is a contract-search
screen that shows the retrieved provision, its contract-specific definition, and
the underlying source text for an employee to inspect.

It is not a legal adviser, a complete search product, a document-management
system, or a PDF/OCR engine. It does not establish whether a provision is
enforceable, identify the controlling version of an agreement, enforce access
permissions, or guarantee that a downstream model answers correctly. Clause
classification is heuristic, not a legal conclusion or calibrated probability.

The public beta is suitable for engineering evaluation. Automated tests and
synthetic examples are not evidence of lawyer validation, customer adoption,
or production accuracy across a jurisdiction.

## Start with an inspectable example

After the source installation in the [README](../README.md), run:

```bash
python examples/offline_evidence_retrieval.py
```

The example uses synthetic text and simple lexical retrieval. Inspect the
selected clause, attached definition, and source spans rather than treating a
successful run as an end-to-end legal QA benchmark. It needs no model credentials
and is not intended to be a production ranker.

For an application, retain an immutable source document and record:

- Document identity, version, jurisdiction profile, and extraction settings.
- The exact sanitized text and its hash, package commit, and chunker settings.
- Each chunk's own source span separately from added headers and definition text.
- Any unresolved references and fallback use for review or application routing.

Offsets index `LegalChunker.sanitize(text)`, not PDF coordinates, byte positions,
or necessarily the original input string. A chunk's `content` can include
ancestor headers; its own source span does not necessarily cover that added
context. Preserve a separate extraction/source map if users need PDF highlights.
Filter document versions and permissions before retrieval. A `document_id`
metadata field is not an access-control mechanism.

## Compare against credible alternatives

This is a capability comparison, not a measured performance ranking. Sources
were checked on 6 September 2026; record dependency versions in your experiment.

| Option | What its own documentation supports | How to use it in the decision |
| --- | --- | --- |
| LangChain recursive character splitter | Splits using a configurable sequence of separators. [Reference](https://reference.langchain.com/python/langchain-text-splitters/character/RecursiveCharacterTextSplitter) | A simple baseline with low integration effort. Do not assume legal metadata must improve retrieval over it. |
| Unstructured | Partitions documents into elements; title-based chunking can preserve section boundaries and handles tables separately. [Documentation](https://docs.unstructured.io/open-source/core-functionality/chunking) | Compare when layout, formats, or tables matter. Structure-aware chunking is not unique to lexichunk. |
| Docling | Provides document-based hierarchical chunking and tokenizer-aware hybrid splitting/merging, with contextualized serialization. [Documentation](https://docling-project.github.io/docling/concepts/chunking/) | Compare for layout-aware ingestion and real tokenizer budgets; it may also provide upstream text extraction. |
| lexichunk | Legal numbering profiles, definition context, reference metadata, local execution, and a dependency-free core. | Test whether these legal-specific signals solve failures in your documents at acceptable integration and maintenance cost. |

Our proposed differentiator is inspectable legal-specific structure with a small
local core, **not** universal superiority over generic or document-aware chunkers.
If your main failure is OCR, table reconstruction, access control, or semantic
ranking, fix that stage first rather than expecting a different chunker to solve
it. If a simpler baseline meets your requirements, prefer the simpler system.

## Evaluate without circular ground truth

Use the separate [legal-rag-eval](https://github.com/emmcygn/legal-rag-eval)
harness for source-evidence experiments. SDK parser tests and evaluator labels
serve different purposes: never generate the expected evidence by running the
chunker you are evaluating.

For broader evaluation, [LegalBench-RAG](https://github.com/ZeroEntropy-AI/legalbenchrag)
is an external retrieval benchmark with character-range evidence. Its maintainers
describe dataset generation using LLMs and require checking the source datasets'
usage policies. Treat it as a candidate external evaluation source, not as a
pre-integrated or independently human-validated result for this project.

Before making a quality claim:

1. Select documents you have permission to use and a real employee workflow.
   Separate documents and near-duplicate templates across development and holdout
   sets; do not call a fixture a holdout after tuning on it.
2. Have qualified reviewers identify exact answer evidence, necessary definitions,
   exceptions, and referenced provisions without seeing a chunker's output.
   Record disagreements, adjudication, and unanswerable questions.
3. Freeze labels, source hashes, and a tuning budget. Use the same ranker,
   retrieval depth, and final context budget for each strategy. Charge added
   headers, overlaps, definitions, and reference expansion to that budget.
4. Report answerable evidence coverage and precision separately from unanswerable
   behavior. Slice failures by document type, numbering style, repeated clauses,
   cross-document distractors, and extraction quality. Show losses as well as wins.
5. Measure downstream citation correctness, omitted exceptions, and unsupported
   answers separately. Retrieval coverage alone does not establish answer accuracy.
6. Report indexing time, latency distribution, memory, context size, operating
   cost, and reviewer time saved on representative document lengths. Predeclare
   acceptance thresholds with the team rather than choosing them after results.

The bundled offline lexical benchmark is a reproducible regression and comparison
tool. It is not a semantic retrieval benchmark, a production cost measurement,
or evidence of legal correctness. Its source-only mode does not measure the value
of definition or cross-reference expansion.

## Production decision gates

Proceed beyond a pilot only when the owning team accepts documented failure
rates on independently reviewed documents, can trace citations back to immutable
sources, handles missing evidence conservatively, and has tested privacy and
version controls in the surrounding application. Define rollback behavior and
rerun the frozen evaluation when extraction, dependencies, chunking, ranking, or
generation changes.

Those are adoption requirements, not checks that this repository claims to have
completed for your organization. A shareable beta should make these limits easy
to discover rather than hide them behind a single benchmark percentage.
