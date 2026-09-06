"""Shared regex fragments for matching quoted defined-term names.

This module imports nothing from lexichunk, so both
:mod:`lexichunk.jurisdiction` and :mod:`lexichunk.parsers` can use it without
creating an import cycle.

Two defects motivated pulling these fragments out of the twenty-odd places
that previously spelled them inline:

* Every term-capture group used ``[A-Za-z\\s\\-]`` — letters, whitespace and
  hyphen only.  A document defining ``"R&D"``, ``"C++ Code"`` and
  ``"Level 1 Support"`` yielded *zero* terms, and the same happened for
  ``"Section 409A Plan"``, ``"Schedule 2 Services"`` and ``"Tier1"``.  These
  are ordinary term names in technology and commercial contracts, and the
  loss was silent and total — not a mis-attachment, an absence.

* Nothing constrained what could precede an opening quote.  In
  ``1.1 "Client's Data" means the data supplied by the client.`` the regex
  engine treated the apostrophe inside ``Client's`` as an opening single
  quote, matched ``[a-z]`` = ``s``, then ``" Data"``, then the real closing
  ``"`` — producing the bogus term ``"s Data"``.  Possessive term names
  ("Seller's Knowledge", "Purchaser's Group", "Guarantor's Obligations") are
  standard M&A and commercial drafting.
"""

from __future__ import annotations

#: Characters permitted *inside* a defined-term name, after the initial
#: letter.  Digits and ``&``/``+`` are required by real term names; the two
#: apostrophe forms are required by possessive ones.  Parentheses are
#: deliberately excluded so ``"Affiliate(s)"`` still reaches the dedicated
#: parenthesised-plural pattern rather than being captured verbatim.
TERM_CHARS = r"A-Za-z0-9\s\-&+'’"

#: A term name beginning with an upper-case letter.
TERM_UPPER = rf"[A-Z][{TERM_CHARS}]{{1,60}}"

#: A term name beginning with a lower-case letter.
TERM_LOWER = rf"[a-z][{TERM_CHARS}]{{1,60}}"

#: A term name beginning with a letter of either case.
TERM_ANY = rf"[A-Za-z][{TERM_CHARS}]{{1,60}}"

#: As :data:`TERM_ANY` but allowing a one-character name — used by the
#: parenthesised-plural pattern, where the ``(s)`` follows the stem.
TERM_ANY_SHORT = rf"[A-Za-z][{TERM_CHARS}]{{0,60}}"

#: A real opening quote is never preceded by a word character; a possessive
#: apostrophe always is.  Guarding every opening-quote class with this
#: lookbehind is what stops ``Client's`` from opening a quote of its own.
#: It is a zero-width assertion, so it never shifts a capture group's number.
NOT_AFTER_WORD = r"(?<![A-Za-z0-9])"

#: Opening-quote character class, always used behind :data:`NOT_AFTER_WORD`.
OPEN_QUOTE = r"[\"'“‘]"

#: Closing-quote character class.
CLOSE_QUOTE = r"[\"'”’]"

#: Opening/closing pair for straight double + curly double quotes only.
OPEN_DOUBLE = r"[\"“]"
CLOSE_DOUBLE = r"[\"”]"

#: Opening/closing pair for straight single + curly single quotes only.
OPEN_SINGLE = r"['‘]"
CLOSE_SINGLE = r"['’]"
