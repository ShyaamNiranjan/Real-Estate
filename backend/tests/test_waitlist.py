import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import tenant_session
from tests.auth_helpers import mails_to

W = "/api/v1/waitlist"


def test_join_once_answer_always_the_same(client, owner_engine):
    body = {"name": "Reza", "email": "reza@example.com", "instagram_handle": "@reza.homes", "market": "Dubai"}
    first = client.post(W, json=body)
    again = client.post(W, json={**body, "name": "Someone else"})
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json() == {"status": "joined"}
    assert len(mails_to("reza@example.com")) == 1
    with owner_engine.connect() as conn:
        row = conn.execute(text("SELECT name, instagram_handle, market FROM waitlist")).one()
    assert tuple(row) == ("Reza", "reza.homes", "Dubai")


def test_waitlist_validation_and_rate_limit(client):
    assert client.post(W, json={"name": "", "email": "a@example.com"}).status_code == 422
    assert client.post(W, json={"name": "A", "email": "a@example.com", "instagram_handle": "bad handle!"}).status_code == 422
    statuses = [client.post(W, json={"name": "A", "email": f"a{i}@example.com"}).status_code for i in range(11)]
    assert statuses[-1] == 429


def test_api_cannot_read_the_waitlist(client):
    client.post(W, json={"name": "Reza", "email": "reza@example.com"})
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session() as s:
            s.execute(text("SELECT email FROM waitlist")).all()
