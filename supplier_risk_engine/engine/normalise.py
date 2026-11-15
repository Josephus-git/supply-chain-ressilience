"""Normalisation for exact-equality matching (plan section 5.1).

There is no fuzzy scoring anywhere in this module. Every comparison the
engine makes is equality, prefix, or whole-word containment on the values
these functions return.
"""

from __future__ import annotations

import re
import unicodedata

from .reference import COUNTRY_NAMES, ISO_COUNTRY_CODES

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_UNNAMED = re.compile(r"\(\s*unnamed\s*\)", re.IGNORECASE)
# Dots and apostrophes are deleted so abbreviations stay one word
# ("V.S." -> "vs", "L.L.C." -> "llc"); any other non-alphanumeric is a space.
_DELETED = re.compile(r"[.'’]")
_NON_WORD = re.compile(r"[^\w]+|_")
_LIST_SEPARATORS = re.compile(r"[;,]")

# Legal suffix tokens removed from the end of company-like names, repeatedly,
# so "Sdn Bhd" and "Pte Ltd" are both removed.
LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "llc",
        "llp",
        "lp",
        "plc",
        "gmbh",
        "ag",
        "sa",
        "bv",
        "nv",
        "berhad",
        "bhd",
        "sdn",
        "pte",
        "pty",
    }
)

GENERIC_PORT_WORDS = frozenset(
    {
        "port",
        "ports",
        "terminal",
        "terminals",
        "pier",
        "piers",
        "harbour",
        "harbours",
        "harbor",
        "harbors",
        "of",
        "the",
    }
)


def normalise_text(value: str) -> str:
    """Case-fold, remove punctuation, and collapse whitespace."""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = _DELETED.sub("", text)
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def normalise_name(value: str) -> str:
    """Normalise a company, parent, buyer, carrier, or vessel name.

    Bracketed role text is removed, then punctuation, then trailing legal
    suffixes. A name made only of suffixes keeps its last token, so it never
    normalises to the empty string.
    """
    text = _BRACKETED.sub(" ", value)
    tokens = normalise_text(text).split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def split_name_list(value: str) -> list[str]:
    """Split a list-valued record field on ';' or ','.

    Bracketed text is removed before splitting, so a comma inside a role
    note does not split a name. Entries marked "(unnamed)" are dropped.
    Returns the raw (unnormalised) entries, stripped.
    """
    entries: list[str] = []
    for part in _split_outside_brackets(value):
        if _UNNAMED.search(part):
            continue
        part = part.strip()
        if part:
            entries.append(part)
    return entries


def _split_outside_brackets(value: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in value:
        if char in "([":
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
        if depth == 0 and _LIST_SEPARATORS.fullmatch(char):
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def normalise_port_name(value: str) -> str:
    """Normalise a graph port name for containment matching.

    Any trailing state or province tag after the first comma is dropped
    ("Long Beach, Ca" -> "long beach"). Legal suffixes are not removed.
    """
    head = value.split(",", 1)[0]
    return normalise_text(head)


def is_generic_port_name(normalised: str) -> bool:
    tokens = normalised.split()
    return not tokens or all(token in GENERIC_PORT_WORDS for token in tokens)


def contains_whole_words(haystack: str, needle: str) -> bool:
    """True when normalised `needle` appears in normalised `haystack` on word
    boundaries. Both arguments must already be normalised."""
    if not needle:
        return False
    return f" {needle} " in f" {haystack} "


def hs_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def hs_codes_match(payload_code: str, record_code: str) -> bool:
    """Digits only; one code is a prefix of the other; both at least 6 digits."""
    a, b = hs_digits(payload_code), hs_digits(record_code)
    if len(a) < 6 or len(b) < 6:
        return False
    return a.startswith(b) or b.startswith(a)


def country_to_code(value: str) -> str | None:
    """Convert an ISO alpha-2 code or a country name to a code.

    Returns None when the value is not a known code or a name in the
    reviewed table.
    """
    stripped = value.strip()
    if len(stripped) == 2 and stripped.isalpha() and stripped.upper() in ISO_COUNTRY_CODES:
        return stripped.upper()
    return COUNTRY_NAMES.get(normalise_text(stripped))
