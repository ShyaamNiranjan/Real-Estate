"""Plan limits and lifecycle constants. Seats and listing limits live in the `plans` table
(editable in Super-Admin); these are the fixed rules around them."""

from datetime import timedelta

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

FREE_PREVIEW_LISTINGS = 1
TRIAL_LISTINGS_DEFAULT = 3
TRIAL_LIVE_DAYS = 60
TRIAL_VIDEO_MAX_BYTES = 500 * 1024 * 1024

GRACE = timedelta(days=30)
DELETE_AFTER = timedelta(days=182)
USERNAME_HOLD = timedelta(days=60)

# subscription_state values: none (free preview), trialing, active, grace, offline
PUBLISH_STATES = frozenset({"trialing", "active", "grace"})
READ_ONLY_STATES = frozenset({"offline"})
TEAM_PLANS = frozenset({"team", "brokerage"})


def plan(s: Session, key: str | None) -> Row | None:
    if not key:
        return None
    return s.execute(text("SELECT * FROM plans WHERE key = :k"), {"k": key}).first()


def seats(s: Session, key: str | None) -> int:
    row = plan(s, key)
    return row.seats if row else 1


def listing_limit(s: Session, key: str | None) -> int | None:
    """None means unlimited; no plan means none allowed."""
    row = plan(s, key)
    return row.listing_limit if row else 0
