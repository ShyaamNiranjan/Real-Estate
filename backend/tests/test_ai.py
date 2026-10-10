import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.ai_client import TextTap
from tests.auth_helpers import csrf, sign_up
from tests.test_listings import L, _member, admin, edit, new_listing  # noqa: F401

SUMMARY = (
    "Four bedroom villa on a quiet street above the river, renovated last year with a new kitchen, oak floors "
    "and a south facing garden with a pool. The primary suite opens onto a terrace. Two garages and a home "
    "office over the garden. Call me on +1 (415) 555-0134 or write to ana@example.com, photos at "
    "https://example.com/villa. Built in 1998."
)

GOOD = {
    "hero_line": "A renovated villa above the river",
    "story": {"heading": "Light and calm", "body": "Renovated last year, with oak floors throughout."},
    "spaces": [{"name": "Kitchen", "description": "New, opening to the garden."}],
    "location": {"heading": "Above the river", "body": "A quiet street.", "highlights": ["Quiet street"]},
    "faq": [{"question": "How many bedrooms?", "answer": "Four."}],
    "captions": [{"label": "Arrival", "text": "Through the gate."}] * 6,
    "seo_title": "Four-bedroom villa above the river",
    "seo_description": "Renovated four-bedroom villa with garden and pool.",
    "photo_alt": [],
}


def events(r):
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    out = []
    for block in r.text.strip().split("\n\n"):
        name_line, data_line = block.split("\n")
        out.append((name_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))))
    return out


def ready_listing(c, **fields):
    listing = new_listing(c, "Villa Aurelia", experience_type="immersive")
    r = edit(c, listing["id"], summary=SUMMARY, bedrooms=4, bathrooms=3, property_type="Villa",
             location="Lisbon", price_amount=2450000, **fields)
    assert r.status_code == 200, r.text
    return r.json()


def generate(c, listing_id, **body):
    return c.post(f"{L}/{listing_id}/ai/generate", json=body, headers=csrf(c))


def section(listing, kind):
    return next(s for s in listing["sections"] if s["type"] == kind)


def fake_provider(monkeypatch, *replies, seen=None):
    queue = list(replies)

    def stream_chat(system, user, usage, stub):
        if seen is not None:
            seen.append((system, user))
        usage.input_tokens, usage.output_tokens = 1000, 500
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        reply = reply if isinstance(reply, str) else json.dumps(reply)
        for i in range(0, len(reply), 7):
            yield reply[i:i + 7]

    monkeypatch.setattr("app.ai.stream_chat", stream_chat)


def generations(owner_engine):
    with owner_engine.begin() as conn:
        return conn.execute(text("SELECT kind, status, attempts, provider, input_tokens FROM ai_generations")).all()


def test_generate_streams_text_then_fills_the_page(admin, owner_engine):
    c = admin["client"]
    listing = ready_listing(c)
    got = events(generate(c, listing["id"], tone="warm"))
    names = [n for n, _ in got]
    assert names[0] == "stage" and got[0][1] == {"stage": "writing"}
    assert "text" in names and ("stage", {"stage": "building"}) in got and names[-1] == "done"
    streamed = "".join(d["text"] for n, d in got if n == "text")
    assert "Four bedroom villa" in streamed and "{" not in streamed

    done = got[-1][1]
    assert done["fallback"] is False and done["message"] is None
    page = done["listing"]
    assert page["subtitle"] == "4-bedroom villa in Lisbon"
    assert section(page, "story")["ai_drafted"] is True
    assert len(page["beats"]) == 6 and page["beats"][0]["label"] == "Arrival"
    assert any(b["code"] == "placeholders" for b in page["publish_blockers"])
    assert [g[:4] for g in generations(owner_engine)] == [("full", "ok", 1, "stub")]


def test_only_scrubbed_listing_text_reaches_the_provider(admin, monkeypatch):
    c = admin["client"]
    listing = ready_listing(c)
    seen: list = []
    fake_provider(monkeypatch, GOOD, seen=seen)
    events(generate(c, listing["id"]))
    system, user = seen[0]
    sent = json.loads(user)
    assert set(sent) <= {"title", "property_type", "location", "price", "bedrooms", "bathrooms", "area",
                         "presentation", "summary", "photo_labels"}
    for secret in ("ana@example.com", "555-0134", "example.com/villa", "Ana Silva", "Silva Realty", "admin@example.com"):
        assert secret not in user and secret not in system
    assert "[removed]" in sent["summary"] and "Built in 1998" in sent["summary"]
    assert sent["price"] == "USD 2,450,000" and sent["bedrooms"] == 4
    assert "exactly 6 captions" in system and "American English" in system


