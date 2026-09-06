"""Escalate only the clauses the keyword classifier was unsure about.

lexichunk classifies clause types with a keyword scorer: fast, free,
deterministic, and confident about the clauses that use standard drafting
language.  It is *not* confident about a clause headed "Miscellany" whose
body happens to talk about three unrelated things — and on a corpus of
40,000 contracts you would rather not pay an LLM to look at every chunk to
find the few hundred like that.

``classification_hook`` is that seam.  It fires only for chunks whose
``classification_confidence`` is below ``classification_hook_threshold``,
after Stage 4 and before the context header is generated, so whatever the
hook decides is what gets embedded.

This example uses a stub callable that stands in for the model call — it
makes no network requests and needs no API key, so the file runs as-is.
The comments mark exactly where a real call would go.

Run::

    python examples/llm_fallback.py
"""

from __future__ import annotations

from lexichunk import LegalChunker
from lexichunk.enrichment.clause_type import ClassificationResult
from lexichunk.models import ClauseType, LegalChunk

CONTRACT = """\
1. Definitions
In this agreement the following terms have the meanings given to them in
this clause 1.

2. Miscellany
The parties record for completeness that the schedules form part of this
agreement and that headings are for convenience only.

3. Insurance and Cover
Each party shall maintain such policies as are reasonable and shall provide
evidence of the same on request.

4. Governing Law
This agreement and any dispute arising out of it are governed by the laws of
England and Wales, and the parties submit to the exclusive jurisdiction of
the English courts.
"""


# ---------------------------------------------------------------------------
# The hook
# ---------------------------------------------------------------------------
#
# Defined at module level, not as a lambda or a closure, so it survives
# pickling into a worker process. `chunk_batch(workers>1)` checks this up
# front and raises ConfigurationError naming the fix if it cannot.


def _stub_model(prompt: str) -> str:
    """Stand in for an LLM call; returns a ClauseType value as a string.

    Replace the body with your provider's client, e.g.::

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    Keep the prompt asking for one of ``ClauseType``'s values and nothing
    else, and keep the ``ClauseType(...)`` parse below — a model that
    answers with prose must not be allowed to become a clause type.
    """
    lowered = prompt.lower()
    if "insurance" in lowered or "policies" in lowered:
        return "insurance"
    if "schedules form part" in lowered or "headings are for convenience" in lowered:
        return "boilerplate"
    return "unknown"


def classify_with_model(
    chunk: LegalChunk, result: ClassificationResult
) -> ClauseType | None:
    """Ask the model what this chunk is; return ``None`` to keep the keyword verdict.

    Args:
        chunk: The chunk the keyword scorer was unsure about.
        result: That scorer's own verdict, including the per-clause-type
            ``scores`` mapping — useful for a prompt that offers the model a
            shortlist rather than all 31 types.

    Returns:
        A :class:`~lexichunk.models.ClauseType`, or ``None`` to leave the
        keyword classification (and ``classification_source="keyword"``)
        alone.
    """
    shortlist = sorted(result.scores, key=lambda t: result.scores[t], reverse=True)[:5]
    prompt = (
        "Classify this contract clause. Answer with exactly one of: "
        + ", ".join(t.value for t in shortlist)
        + ", or 'unknown'.\n\n"
        + chunk.content
    )

    answer = _stub_model(prompt)
    try:
        clause_type = ClauseType(answer.strip().lower())
    except ValueError:
        # The model answered with something that is not a clause type. Keep
        # the keyword verdict rather than inventing one.
        return None
    if clause_type is ClauseType.UNKNOWN:
        return None
    return clause_type


def main() -> None:
    """Chunk the sample contract with and without the hook, and compare."""
    baseline = LegalChunker(jurisdiction="uk", min_chunk_size=0).chunk(CONTRACT)

    chunker = LegalChunker(
        jurisdiction="uk",
        min_chunk_size=0,
        classification_hook=classify_with_model,
        # classification_confidence is a saturation-scaled margin, not a
        # calibrated probability. 0.5 is a reasonable starting point; tune it
        # against your own corpus by measuring how many chunks it escalates.
        classification_hook_threshold=0.5,
    )
    chunks = chunker.chunk(CONTRACT)

    print(f"{'#':>2}  {'hierarchy':<28} {'conf':>5}  {'keyword':<18} -> final")
    print("-" * 82)
    escalated = 0
    changed = 0
    for before, after in zip(baseline, chunks):
        marker = " "
        if after.classification_source == "hook":
            escalated += 1
            if after.clause_type is not before.clause_type:
                changed += 1
                marker = "*"
        print(
            f"{after.index:>2}{marker} {after.hierarchy_path[:28]:<28} "
            f"{after.classification_confidence:>5.2f}  "
            f"{before.clause_type.value:<18} -> {after.clause_type.value}"
            f"  [{after.classification_source}]"
        )

    print()
    print(
        f"{len(chunks)} chunks, {escalated} escalated to the model "
        f"({escalated / len(chunks):.0%}), {changed} reclassified."
    )
    print(
        "Only the escalated chunks would have cost a model call; the rest "
        "were settled by keywords."
    )


if __name__ == "__main__":
    main()
