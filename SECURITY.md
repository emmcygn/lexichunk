# Security Policy

## Supported Versions

`0.9.0` is the first PyPI release. Until 1.0.0, only the latest published
version receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.9.x | :white_check_mark: |
| < 0.9.0 (source-only pre-releases) | :x: |

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for a security vulnerability.

Use [GitHub's private vulnerability reporting](https://github.com/emmcygn/lexichunk/security/advisories/new)
for this repository — the "Security" tab, then "Report a vulnerability". That
channel is private to the maintainers and is the only one monitored for
security reports.

Include a description of the issue, steps to reproduce, and any proof of
concept. We aim to acknowledge reports within 5 business days. Once a fix is
available we will agree a disclosure timeline with the reporter before
publishing an advisory.

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
