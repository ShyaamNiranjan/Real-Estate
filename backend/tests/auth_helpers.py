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


def set_workspace(owner_engine, workspace_id: str, **columns) -> None:
    from sqlalchemy import text

    assignments = ", ".join(f"{k} = :{k}" for k in columns)
    with owner_engine.begin() as conn:
        conn.execute(text(f"UPDATE workspaces SET {assignments} WHERE id = :w"), {**columns, "w": workspace_id})


def add_member(owner_engine, workspace_id: str, user_id: str, role_id: str | None = None) -> None:
    """Puts an existing user into a workspace and switches their sessions to it."""
    from sqlalchemy import text

    with owner_engine.begin() as conn:
        conn.execute(text("INSERT INTO memberships (workspace_id, user_id, role_id) VALUES (:w, :u, :r)"),
                     {"w": workspace_id, "u": user_id, "r": role_id})
        conn.execute(text("UPDATE sessions SET workspace_id = :w WHERE user_id = :u"),
                     {"w": workspace_id, "u": user_id})


def sign_up(client, address: str, password: str = PASSWORD, name: str = "") -> dict:
    r = client.post("/api/v1/auth/signup", json={
        "email": address, "password": password, "display_name": name, "accept_terms": True,
    })
    assert r.status_code == 202, r.text
    r = client.post("/api/v1/auth/verify", json={"email": address, "code": last_code(address)})
    assert r.status_code == 200, r.text
    return r.json()
