"""Outgoing email. Until Resend is connected, messages are logged and kept in `outbox`."""

import logging
from dataclasses import dataclass

log = logging.getLogger("scrollwalk.email")


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    reply_to: str | None = None


outbox: list[Email] = []


def send(*emails: Email) -> None:
    for email in emails:
        outbox.append(email)
        log.warning("EMAIL to=%s subject=%r\n%s", email.to, email.subject, email.text)


_CODE_COPY = {
    "verify": ("Your Scrollwalk code: {code}", "Enter this code to confirm your email"),
    "reset": ("Reset your Scrollwalk password: {code}", "Enter this code to choose a new password"),
    "email_change": ("Confirm your new email: {code}", "Enter this code to confirm your new email address"),
}


def code_email(to: str, purpose: str, code: str) -> Email:
    subject, lead = _CODE_COPY[purpose]
    return Email(
        to=to,
        subject=subject.format(code=code),
        text=f"{lead}:\n\n    {code}\n\nIt expires in 10 minutes. If you didn't ask for this, you can ignore this email.",
    )


def existing_account_email(to: str) -> Email:
    return Email(
        to=to,
        subject="You already have a Scrollwalk account",
        text="Someone (hopefully you) tried to sign up with this email. You already have an account, "
        "so just sign in. Forgot your password? Use \"Forgot password\" on the sign-in page.",
    )


def email_changed_notice(to: str, new_email: str) -> Email:
    return Email(
        to=to,
        subject="Your Scrollwalk email was changed",
        text=f"Your account email was changed to {new_email}. If this wasn't you, reply to this email right away.",
    )
