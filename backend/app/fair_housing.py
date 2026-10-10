"""Phrases that describe who should live in a home rather than the home itself (familial status,
religion, race or national origin, disability, age, source of income). The prompt forbids them and
every AI output is checked; a hit counts as a failed attempt."""

import re

BANNED = (
    "adults only", "adult only", "no children", "no kids", "no families", "child free", "child-free",
    "perfect for families", "ideal for families", "great for families", "family neighborhood", "family neighbourhood",
    "perfect for couples", "ideal for couples", "perfect for singles", "ideal for singles", "bachelor pad",
    "empty nesters", "empty-nesters", "mature couple", "mature person", "mature adults", "young professionals",
    "young couple", "golden agers", "retirees only", "seniors only",
    "christian", "jewish", "muslim", "catholic", "hindu", "church nearby", "near church", "near mosque",
    "near synagogue", "near temple",
    "white neighborhood", "white neighbourhood", "hispanic", "latino", "asian community", "black community",
    "ethnic", "integrated neighborhood", "exclusive neighborhood", "exclusive neighbourhood", "exclusive community",
    "english speaking", "english-speaking", "native speakers", "no immigrants",
    "no wheelchairs", "able-bodied", "able bodied", "physically fit", "handicapped", "not suitable for disabled",
    "no section 8", "no dss", "no housing benefit", "no welfare",
    "safe neighborhood", "safe neighbourhood", "crime-free", "crime free",
)

_PATTERN = re.compile(r"\b(" + "|".join(re.escape(p) for p in BANNED) + r")\b", re.IGNORECASE)


def violations(*texts: str) -> list[str]:
    found: list[str] = []
    for value in texts:
        for match in _PATTERN.finditer(value or ""):
            phrase = match.group(1).lower()
            if phrase not in found:
                found.append(phrase)
    return found


def strings_in(value) -> list[str]:
    """Every string inside a JSON-like value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings_in(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings_in(v)]
    return []
