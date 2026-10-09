"""Username rules (docs/SCOPE.md 5): 3–30 lowercase letters, numbers and single hyphens,
permanent, first come first served, reserved words and big brands blocked."""

import re
import secrets

from sqlalchemy import text
from sqlalchemy.orm import Session

PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$")

RESERVED = frozenset("""
studio hq admin administrator root api app apps www mail email smtp ftp cdn media static assets
images img files uploads download downloads preview previews login logout signin signup sign-in
sign-up register join account accounts settings billing pricing plans plan checkout pay payment
payments invoice invoices help support contact contact-us about about-us team teams careers jobs
blog journal news press legal terms privacy cookies refund refunds dmca accessibility security
status health docs developer developers dashboard home index search explore discover properties
property listings listing neighbourhoods neighborhoods report reports sitemap robots favicon
waitlist invite invites trial demo test staging dev beta new edit delete null undefined
scrollwalk scroll-walk yniidi official staff moderator owner system
compass kw kellerwilliams keller-williams exp exprealty remax re-max coldwell coldwellbanker
coldwell-banker century21 sothebys christies zillow redfin realtor realtors realtorcom trulia
rightmove zoopla onthemarket bayut propertyfinder dubizzle magicbricks 99acres housing nobroker
realestate domain berkshire berkshirehathaway douglaselliman elliman engelvoelkers savills knightfrank
""".split())

SUFFIXES = ("realty", "homes", "estates", "properties", "-realty", "-homes", "-estates", "group")


def normalize(raw: str) -> str:
    return raw.strip().lower()


def problem(name: str) -> str | None:
    """Why this name can't be used, or None. Availability is checked separately."""
    if len(name) < 3:
        return "too_short"
    if len(name) > 30:
        return "too_long"
    if not PATTERN.match(name) or "--" in name:
        return "invalid_characters"
    if name in RESERVED:
        return "reserved"
    return None


def taken(s: Session, names: list[str]) -> set[str]:
    rows = s.execute(text("SELECT * FROM usernames_taken(CAST(:n AS citext[]))"), {"n": names}).scalars()
    return {str(r).lower() for r in rows}


def _base(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)
    return base[:22].strip("-") or "agent"


def suggestions(s: Session, name: str, count: int = 3) -> list[str]:
    base = _base(name)
    candidates = [f"{base}{suffix}" for suffix in SUFFIXES]
    candidates += [f"{base}{secrets.randbelow(900) + 100}" for _ in range(6)]
    candidates = [c for c in dict.fromkeys(candidates) if problem(c) is None]
    unavailable = taken(s, candidates)
    picks = [c for c in candidates if c not in unavailable]
    # One numbered option keeps the list from looking like brand-only variants.
    numbered = [c for c in picks if c[-1].isdigit()][:1]
    named = [c for c in picks if not c[-1].isdigit()]
    return (named[: count - len(numbered)] + numbered)[:count]