def test_provider_text_is_applied(admin, monkeypatch, owner_engine):
    c = admin["client"]
    listing = ready_listing(c)
    fake_provider(monkeypatch, GOOD)
    page = events(generate(c, listing["id"]))[-1][1]["listing"]
    assert page["subtitle"] == GOOD["hero_line"] and page["seo_title"] == GOOD["seo_title"]
    assert section(page, "story")["content"] == GOOD["story"]
    assert section(page, "spaces")["content"]["items"] == GOOD["spaces"]
    assert section(page, "faq")["content"]["items"] == GOOD["faq"]
    assert section(page, "spaces")["content"]["heading"] == "The spaces", "keeps the designed heading"
    assert not any(b["code"] == "placeholders" for b in page["publish_blockers"])
    assert generations(owner_engine)[0][:3] == ("full", "ok", 1)


def test_bad_replies_retry_once_then_fall_back_to_the_template(admin, monkeypatch, owner_engine):
    c = admin["client"]
    listing = ready_listing(c)
    fake_provider(monkeypatch, "Sorry, I can't help with that.")
    got = events(generate(c, listing["id"]))
    assert ("stage", {"stage": "retrying"}) in got
    done = got[-1][1]
    assert done["fallback"] is True and done["message"] == "We've started your page; you can refine it below."
    assert section(done["listing"], "story")["content"]["body"] == SUMMARY, "the template uses the agent's own text"
    assert generations(owner_engine)[0][:3] == ("full", "fallback", 2)


def test_fair_housing_phrases_are_rejected(admin, monkeypatch):
    c = admin["client"]
    listing = ready_listing(c)
    bad = {**GOOD, "story": {"heading": "Home", "body": "Perfect for families who love the outdoors."}}
    fake_provider(monkeypatch, bad, GOOD)
    got = events(generate(c, listing["id"]))
    assert ("stage", {"stage": "retrying"}) in got
    assert got[-1][1]["fallback"] is False
    assert section(got[-1][1]["listing"], "story")["content"] == GOOD["story"]


