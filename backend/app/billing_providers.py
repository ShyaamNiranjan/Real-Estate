"""Merchant-of-record adapters. Everything provider-specific stays here; the rest of the app only
sees normalised BillingEvents. A real provider (Paddle, Lemon Squeezy, Dodo, ...) is one more class
implementing the same methods once it's chosen."""

import base64
import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.config import get_settings
from app.security import keyed, same


class WebhookError(Exception):
    pass


@dataclass(frozen=True)
class BillingEvent:
    event_id: str
    type: str
    occurred_at: datetime
    workspace_id: UUID
    subscription_id: str
    customer_id: str
    plan_key: str
    interval: str  # month | year
    status: str  # active | past_due | canceled | expired
    current_period_end: datetime | None
    cancel_at_period_end: bool
    # A money movement that came with the event: {id, kind: charge|refund|failed, amount?, fee?, tax?, currency?}.
    # Amounts are decimal strings; a missing amount means the plan's list price.
    payment: dict | None = None

    def payload(self) -> dict:
        data = asdict(self)
        for key in ("occurred_at", "current_period_end"):
            data[key] = data[key].isoformat() if data[key] else None
        data["workspace_id"] = str(self.workspace_id)
        return data

    @classmethod
    def from_payload(cls, data: dict) -> "BillingEvent":
        return cls(**{
            **data,
            "workspace_id": UUID(data["workspace_id"]),
            "occurred_at": datetime.fromisoformat(data["occurred_at"]),
            "current_period_end": datetime.fromisoformat(data["current_period_end"]) if data["current_period_end"] else None,
        })


@dataclass(frozen=True)
class SubscriptionRef:
    workspace_id: UUID
    subscription_id: str
    customer_id: str
    plan_key: str
    interval: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


def _period(interval: str) -> timedelta:
    return timedelta(days=365 if interval == "year" else 30)


class StubProvider:
    """Simulates a merchant of record for development and tests. Checkout and portal pages are
    Studio pages; plan changes take effect at once by returning the event the provider would send."""

    name = "stub"

    def _sign(self, payload: dict, purpose: str) -> str:
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        return f"{body}.{keyed(purpose, body)[:40]}"

    def _verify(self, token: str, purpose: str) -> dict | None:
        try:
            body, mac = token.rsplit(".", 1)
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if not same(mac, keyed(purpose, body)[:40]) or payload.get("exp", 0) < time.time():
            return None
        return payload

    def checkout_url(self, workspace_id: UUID, plan_key: str, interval: str, email: str, price_id: str | None) -> str:
        token = self._sign({"w": str(workspace_id), "p": plan_key, "i": interval, "exp": int(time.time()) + 3600},
                           "stub-checkout")
        return f"{get_settings().app_url}/studio/billing/checkout#{token}"

    def checkout_completed(self, token: str) -> BillingEvent | None:
        data = self._verify(token, "stub-checkout")
        if data is None:
            return None
        now = datetime.now(UTC)
        return BillingEvent(
            event_id=f"stub_evt_{uuid4().hex}", type="subscription.created", occurred_at=now,
            workspace_id=UUID(data["w"]), subscription_id=f"stub_sub_{uuid4().hex[:16]}",
            customer_id=f"stub_cus_{data['w'][:8]}", plan_key=data["p"], interval=data["i"], status="active",
            current_period_end=now + _period(data["i"]), cancel_at_period_end=False,
            payment={"id": f"stub_pay_{uuid4().hex[:16]}", "kind": "charge"},
        )

    def portal_url(self, customer_id: str) -> str:
        return f"{get_settings().app_url}/studio/billing?portal=stub"

    def _event(self, sub: SubscriptionRef, type_: str, **changes) -> BillingEvent:
        base = BillingEvent(
            event_id=f"stub_evt_{uuid4().hex}", type=type_, occurred_at=datetime.now(UTC),
            workspace_id=sub.workspace_id, subscription_id=sub.subscription_id, customer_id=sub.customer_id,
            plan_key=sub.plan_key, interval=sub.interval, status=sub.status,
            current_period_end=sub.current_period_end, cancel_at_period_end=sub.cancel_at_period_end,
        )
        return replace(base, **changes)

    def change_plan(self, sub: SubscriptionRef, plan_key: str, interval: str, price_id: str | None) -> BillingEvent | None:
        return self._event(sub, "subscription.updated", plan_key=plan_key, interval=interval)

    def cancel(self, sub: SubscriptionRef) -> BillingEvent | None:
        return self._event(sub, "subscription.updated", cancel_at_period_end=True)

    def resume(self, sub: SubscriptionRef) -> BillingEvent | None:
        return self._event(sub, "subscription.updated", cancel_at_period_end=False)

    def simulate(self, sub: SubscriptionRef, what: str) -> BillingEvent:
        if what == "renew":
            end = (sub.current_period_end or datetime.now(UTC)) + _period(sub.interval)
            return self._event(sub, "subscription.renewed", status="active", current_period_end=end,
                               payment={"id": f"stub_pay_{uuid4().hex[:16]}", "kind": "charge"})
        if what == "payment_failed":
            return self._event(sub, "subscription.past_due", status="past_due",
                               payment={"id": f"stub_pay_{uuid4().hex[:16]}", "kind": "failed"})
        return self._event(sub, "subscription.expired", status="expired", cancel_at_period_end=False)

    def refund(self, sub: SubscriptionRef, payment_id: str, amount: str) -> BillingEvent:
        """Refunds one charge in full. The subscription itself is unchanged."""
        return self._event(sub, "payment.refunded", payment={"id": payment_id, "kind": "refund", "amount": amount})

    def sign_webhook(self, body: bytes) -> str:
        return keyed("stub-webhook", body.decode())

    def parse_webhook(self, body: bytes, headers) -> BillingEvent:
        signature = headers.get("x-stub-signature", "")
        if not signature or not same(signature, self.sign_webhook(body)):
            raise WebhookError("bad signature")
        try:
            return BillingEvent.from_payload(json.loads(body))
        except (ValueError, KeyError, TypeError):
            raise WebhookError("malformed event") from None


def get_provider() -> StubProvider:
    settings = get_settings()
    if settings.billing_provider == "stub":
        if settings.environment == "production":
            raise RuntimeError("The billing stub must not run in production. Configure a merchant of record.")
        return StubProvider()
    raise RuntimeError(f"Unknown billing provider {settings.billing_provider}")
