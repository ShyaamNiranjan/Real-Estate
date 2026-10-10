"""Redeeming trial invites (docs/SCOPE.md 11): a personal link (`/trial#<token>`, tied to one
email) or a campaign code such as REZA30. One trial per person and per workspace, only before
ever paying. The trial itself (3 listings ever, each live 60 days) is enforced in listings."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from app.db import tenant_session
from app.deps import Auth, client_ip, in_workspace
from app.errors import ApiError, ErrorResponse
from app.ratelimit import Rule, enforce
from app.security import token_hash

router = APIRouter(
    prefix="/api/v1/trial",
    tags=["trial"],
    responses={k: {"model": ErrorResponse} for k in (400, 401, 403, 404, 409, 429)},
)

LOOKUP_IP = Rule("trial-lookup-ip", 30, 600)
REDEEM_USER = Rule("trial-redeem-user", 10, 3600)


class TrialIn(BaseModel):
    token: str | None = Field(default=None, max_length=100, description="From the personal link's #fragment.")
    code: str | None = Field(default=None, max_length=30, description="Campaign code, any case.")

    @model_validator(mode="after")
    def _one(self):
        if bool(self.token) == bool(self.code):
            raise ValueError("Send either the invite link token or a code.")
        return self


class TrialLookupOut(BaseModel):
    status: Literal["open", "expired", "used", "revoked"]
    kind: Literal["personal", "campaign"]
    email: str | None = Field(description="Personal invites: who it's for (sign up with this email).")
    listings_allowed: int
    expires_at: datetime


class TrialStarted(BaseModel):
    status: Literal["trialing"] = "trialing"
    listings_allowed: int


def _args(body: TrialIn) -> dict:
    return {"h": token_hash(body.token) if body.token else None, "c": body.code.strip() if body.code else None}


@router.post("/lookup", response_model=TrialLookupOut)
def lookup(body: TrialIn, request: Request) -> TrialLookupOut:
    """What the trial link or code offers, before signing up. No sign-in needed."""
    enforce((LOOKUP_IP, client_ip(request)))
    with tenant_session() as s:
        row = s.execute(text("SELECT * FROM trial_invite_lookup(:h, CAST(:c AS citext))"), _args(body)).first()
    if row is None:
        raise ApiError(404, "trial_not_found", "That invite link or code isn't valid.")
    return TrialLookupOut(status=row.status, kind=row.kind, email=row.email, listings_allowed=row.listings_allowed,
                          expires_at=row.expires_at)


_ERRORS = {
    "forbidden": ApiError(403, "admin_only", "Only the workspace Admin can start a trial."),
    "invalid": ApiError(400, "invalid_trial", "This invite has expired, been used up or withdrawn."),
    "email_mismatch": ApiError(403, "trial_email_mismatch", "This invite is for a different email address."),
    "already_trialed": ApiError(409, "already_trialed", "You've already had a Scrollwalk trial."),
    "not_eligible": ApiError(409, "trial_not_eligible", "Trials are for new accounts. Choose a plan instead."),
}


@router.post("/redeem", response_model=TrialStarted)
def redeem(body: TrialIn, auth: Auth = Depends(in_workspace)) -> TrialStarted:
    """Starts the trial in the signed-in Admin's workspace."""
    enforce((REDEEM_USER, str(auth.user_id)))
    with tenant_session(auth.user_id, auth.workspace_id) as s:
        row = s.execute(text("SELECT * FROM trial_redeem(:h, CAST(:c AS citext))"), _args(body)).one()
    if row.status != "trialing":
        raise _ERRORS[row.status]
    return TrialStarted(listings_allowed=row.listings_allowed)
