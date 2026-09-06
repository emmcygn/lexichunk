# Extending lexichunk

## Custom Jurisdictions

lexichunk ships with UK, US and EU jurisdiction support. You can add your own by implementing the `JurisdictionPatterns` protocol and registering a `detect_level` function.

### Step 1: Create a Patterns Object

Your patterns object must have these six attributes:

```python
import re

class EUPatterns:
    """EU-style legal document patterns."""

    cross_ref = re.compile(
        r"\b(?:Article|Paragraph|Annex)\s+\d+(?:\.\d+)*(?:\([a-z]\))?",
        re.IGNORECASE,
    )
    definition = re.compile(
        r'"([A-Z][A-Za-z\s]+?)"\s+(?:means|shall mean|refers to)',
    )
    definition_curly = re.compile(
        r"\u201c([A-Z][A-Za-z\s]+?)\u201d\s+(?:means|shall mean|refers to)",
    )
    definitions_headers = ("definitions", "interpretation")
    boilerplate_headers = ("final provisions", "general provisions")
    signature_markers = ("done at", "in witness whereof")
```

No inheritance is required — any object with these attributes satisfies the `JurisdictionPatterns` protocol (duck typing via `@runtime_checkable`).

### Step 2: Write a detect_level Function

This function receives a single line of text and returns `(level, identifier)` if the line is a clause header, or `None` otherwise.

```python
from typing import Optional

def eu_detect_level(line: str) -> Optional[tuple[int, str]]:
    """Detect EU-style clause headers.

    Examples:
        "Article 1" -> (0, "Article 1")
        "1.1" -> (1, "1.1")
        "(a)" -> (2, "(a)")
    """
    stripped = line.strip()

    # Article-level headers
    m = re.match(r"^(Article\s+\d+)", stripped, re.IGNORECASE)
    if m:
        return (0, m.group(1))

    # Numbered subsections
    m = re.match(r"^(\d+\.\d+(?:\.\d+)*)\b", stripped)
    if m:
        depth = m.group(1).count(".")
        return (depth, m.group(1))

    # Lettered sub-clauses
    m = re.match(r"^\(([a-z])\)", stripped)
    if m:
        return (2, f"({m.group(1)})")

    return None
```

`detect_level` is deliberately **stateless and permissive**: it only has to recognise the *shape* of a header. Before a match is accepted, `StructureParser` applies a jurisdiction-agnostic **heading-plausibility gate** that looks at the surrounding lines and can reject the match. The gate is reject-only — it never promotes a line to a header — so a rejected line simply stays body text, exactly as if `detect_level` had returned `None`. It currently rejects:

- table-of-contents entries (leader dots or a right-aligned page number);
- a container-level match (levels `-1`/`-2` — Schedule, Exhibit, Annex, Chapter) that is neither at column 0 nor preceded by a blank line, i.e. a word-wrapped cross-reference such as `"     Schedule 2."`;
- a standalone ALL-CAPS level-0 heading that is page furniture (`CONFIDENTIAL`, `TABLE OF CONTENTS`, `PAGE …`), is longer than eight words, is not preceded by a blank line, or continues an unterminated ALL-CAPS paragraph;
- a numeric level-0 heading whose remainder reads as prose (a long, `.`/`;`-terminated sentence) or starts with a unit or month word (`3 Business Days after …`);
- any heading whose remainder begins with a comma — that is a wrapped sentence, not a heading.

The number of matches the gate rejected in the last parse is available as `StructureParser.last_rejected_headings`.

The parser also disambiguates the sub-clause labels that are both valid alpha labels and valid Roman numerals — `(i)`, `(v)`, `(x)`, `(l)`, `(c)`. If such a label directly follows its alphabetic predecessor at the same indent (`(i)` after `(h)`), it is read as alpha (level 3); otherwise it is read as Roman (level 4). Return level 3 for alpha sub-clauses and level 4 for Roman ones so a custom jurisdiction participates in this.

### Step 2b (optional): Declare Section Roles

The hierarchy level `-1` means different things in different jurisdictions — a UK/US Schedule is an attachment, but an EU Chapter is a grouping of operative Articles. Declare what a level *means* by adding a module-level `SECTION_ROLES` dict next to your `detect_level` function:

```python
from lexichunk.models import DocumentSection

SECTION_ROLES: dict[int, DocumentSection] = {
    -1: DocumentSection.OPERATIVE,   # Chapter — a grouping, not an attachment
    -2: DocumentSection.SCHEDULES,   # Annex
}
```

`StructureParser` reads this attribute from the module that defines `detect_level`. It is entirely optional: any level with no entry — and every jurisdiction that declares no mapping at all — defaults to `DocumentSection.OPERATIVE`, after which the usual title/identifier keyword rules (definitions, recitals, signatures) apply. Those keyword rules match on whole words against the clause's identifier and title, and the signature rule additionally consults your patterns object's `signature_markers`.

### Step 3: Register

```python
from lexichunk import LegalChunker, register_jurisdiction

register_jurisdiction("eu", EUPatterns(), eu_detect_level)

chunker = LegalChunker(jurisdiction="eu", doc_type="contract")
chunks = chunker.chunk(document_text)
```

### Limitations

- Custom jurisdictions cannot be used with `chunk_batch(workers>1)` because the registration cannot be pickled to child processes. Use `workers=1` for custom jurisdictions.
- The `detect_level` function is called once per line — keep it fast.

## Custom Clause Signals

The clause type classifier uses keyword signals to score each chunk. You can add custom keywords for any `ClauseType`:

```python
from lexichunk import LegalChunker, ClauseType

chunker = LegalChunker(
    jurisdiction="uk",
    extra_clause_signals={
        ClauseType.FORCE_MAJEURE: ["pandemic", "epidemic", "quarantine"],
        ClauseType.CONFIDENTIALITY: ["trade secret", "proprietary"],
    },
)
chunks = chunker.chunk(text)
```

The extra signals are merged with the built-in signals — they do not replace them. The built-in `CLAUSE_SIGNALS` dict is never mutated.

### How Classification Works

1. Each chunk's content is scanned for keyword matches against all 31 clause types.
2. Scoring is phrase-length weighted, not a flat count: each signal match adds a
   weight equal to the number of words in that signal (`len(signal.split())`).
   A multi-word phrase like `"limitation of liability"` therefore contributes
   more to its type's score than a single-word match like `"payable"`.
3. Position bonus: +1.5 for end-of-document types (governing law, assignment, etc.) when the chunk is past the 75% mark.
4. The type with the highest score wins. Confidence = `best_score / sum_of_all_scores`.
5. The runner-up becomes `secondary_clause_type`.

### Inspecting Classification Details

```python
from lexichunk.enrichment.clause_type import ClauseTypeClassifier

classifier = ClauseTypeClassifier()
result = classifier.classify_detailed(chunk_text, relative_position=0.8)
print(result.clause_type)             # ClauseType.GOVERNING_LAW
print(result.confidence)              # 0.72
print(result.secondary_clause_type)   # ClauseType.AMENDMENT
print(dict(result.scores))            # {ClauseType.GOVERNING_LAW: 5.5, ...}
```
