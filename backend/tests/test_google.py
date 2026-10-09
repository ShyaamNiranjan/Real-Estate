import time
from urllib.parse import parse_qs, urlparse

import pytest

from app import google
from app.config import get_settings
from tests.auth_helpers import PASSWORD

API = "/api/v1/auth"


@pytest.fixture(autouse=True)
def google_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "client-123")
    monkeypatch.setattr(settings, "google_client_secret", "secret-456")


def run_flow(client, monkeypatch, claims: dict, *, tamper_state: bool = False):
    r = client.get(f"{API}/google/start", follow_redirects=False)
    assert r.status_code == 303
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["client_id"] == ["client-123"]
    state, nonce = query["state"][0], query["nonce"][0]

    base = {"iss": "https://accounts.google.com", "aud": "client-123", "exp": time.time() + 300,
            "nonce": nonce, "email_verified": True}
    monkeypatch.setattr(google, "exchange_code", lambda code, verifier: {**base, **claims})
    return client.get(f"{API}/google/callback",
                      params={"code": "auth-code", "state": "forged" if tamper_state else state},
                      follow_redirects=False)


def test_new_google_user_is_signed_in(client, monkeypatch):
    r = run_flow(client, monkeypatch, {"sub": "g-1", "email": "g@example.com", "name": "Gia"})
    assert r.status_code == 303 and r.headers["location"].endswith("/studio")
    me = client.get(f"{API}/me").json()
    assert me["user"]["email"] == "g@example.com" and me["user"]["email_verified"] is True
    assert me["user"]["has_password"] is False and len(me["workspaces"]) == 1


def test_returning_google_user_gets_same_account(client, make_client, monkeypatch):
    run_flow(client, monkeypatch, {"sub": "g-1", "email": "g@example.com"})
    first = client.get(f"{API}/me").json()["user"]["id"]
    again = make_client()
    run_flow(again, monkeypatch, {"sub": "g-1", "email": "g@example.com"})
    assert again.get(f"{API}/me").json()["user"]["id"] == first


def test_forged_state_is_refused(client, monkeypatch):
    r = run_flow(client, monkeypatch, {"sub": "g-1", "email": "g@example.com"}, tamper_state=True)
    assert "error=google_failed" in r.headers["location"]
    assert client.get(f"{API}/me").status_code == 401


def test_replayed_nonce_is_refused(client, monkeypatch):
    r = run_flow(client, monkeypatch, {"sub": "g-1", "email": "g@example.com", "nonce": "old-nonce"})
    assert "error=google_failed" in r.headers["location"]


def test_unverified_google_email_is_refused(client, monkeypatch):
    r = run_flow(client, monkeypatch, {"sub": "g-1", "email": "g@example.com", "email_verified": False})
    assert "error=google_failed" in r.headers["location"]


def test_token_for_another_app_is_refused(client, monkeypatch):
    r = run_flow(client, monkeypatch, {"sub": "g-1", "email": "g@example.com", "aud": "someone-else"})
    assert "error=google_failed" in r.headers["location"]


def test_google_takes_over_unverified_squatter_account(client, make_client, monkeypatch):
    squatter = make_client()
    squatter.post(f"{API}/signup", json={"email": "v@example.com", "password": "squatter-pass", "accept_terms": True})
    run_flow(client, monkeypatch, {"sub": "g-9", "email": "v@example.com"})
    assert client.get(f"{API}/me").json()["user"]["has_password"] is False
    r = squatter.post(f"{API}/login", json={"email": "v@example.com", "password": "squatter-pass"})
    assert r.status_code == 401


def test_google_links_to_verified_password_account(client, make_client, monkeypatch):
    from tests.auth_helpers import sign_up

    owner = sign_up(make_client(), "p@example.com")
    run_flow(client, monkeypatch, {"sub": "g-5", "email": "p@example.com"})
    me = client.get(f"{API}/me").json()
    assert me["user"]["id"] == owner["user"]["id"] and me["user"]["has_password"] is True
    assert make_client().post(f"{API}/login", json={"email": "p@example.com", "password": PASSWORD}).status_code == 200


def test_google_unconfigured_redirects_with_message(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", None)
    r = client.get(f"{API}/google/start", follow_redirects=False)
    assert "error=google_unavailable" in r.headers["location"]
