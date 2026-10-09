from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from app import email as mail
from app.db import tenant_session
from app.deps import client_ip
from app.errors import ErrorResponse
from app.ratelimit import Rule, enforce
from app.security import keyed

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"],
                   responses={k: {"model": ErrorResponse} for k in (422, 429)})

WAITLIST_IP = Rule("waitlist-ip", 10, 3600)


class WaitlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    instagram_handle: str = Field(default="", max_length=40, pattern=r"^@?[A-Za-z0-9._]{0,30}$")
    market: str = Field(default="", max_length=80)


class Joined(BaseModel):
    status: Literal["joined"] = "joined"


@router.post("", status_code=202, response_model=Joined)
def join_waitlist(body: WaitlistIn, request: Request) -> Joined:
    """Always answers the same way, so the list can't be probed for who's on it."""
    enforce((WAITLIST_IP, client_ip(request)))
    with tenant_session() as s:
        added = s.execute(
            text("SELECT waitlist_join(:n, :e, :i, :m, :ip)"),
            {"n": body.name.strip(), "e": body.email, "i": body.instagram_handle.lstrip("@"),
             "m": body.market.strip(), "ip": keyed("ip", client_ip(request))},
        ).scalar_one()
    if added:
        mail.send(mail.Email(
            to=body.email,
            subject="You're on the Scrollwalk waitlist",
            text=f"Thanks, {body.name.strip()}. You're on the list. We're opening Scrollwalk to a small group of "
                 "agents first, and we'll email you as soon as your invite is ready.",
        ))
    return Joined()
