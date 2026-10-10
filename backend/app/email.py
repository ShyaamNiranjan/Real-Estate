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


def invitation_email(to: str, inviter: str, team: str, role: str, link: str) -> Email:
    return Email(
        to=to,
        subject=f"{inviter} invited you to join {team} on Scrollwalk",
        text=f"{inviter} invited you to join {team} on Scrollwalk as {role}.\n\n"
        f"Accept the invitation:\n{link}\n\n"
        "The link works for 7 days. If you weren't expecting this, you can ignore this email.",
    )


def member_joined_notice(to: str, member: str, team: str) -> Email:
    return Email(
        to=to,
        subject=f"{member} joined {team} on Scrollwalk",
        text=f"{member} accepted your invitation and is now on your team.",
    )


def lifecycle_email(to: str, notice: str, app_url: str, **ctx) -> Email:
    """Account lifecycle reminders (docs/SCOPE.md 11). `notice` is the stored notice key's kind."""
    billing, export = f"{app_url}/studio/billing", f"{app_url}/studio/settings/export"
    copy = {
        "grace_start": ("Your Scrollwalk subscription has ended",
                        f"Your site and listings stay live for 30 more days, until {ctx.get('date')}, and enquiries "
                        f"keep arriving. You can't create new listings until you resubscribe.\n\nResubscribe: {billing}"),
        "grace_7": ("Your site goes offline in 7 days",
                    f"On {ctx.get('date')} your site and listings will show a \"temporarily unavailable\" page. "
                    f"Resubscribe to keep them live: {billing}"),
        "grace_1": ("Your site goes offline tomorrow",
                    f"Tomorrow your site and listings will show a \"temporarily unavailable\" page. "
                    f"Resubscribe to keep them live: {billing}"),
        "offline": ("Your site is offline",
                    f"Your site and listings now show a \"temporarily unavailable\" page and the Studio is read-only. "
                    f"Everything is kept until {ctx.get('date')}. Resubscribe any time before then and it all comes "
                    f"back exactly as it was: {billing}\n\nDownload everything: {export}"),
        "delete_30": ("Your Scrollwalk account will be deleted in 30 days",
                      f"On {ctx.get('date')} your listings, videos, photos and enquiries will be permanently deleted. "
                      f"Resubscribe to keep them ({billing}) or download everything first ({export})."),
        "delete_7": ("Your Scrollwalk account will be deleted in 7 days",
                     f"On {ctx.get('date')} everything will be permanently deleted. "
                     f"Resubscribe ({billing}) or download everything ({export})."),
        "trial_7": (f"\"{ctx.get('title')}\" goes offline in 7 days",
                    f"Your trial listing stays live until {ctx.get('date')}. Subscribe to keep it live at the same "
                    f"address: {billing}"),
        "trial_1": (f"\"{ctx.get('title')}\" goes offline tomorrow",
                    f"Your trial listing goes offline tomorrow. Subscribe to keep it live at the same address: {billing}"),
        "renewal": ("Your annual Scrollwalk plan renews soon",
                    f"Your plan renews automatically on {ctx.get('date')}. To change or cancel it, go to {billing}."),
        "export_ready": ("Your Scrollwalk download is ready",
                         f"Your listings, videos, photos and enquiries are ready to download for 7 days: {export}"),
    }
    subject, body = copy[notice]
    return Email(to=to, subject=subject, text=body)


def email_changed_notice(to: str, new_email: str) -> Email:
    return Email(
        to=to,
        subject="Your Scrollwalk email was changed",
        text=f"Your account email was changed to {new_email}. If this wasn't you, reply to this email right away.",
    )
