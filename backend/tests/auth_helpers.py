import re

from app import email

PASSWORD = "correct horse battery"


def last_code(to: str) -> str:
    for message in reversed(email.outbox):
        if message.to.lower() == to.lower():
            match = re.search(r"\b(\d{6})\b", message.text)
            if match:
                return match.group(1)
    raise AssertionError(f"no code emailed to {to}")


def mails_to(to: str) -> list[email.Email]:
    return [m for m in email.outbox if m.to.lower() == to.lower()]


def csrf(client) -> dict:
    token = client.cookies.get("__Host-sw_csrf")
    return {"X-CSRF-Token": token or ""}


def sign_up(client, address: str, password: str = PASSWORD, name: str = "") -> dict:
    r = client.post("/api/v1/auth/signup", json={
        "email": address, "password": password, "display_name": name, "accept_terms": True,
    })
    assert r.status_code == 202, r.text
    r = client.post("/api/v1/auth/verify", json={"email": address, "code": last_code(address)})
    assert r.status_code == 200, r.text
    return r.json()
