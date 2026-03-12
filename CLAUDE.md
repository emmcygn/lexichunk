# Legal Chunker SDK — CLAUDE.md

## Project Context
Building `lexchunk` — a Python SDK for legal-document-aware text chunking optimized for RAG pipelines. Targets UK and US contracts and terms & conditions. Published to PyPI. This is a 6-hour Claude Code sprint aiming for 2 weeks of equivalent dev output.

## Domain Knowledge
- Legal documents have hierarchical structure: Articles → Sections → Subsections → Clauses → Sub-clauses
- UK numbering: flat (1, 1.1, 1.1.1, (a), (i))
- US numbering: multi-tier (Article I, Section 1.01, (a), (i)), often with ALL CAPS headers
- Defined terms are capitalised and typically defined in a dedicated section ("Definitions")
- Cross-references are pervasive: "as defined in Section 2.1", "subject to Clause 5(a)", "see Schedule 2"
- Legal abbreviations break standard NLP sentence splitters: "U.S.C.", "F.3d.", "LLC.", "Ltd."
- Clause types that matter: definitions, representations, warranties, covenants, conditions, indemnification, termination, confidentiality, governing law, force majeure, assignment, amendment, notices, entire agreement, severability

## Tech Stack
- Python 3.10+
- No heavy dependencies — regex + dataclasses for core, optional pydantic for validation
- pytest for testing
- setuptools/pyproject.toml for PyPI packaging
- Optional integrations: langchain, llama-index (as extras)

---

## Workflow Orchestration

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behaviour between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Trade-off and Risk**: Always include a trade-off and risk audit in your check-in for users to give guidance
4. **Track Progress**: Mark items complete as you go
5. **Explain Changes**: High-level summary at each step
6. **Document Results**: Add review section to `tasks/todo.md`
7. **Capture Lessons**: Update `tasks/lessons.md` after corrections

---

## Core Principles
- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

---

## Project-Specific Rules

### Architecture Decisions
- Core chunking logic MUST be zero-dependency (stdlib only + regex)
- All external integrations (langchain, llama-index) are optional extras
- Every chunk output MUST be a structured dataclass, not a raw dict
- Metadata enrichment is a separate pipeline stage, not baked into the chunker
- Jurisdiction detection is config-driven (UK/US), not magic inference

### Testing Standards
- Every regex pattern MUST have at least 3 positive and 2 negative test cases
- Test against real contract excerpts (use CUAD dataset samples or public domain contracts)
- Chunk output tests must verify: no orphaned cross-references, hierarchy preserved, metadata populated
- Integration tests for LangChain/LlamaIndex compatibility

### Code Style
- Type hints on all public functions
- Docstrings on all public classes and methods (Google style)
- No classes where a function will do — keep it simple
- Prefer composition over inheritance for chunker strategies

### Sprint Priorities (6-hour session)
1. **Hour 1**: Project scaffold + core data models + pyproject.toml
2. **Hour 2**: Legal structure parser (section/clause detection, UK + US numbering)
3. **Hour 3**: Clause-level chunker with hierarchy preservation
4. **Hour 4**: Defined terms extraction + cross-reference detection
5. **Hour 5**: Metadata enrichment + context assembly
6. **Hour 6**: LangChain/LlamaIndex integration + PyPI packaging + README + tests

### What NOT to Build
- No web UI or CLI — SDK only
- No ML models — regex and heuristic patterns only (v1)
- No PDF parsing — assume text input (users handle extraction)
- No document comparison or diff
- No authentication or API layer
