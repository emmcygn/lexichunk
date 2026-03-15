# Extending lexichunk

## Custom Jurisdictions

lexichunk ships with UK and US jurisdiction support. You can add your own by implementing the `JurisdictionPatterns` protocol and registering a `detect_level` function.

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

1. Each chunk's content is scanned for keyword matches against all 15 clause types.
2. Each match adds 1 to that type's score.
3. Position bonus: +1.5 for end-of-document types (governing law, assignment, etc.) when the chunk is past the 75% mark.
4. The type with the highest score wins. Confidence = `best_score / sum_of_all_scores`.
5. The runner-up becomes `secondary_clause_type`.

### Inspecting Classification Details

```python
from lexichunk.enrichment.clause_type import ClauseTypeClassifier

classifier = ClauseTypeClassifier()
result = classifier.classify_detailed(chunk_text, relative_position=0.8)
print(result.clause_type)       # ClauseType.GOVERNING_LAW
print(result.confidence)        # 0.72
print(result.secondary_type)    # ClauseType.AMENDMENT
print(dict(result.scores))      # {ClauseType.GOVERNING_LAW: 5.5, ...}
```
