# Security Policy

## Supported Versions

lexichunk is a source-distributed public beta. It is not yet published on
PyPI; `v0.9.0` is the first tagged release, and installs are expected to pin
that tag (or a reviewed commit SHA).

Security fixes target the latest commit published on the repository's default
branch, and are folded into the next tag. Older tags, older commits and forks
are not maintained as separate release lines.

| Reference | Supported |
| --------- | --------- |
| default branch (`master`) | :white_check_mark: |
| `v0.9.0` | :white_check_mark: |
| earlier commits / pre-release tags | :x: |

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Use [GitHub's private vulnerability reporting](https://github.com/emmcygn/lexichunk/security/advisories/new)
for this repository — the "Security" tab, then "Report a vulnerability". That
channel is private to the maintainers and is the only one monitored for
security reports.

Include a description of the issue, affected code paths, reproduction steps,
and any relevant proof of concept. We aim to acknowledge reports within 5
business days. Disclosure timing is coordinated through the private report.

## Scope

lexichunk parses untrusted document text with regular expressions and has no
network, filesystem or subprocess behaviour beyond `chunk_batch(workers>1)`,
which starts worker processes running this package's own code.

In scope:

- catastrophic regex backtracking (ReDoS) on adversarial input — see
  `tests/test_redos_audit.py`, which drives every pattern in the package with
  pathological strings;
- unbounded memory or CPU growth on input under the 10,000,000-character
  guard;
- anything that lets document content escape the parser and affect the host
  process.

Out of scope:

- a wrong or missing chunk, clause type, defined term or cross-reference —
  that is a correctness bug, so please open a normal issue;
- resource exhaustion from deliberately passing input larger than the
  documented limit.

## Optional Dependency Advisory

The core `lexichunk` package has no mandatory third-party runtime dependencies.
The optional `llama-index` extra currently permits `llama-index-core`, which can
install NLTK 3.10.3 transitively. NLTK 3.10.3 is affected by
[GHSA-8mgp-746c-j5xp](https://github.com/advisories/GHSA-8mgp-746c-j5xp), a
model-file path containment bypass with no fixed NLTK release listed as of
2026-09-06.

Lexichunk does not call NLTK's affected model training, parsing, loading, or
saving APIs, and importing or using `LegalNodeParser` does not require those
paths. Applications that install optional integrations should still audit
their complete dependency graph and avoid processing untrusted NLTK model
artifacts. This scoped assessment is not a claim that every transitive
dependency is vulnerability-free.
