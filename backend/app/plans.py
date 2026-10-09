"""Plan limits. Placeholders until pricing is decided; they move to the plans table (editable in
Super-Admin) with the billing slice."""

LISTING_LIMITS: dict[str, int | None] = {"agent": 15, "team": 50, "brokerage": None}
FREE_PREVIEW_LISTINGS = 1
TRIAL_LISTINGS_DEFAULT = 3
TRIAL_LIVE_DAYS = 60

# subscription_state values: none (free preview), trialing, active, grace, offline
PUBLISH_STATES = frozenset({"trialing", "active", "grace"})
READ_ONLY_STATES = frozenset({"offline"})