def test_summary_needs_enough_words(admin):
    c = admin["client"]
    listing = new_listing(c)
    edit(c, listing["id"], summary="A lovely home with a garden.")
    r = generate(c, listing["id"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "summary_too_short"


def test_regenerating_warns_before_replacing_the_agents_own_text(admin, monkeypatch):
    c = admin["client"]
    listing = ready_listing(c)
    fake_provider(monkeypatch, GOOD)
    events(generate(c, listing["id"]))
    assert events(generate(c, listing["id"]))[-1][0] == "done", "untouched AI text is replaced without asking"

    story = section(c.get(f"{L}/{listing['id']}").json(), "story")
    r = c.patch(f"{L}/{listing['id']}/sections/{story['id']}",
                json={"content": {"heading": "Mine", "body": "My own words."}}, headers=csrf(c))
    assert section(r.json(), "story")["ai_drafted"] is False
    r = generate(c, listing["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirm_replace"
    assert events(generate(c, listing["id"], replace_edits=True))[-1][0] == "done"


def test_daily_limit_per_listing(admin, owner_engine):
    c = admin["client"]
    listing = ready_listing(c)
    with owner_engine.begin() as conn:
        for _ in range(10):
            conn.execute(text("""INSERT INTO ai_generations (id, workspace_id, listing_id, user_id, kind, provider,
                                                             model, prompt_version, status)
                                 VALUES (:id, :w, :l, :u, 'full', 'stub', 'template', 'listing-v1', 'ok')"""),
                         {"id": uuid4(), "w": admin["workspace_id"], "l": listing["id"], "u": admin["user_id"]})
    r = generate(c, listing["id"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_limit"


def test_only_editors_of_the_listing_can_generate(admin, make_client, owner_engine):
    c = admin["client"]
    listing = ready_listing(c)
    agent, _ = _member(make_client, owner_engine, admin, ["listings.create", "listings.edit_own"])
    assert generate(agent, listing["id"]).status_code == 403

    outsider = make_client()
    sign_up(outsider, "outsider@example.com")
    assert generate(outsider, listing["id"]).status_code == 404


def test_rewrite_returns_a_proposal_without_saving(admin, monkeypatch, owner_engine):
    c = admin["client"]
    listing = ready_listing(c)
    long_story = {**GOOD, "story": {"heading": "Light", "body": "One sentence here. Two sentences here. "
                                    "Three sentences here. Four sentences here, to make it long enough."}}
    fake_provider(monkeypatch, long_story)
    page = events(generate(c, listing["id"]))[-1][1]["listing"]
    story = section(page, "story")
    monkeypatch.undo()

    r = c.post(f"{L}/{listing['id']}/ai/rewrite", json={"section_id": story["id"], "style": "shorter"}, headers=csrf(c))
    assert r.status_code == 200, r.text
    assert len(r.json()["content"]["body"]) < len(story["content"]["body"])
    assert section(c.get(f"{L}/{listing['id']}").json(), "story")["content"] == story["content"]

    glance = section(page, "at_a_glance")
    r = c.post(f"{L}/{listing['id']}/ai/rewrite", json={"section_id": glance["id"], "style": "factual"}, headers=csrf(c))
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_rewritable"
    cta = section(page, "cta")
    c.patch(f"{L}/{listing['id']}/sections/{cta['id']}", json={"content": {"heading": "Visit"}}, headers=csrf(c))
    r = c.post(f"{L}/{listing['id']}/ai/rewrite", json={"section_id": cta["id"], "style": "factual"}, headers=csrf(c))
    assert r.status_code == 422 and r.json()["error"]["code"] == "nothing_to_rewrite"

    fake_provider(monkeypatch, {"heading": "x", "body": "Ideal for couples."})
    r = c.post(f"{L}/{listing['id']}/ai/rewrite", json={"section_id": story["id"], "style": "luxurious"}, headers=csrf(c))
    assert r.status_code == 502 and r.json()["error"]["code"] == "ai_unavailable"
    kinds = [g[:2] for g in generations(owner_engine)]
    assert ("rewrite_section", "ok") in kinds and ("rewrite_section", "failed") in kinds


def test_preview_and_snapshot_carry_no_ai_markers(admin, monkeypatch):
    c = admin["client"]
    listing = ready_listing(c)
    fake_provider(monkeypatch, GOOD)
    events(generate(c, listing["id"]))
    content = c.get(f"{L}/{listing['id']}/preview").json()["content"]
    assert all("ai_drafted" not in s for s in content["sections"])


def test_text_tap_shows_only_values_even_when_split_mid_escape():
    reply = json.dumps({"hero_line": "Café \"Sol\"", "story": {"heading": "A", "body": "Line one\nLine two"},
                        "faq": [{"question": "Q?", "answer": "A."}]}, ensure_ascii=True)
    tap = TextTap()
    shown = "".join(tap.feed(reply[i:i + 3]) for i in range(0, len(reply), 3))
    assert shown == 'Café "Sol"\nA\nLine one\nLine two\nQ?\nA.\n'
    assert "hero_line" not in shown


def test_openai_compatible_client_streams_and_reports_usage(monkeypatch):
    import httpx

    from app import ai_client
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "ai_api_key", "test-key-123")
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.example/v1/")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        chunks = [{"choices": [{"delta": {"content": '{"a":'}}]}, {"choices": [{"delta": {"content": '"b"}'}}]},
                  {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}}]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    monkeypatch.setattr(ai_client.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    usage = ai_client.Usage()
    reply = "".join(ai_client.stream_chat("system", "user", usage, stub=lambda: "unused"))
    assert reply == '{"a":"b"}' and (usage.input_tokens, usage.output_tokens) == (12, 3)
    assert seen["url"] == "https://ai.example/v1/chat/completions" and seen["auth"] == "Bearer test-key-123"
    assert seen["body"]["messages"] == [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}]
    assert "test-key-123" not in json.dumps(seen["body"])

    monkeypatch.setattr(ai_client.httpx, "Client", lambda **kw: real_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(429)), **kw))
    with pytest.raises(ai_client.AiError):
        list(ai_client.stream_chat("system", "user", ai_client.Usage(), stub=lambda: "unused"))


def test_cost_is_metered(monkeypatch, admin, owner_engine):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_input_usd_per_million", 2.0)
    monkeypatch.setattr(settings, "ai_output_usd_per_million", 8.0)
    c = admin["client"]
    listing = ready_listing(c)
    fake_provider(monkeypatch, GOOD)
    events(generate(c, listing["id"]))
    with owner_engine.begin() as conn:
        cost = conn.execute(text("SELECT cost_usd FROM ai_generations")).scalar_one()
    assert float(cost) == pytest.approx((1000 * 2 + 500 * 8) / 1_000_000)
