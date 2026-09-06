# Ingestion: after Docling, not instead of Docling

lexichunk does not parse PDFs, and it should not. Turning a scanned or
born-digital PDF into ordered text — finding the columns, the reading order,
the tables, the running headers — is a hard problem with excellent solutions
already: [Docling](https://github.com/docling-project/docling),
[`unstructured`](https://github.com/Unstructured-IO/unstructured), and half a
dozen converters that legaltech teams have already built internally.

What those tools do not do is *legal* structure. They will not tell you that
`5.2` is a subsection of `5`, that `SCHEDULE 1` is a container rather than
clause 8, that `"Services"` was defined in clause 1 and used in clause 7, or
that a chunk must never straddle two top-level clauses. That is lexichunk's
half.

The mistake is to make lexichunk re-derive structure that the converter
already found. A PDF's layout says where the headings are; flattening it to
text throws that away, and then line-based detection guesses at it. If you
have the structure, hand it over:

```python
from docling.document_converter import DocumentConverter
from lexichunk import LegalChunker
from lexichunk.ingestion import from_docling

result = DocumentConverter().convert("msa.pdf")
sections = from_docling(result.document, jurisdiction="uk")
chunks = LegalChunker(jurisdiction="uk").chunk_documents(sections)
```

`chunk_documents()` runs the whole pipeline *except* heading detection —
chunking, cross-reference detection, clause-type classification, context
headers, defined terms, resolution. Everything `chunk()` guarantees still
holds: chunk bodies are exact slices, spans tile without overlap,
`max_chunk_size` is a hard cap, no chunk spans two top-level clauses.

`examples/docling_pipeline.py` is a runnable version of the above that builds
its `DoclingDocument` by hand, so it needs no models and no PDF.

## Install

```bash
pip install 'lexichunk[docling]'   # docling-core only — enough to read a DoclingDocument
```

lexichunk still has **zero mandatory dependencies**. `import lexichunk.ingestion`
never imports `docling_core` or `unstructured`; `from_docling()` raises an
`ImportError` naming the fix if `docling-core` is genuinely needed and missing,
and `from_unstructured()` imports nothing at all — it is duck-typed on
`.category` / `.text` / `.metadata`, so it works with any version and with your
own stand-in objects.

To produce a `DoclingDocument` from a real PDF you also need the full `docling`
package (`pip install docling`), which lexichunk never imports.

## The `Section` model

Every adapter produces `lexichunk.Section` records:

```python
from lexichunk import Section

Section(
    identifier="5.2",          # the label; or the heading text if unnumbered
    title="Payment Terms",     # heading text after the identifier, or None
    text="The Customer shall pay each invoice within thirty days.",
    level=1,                   # -1 Schedule, 0 clause, 1 subsection, ...
    parent_identifier=None,    # optional; inferred from level when omitted
    char_start=1204,           # optional: where this section sat in your source
    char_end=1310,
)
```

Two things are worth being precise about.

**`text` is the body, not the heading.** The heading lives in
`identifier`/`title`, exactly as an upstream parser reports it (a Docling
`SectionHeaderItem` and the `TextItem`s beneath it). `chunk_documents()`
reconstructs a document by emitting a header line from `identifier`/`title`
followed by `text`, so putting the heading in `text` as well duplicates it.

**`char_start`/`char_end` are your source's offsets, and they are worth
supplying.** When every section carries both, `chunk_documents()` populates
`raw_char_start`/`raw_char_end` on each chunk, so you can point a chunk back at
the file it came from. Without them the fields stay at their `-1` sentinel and
only `char_start`/`char_end` — which index the *reconstructed* text — are
available.

Body offsets must describe the original `Section.text` before sanitisation.
The SDK maps normalised body positions back through CRLF and Unicode changes.
For a heading-only section, offsets describe its original heading; a generated
heading chunk covers that source range rather than an empty span. A boundary
inside a multi-output Unicode normalisation run covers the whole original
run, so neighboring raw spans can overlap. These are source-highlighting
ranges, not a guarantee that concatenating raw slices reproduces chunk text.
The low-level `build_document()` helper omits the source-span index when a
custom sanitiser produces body text different from the built-in sanitiser;
it does not guess source offsets for arbitrary transformations.

## Levels come from the numbering

This is the part that makes the adapters worth using rather than writing
yourself.

A converter reports a heading's *depth*. Docling gives you
`SectionHeaderItem.level`; `unstructured` gives you `metadata.category_depth`;
markdown gives you the `#` count. None of them knows that a schedule is a
container. In a real agreement, `1. Definitions` and `SCHEDULE 1 - CHARGES` are
routinely both "heading level 1", which is true about the *layout* and wrong
about the *document*.

So the adapters run the jurisdiction's own `detect_level` over the heading
text. Where the heading starts with legal numbering, its level and identifier
come from those rules and the remainder becomes the title:

| Heading | Reported depth | lexichunk level | identifier | title |
| --- | --- | --- | --- | --- |
| `1. Definitions` | 1 | `0` | `1` | `Definitions` |
| `5.2 Payment Terms` | 1 | `1` | `5.2` | `Payment Terms` |
| `SCHEDULE 1 - FEES` | 1 | `-1` | `SCHEDULE 1` | `FEES` |
| `Exhibit A` | 1 | `-2` | `Exhibit A` | — |
| `Article IV — Indemnification` | 1 | `0` | `Article IV` | `Indemnification` |
| `CONFIDENTIALITY` | 2 | `1` | `CONFIDENTIALITY` | — |

The last row is the fallback: a heading with no numbering has nothing the
jurisdiction rules can add, so the converter's own depth is kept (mapped so
that depth 1 is a top-level clause). This is exposed as
`lexichunk.ingestion.refine_heading()` if you are writing an adapter of your
own.

## `from_docling`

```python
from lexichunk.ingestion import from_docling

sections = from_docling(
    document,                  # DoclingDocument, or its JSON as str/bytes, or a dict
    jurisdiction="uk",
    include_title=True,        # emit the TitleItem as a root enclosing everything
    include_tables=True,       # export tables row-wise into the enclosing section
    include_furniture=False,   # keep page headers/footers/footnotes
)
```

Section headers open a section; the text, list and table items that follow fill
it. Content before the first header becomes a preamble section, exactly as
lexichunk's own parser treats leading text.

**Furniture is dropped by default, and this is a large part of the point.** A
running `CONFIDENTIAL — Project Atlas Services Agreement` header appearing
every 45 lines is, in extracted text, an unavoidable smear across whichever
clause spans each page break. Docling has already identified it as page
furniture. Dropping it here is free; recovering from it downstream is not.

**Tables are exported row-wise**, one row per line as `cell | cell | cell`,
rather than as a markdown pipe table. A row of a fee schedule or a data
processing annex carries a sentence's worth of meaning (`Managed hosting | GBP
5,000 | Monthly`), and keeping each row on its own line lets the cascading
splitter break an over-sized table *between* rows instead of mid-row. A
spanning cell's duplicated text is collapsed, so `Fees | Fees | Fees` reads as
`Fees`. Table captions come first.

The JSON form works too, which matters when conversion happens in a different
process or on a different machine:

```python
sections = from_docling(open("msa.docling.json").read(), jurisdiction="uk")
```

## `from_unstructured`

```python
from unstructured.partition.auto import partition
from lexichunk.ingestion import from_unstructured

sections = from_unstructured(partition("msa.pdf"), jurisdiction="us")
```

`Title` elements open a section; `NarrativeText`, `ListItem` and `Table` fill
it. `Header`, `Footer`, `PageNumber` and `PageBreak` are dropped unless you
pass `include_furniture=True`. Heading depth comes from
`metadata.category_depth`, which `unstructured` numbers from 0 — so it maps
straight onto lexichunk's levels with no shift — and is overridden by legal
numbering as described above.

An element with a category the adapter does not recognise is **kept**, not
dropped: a stray caption in the enclosing clause is a smaller problem than
silently losing text somebody extracted on purpose.

Nothing is imported from `unstructured`. Any object with `.category`, `.text`
and `.metadata` works, which also makes this adapter trivial to test.

## `from_markdown`

```python
from lexichunk.ingestion import from_markdown

sections = from_markdown(markdown_text, jurisdiction="uk")
```

Markdown is what most pipelines already produce — Docling exports it, `pandoc`
emits it, LLM extraction steps return it, and so do most internal converters.
If you have markdown with real headings, you have structure.

Only ATX headings (`# Heading`) are read; fenced code blocks are skipped so a
`#` comment inside one cannot open a section. Because the source is plain text,
every section records its `char_start`/`char_end` in it, so
`raw_char_start`/`raw_char_end` come through on every chunk with no extra work:

```python
chunks = LegalChunker(jurisdiction="uk").chunk_documents(from_markdown(md))
for chunk in chunks:
    print(md[chunk.raw_char_start:chunk.raw_char_end])   # back to the source
```

## Writing your own adapter

If your converter is not one of these, produce `Section` records directly —
that is the whole interface. Two helpers are worth reusing:

- `lexichunk.ingestion.refine_heading(heading, jurisdiction, fallback_level)`
  returns `(identifier, title, level)` using the rules in the table above.
- Give the preamble level `-99` for content before the first heading;
  `chunk_documents()` knows not to synthesise a header line for it.

For a converter that produces a full clause tree of its own, `chunk_documents()`
also accepts `ParsedClause` objects directly. Feeding
`StructureParser.parse(text)` straight back in reproduces `chunk(text)`
byte-for-byte — which is the property that makes this path safe to build
against.

## Metrics

`chunk_documents(..., return_metrics=True)` returns the same `PipelineMetrics`
object `chunk_with_metrics()` does. Two fields read differently on this path:
`clause_count` is the number of sections you supplied, and
`heading_candidates_rejected` is always `0`, because no heading detection ran.
`chunks_unclassified` is worth watching here too — a converter that produced
sections but no usable text shows up as `chunks_unclassified == chunk_count`.
The one to assert on is unchanged:

```python
chunks, metrics = chunker.chunk_documents(sections, return_metrics=True)
assert metrics.chunks_spanning_multiple_top_level_clauses == 0
```

See [architecture.md](architecture.md#structure-quality-metrics) for the rest.
