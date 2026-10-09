from dataclasses import dataclass

from sqlalchemy import text

from app.db import tenant_session
from app.errors import ApiError
from app.security import keyed


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window_seconds: int


def enforce(*checks: tuple[Rule, str]) -> None:
    """Counts one hit against every (rule, subject) pair; refuses if any is over its limit."""
    allowed = True
    with tenant_session() as s:
        for rule, subject in checks:
            key = f"{rule.name}:{keyed('rate-limit', subject.lower())}"
            ok = s.execute(
                text("SELECT rate_limit_hit(:key, :window, :limit)"),
                {"key": key, "window": rule.window_seconds, "limit": rule.limit},
            ).scalar_one()
            allowed = allowed and ok
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many attempts. Please wait a few minutes and try again.")
