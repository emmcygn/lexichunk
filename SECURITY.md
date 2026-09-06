# Security Policy

## Supported Versions

lexichunk is currently a source-distributed public beta. Security fixes target
the latest commit published on the repository's default branch. Older commits
and forks are not maintained as separate release lines.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Preferred: use [GitHub's private vulnerability reporting](https://github.com/emmcygn/lexichunk/security/advisories/new)
for this repository ("Security" tab → "Report a vulnerability").

Include a description of the issue, affected code paths, reproduction steps,
and any relevant proof of concept. Disclosure timing is coordinated through
the private report.

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
