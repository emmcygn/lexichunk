"""Execute every ``python`` code block in README.md.

The README is the first thing a reader runs. This module extracts each
fenced ``python`` block from it and executes the block, so a rename or a
signature change in the package breaks the test suite rather than silently
rotting the documentation.

Conventions the README must follow for this to work:

* A block that cannot run in CI — because it needs a live embedding model, a
  network call, or an API key — is preceded by an HTML comment containing
  ``lexichunk-doctest: skip``.  The comment is visible in the Markdown source
  and states the reason, so the exemption is never silent.
* A block may use the shared names supplied by :data:`_NAMESPACE_SOURCE`
  (``contract_text``, ``text_1``…``text_3``, ``documents``,
  ``loaded_documents``) without defining them.  Everything else it must
  import or define itself.
* Blocks mentioning ``langchain`` or ``llama_index`` are skipped when the
  corresponding optional dependency is not installed.

Blocks are executed in README order, each in a fresh namespace.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

README_PATH = Path(__file__).resolve().parent.parent / "README.md"

# A fenced block plus whatever HTML comment immediately precedes it.
_BLOCK_RE = re.compile(
    r"(?P<preamble>(?:<!--.*?-->\s*)*)```python\n(?P<code>.*?)\n```",
    re.DOTALL,
)

_SKIP_MARKER = "lexichunk-doctest: skip"

# A small but structurally realistic UK contract: numbered clauses, a
# definitions clause with two quoted terms, and a cross-reference.
SAMPLE_CONTRACT = """\
SERVICE AGREEMENT

This Service Agreement is made between Acme Software Limited (the "Supplier")
and GlobalCorp plc (the "Customer").

1. Definitions

1.1 "Confidential Information" means all information disclosed by one party to
the other, whether orally or in writing, that is designated as confidential or
that a reasonable person would understand to be confidential.

1.2 "Services" means the software development and support services described
in Schedule 1.

2. Supply of the Services

2.1 The Supplier shall provide the Services with reasonable skill and care and
in accordance with Clause 5.2.

2.2 The Customer shall provide the Supplier with such access, information and
co-operation as the Supplier reasonably requires to perform the Services.

3. Confidentiality

3.1 Each party shall keep the other party's Confidential Information secret
and shall not disclose it to any third party without prior written consent.

3.2 This Clause 3 shall survive termination of this Agreement.

4. Limitation of Liability

4.1 Neither party shall be liable to the other for any indirect, special or
consequential loss, loss of profits, loss of revenue or loss of anticipated
savings, howsoever arising.

4.2 The aggregate liability of either party under this Agreement shall not
exceed the total fees paid in the twelve months preceding the claim.

5. Payment

5.1 The Customer shall pay the Supplier the fees set out in Schedule 2.

5.2 Invoices are payable within thirty days of the date of issue.

6. Governing Law

6.1 This Agreement is governed by the law of England and Wales.
"""


def _optional(name: str) -> bool:
    """Return ``True`` when the named optional dependency imports."""
    try:
        __import__(name)
    except ImportError:
        return False
    return True


_HAVE_LANGCHAIN = _optional("langchain_core")
_HAVE_LLAMA_INDEX = _optional("llama_index.core")


def _namespace() -> dict[str, Any]:
    """Build the shared namespace a README block may rely on.

    ``__name__`` is deliberately *not* ``"__main__"``, so the README's
    Windows/macOS ``if __name__ == "__main__":`` batch guard defines its
    function without starting a process pool during the test run.
    """
    namespace: dict[str, Any] = {
        "__name__": "lexichunk_readme_block",
        "contract_text": SAMPLE_CONTRACT,
        "text": SAMPLE_CONTRACT,
        "text_1": SAMPLE_CONTRACT,
        "text_2": SAMPLE_CONTRACT,
        "text_3": SAMPLE_CONTRACT,
        "documents": [SAMPLE_CONTRACT, SAMPLE_CONTRACT],
    }
    if _HAVE_LANGCHAIN:
        from langchain_core.documents import Document as _LCDocument

        namespace["loaded_documents"] = [
            _LCDocument(page_content=SAMPLE_CONTRACT, metadata={"source": "sample.pdf"})
        ]
    return namespace


def _extract_blocks() -> list[tuple[int, str, bool]]:
    """Return ``(ordinal, code, skip)`` for every python block in the README."""
    text = README_PATH.read_text(encoding="utf-8")
    blocks: list[tuple[int, str, bool]] = []
    for ordinal, match in enumerate(_BLOCK_RE.finditer(text), start=1):
        preamble = match.group("preamble") or ""
        blocks.append((ordinal, match.group("code"), _SKIP_MARKER in preamble))
    return blocks


BLOCKS = _extract_blocks()


def _block_id(block: tuple[int, str, bool]) -> str:
    ordinal, code, _skip = block
    first_line = next(
        (line for line in code.splitlines() if line.strip() and not line.startswith("#")),
        code.splitlines()[0] if code.splitlines() else "",
    )
    return f"block{ordinal:02d}-{first_line.strip()[:48]}"


def test_readme_has_python_blocks() -> None:
    """Guard against the extractor silently matching nothing."""
    assert len(BLOCKS) >= 8, f"expected the README to carry python examples, found {len(BLOCKS)}"


def test_every_skip_marker_states_a_reason() -> None:
    """A skipped block must say why, in the README itself."""
    text = README_PATH.read_text(encoding="utf-8")
    for comment in re.findall(r"<!--\s*lexichunk-doctest:\s*skip(.*?)-->", text, re.DOTALL):
        assert comment.strip(), "a lexichunk-doctest: skip marker must state a reason"


@pytest.mark.parametrize("block", BLOCKS, ids=_block_id)
def test_readme_block_executes(block: tuple[int, str, bool]) -> None:
    """Execute one README python block in a fresh namespace."""
    ordinal, code, skip = block
    if skip:
        pytest.skip(f"README block {ordinal} is marked lexichunk-doctest: skip")
    if "langchain" in code and not _HAVE_LANGCHAIN:
        pytest.skip("langchain-core is not installed")
    if "llama_index" in code and not _HAVE_LLAMA_INDEX:
        pytest.skip("llama-index-core is not installed")

    namespace = _namespace()
    compiled = compile(code, f"<README.md block {ordinal}>", "exec")
    exec(compiled, namespace)  # noqa: S102 - executing documentation is the point
