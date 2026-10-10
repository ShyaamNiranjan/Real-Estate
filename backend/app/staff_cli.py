"""Creates or recovers the Super-Admin from the server's command line (there is no sign-up for staff).

    python -m app.staff_cli create-super founder@example.com "Founder Name"
    python -m app.staff_cli reset-super          # lost phone or password: new setup link

Prints a setup link (also emailed) where the password and two-factor are chosen. Nothing secret
is typed here.
"""

import sys

from sqlalchemy import text

from app import email as mail
from app.db import hq_session
from app.staff import setup_email, issue_setup_link


def create_super(email: str, name: str = "") -> str:
    with hq_session() as s:
        if s.execute(text("SELECT 1 FROM staff WHERE is_super")).first():
            raise SystemExit("A Super-Admin already exists. Use reset-super to recover access.")
        staff_id = s.execute(text("INSERT INTO staff (email, display_name, is_super) VALUES (:e, :n, true) RETURNING id"),
                             {"e": email.strip().lower(), "n": name.strip()}).scalar_one()
        link = issue_setup_link(s, staff_id)
        s.execute(text("""INSERT INTO audit_log (staff_id, staff_email, action) VALUES (:id, :e, 'staff.super_created')"""),
                  {"id": staff_id, "e": email.strip().lower()})
    mail.send(setup_email(email, link))
    return link


def reset_super() -> str:
    with hq_session() as s:
        row = s.execute(text("SELECT id, email FROM staff WHERE is_super")).first()
        if row is None:
            raise SystemExit("No Super-Admin yet. Use create-super.")
        link = issue_setup_link(s, row.id)
        s.execute(text("""INSERT INTO audit_log (staff_id, staff_email, action) VALUES (:id, :e, 'staff.super_reset')"""),
                  {"id": row.id, "e": row.email})
    mail.send(setup_email(row.email, link))
    return link


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["create-super"] and len(args) in (2, 3):
        link = create_super(args[1], args[2] if len(args) == 3 else "")
    elif args == ["reset-super"]:
        link = reset_super()
    else:
        raise SystemExit(__doc__)
    print(f"\nSetup link (valid 72 hours):\n{link}\n")


if __name__ == "__main__":
    main()
