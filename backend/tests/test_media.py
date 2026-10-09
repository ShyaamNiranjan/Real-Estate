import io
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import email, worker
from app.db import tenant_session
from tests.auth_helpers import csrf, sign_up
from tests.test_listings import admin, make_ready, new_listing, publish  # noqa: F401

M = "/api/v1/media"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def jpeg(size=(1600, 1000), gps=True) -> bytes:
    image = Image.new("RGB", size, (180, 140, 90))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    if gps:
        exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


def upload(c, listing_id, kind, data, content_type="image/jpeg", name="photo.jpg", aspect=None, announced=None):
    r = c.post(f"{M}/uploads", headers=csrf(c), json={
        "listing_id": listing_id, "kind": kind, "filename": name, "content_type": content_type,
        "size": announced or len(data), **({"aspect": aspect} if aspect else {})})
    assert r.status_code == 201, r.text
    target = r.json()["upload"]
    put = c.put(target["url"], content=data, headers={"Content-Type": target["headers"]["Content-Type"]})
    return r.json()["media"], put


def add_image(c, listing_id, kind="gallery", data=None):
    media, put = upload(c, listing_id, kind, data or jpeg())
    assert put.status_code == 200, put.text
    r = c.post(f"{M}/{media['id']}/complete", headers=csrf(c))
    assert r.status_code == 200, r.text
    return r.json()


def clip(tmp_path: Path, size="640x360", seconds=4, name="walk.mp4") -> bytes:
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out.read_bytes()


# ---------- images ----------


def test_image_upload_is_reencoded_without_metadata(admin):
    c = admin["client"]
    listing = new_listing(c)
    media = add_image(c, listing["id"])
    assert media["status"] == "ready" and media["kind"] == "gallery"
    assert (media["width"], media["height"]) == (1600, 1000)
    large = c.get(media["large_url"])
    assert large.status_code == 200 and large.headers["content-type"] == "image/webp"
    image = Image.open(io.BytesIO(large.content))
    assert image.format == "WEBP" and not image.getexif()
    thumb = Image.open(io.BytesIO(c.get(media["thumb_url"]).content))
    assert max(thumb.size) == 640


def test_upload_link_refuses_other_sizes_and_types(admin):
    c = admin["client"]
    listing = new_listing(c)
    _, put = upload(c, listing["id"], "gallery", jpeg(), announced=1000)
    assert put.status_code == 403
    r = c.post(f"{M}/uploads", headers=csrf(c), json={
        "listing_id": listing["id"], "kind": "gallery", "filename": "x.jpg", "content_type": "image/jpeg", "size": 10})
    url = r.json()["upload"]["url"]
    assert c.put(url, content=b"0123456789", headers={"Content-Type": "image/png"}).status_code == 403
    assert c.put(url.replace("upload/", "upload/x"), content=b"0123456789",
                 headers={"Content-Type": "image/jpeg"}).status_code == 403


def test_local_files_cannot_escape_the_media_root(client):
    for path in ("ws/../../private/x", "ws/%2e%2e/%2e%2e/x", "..%5C..%5Cx", "C:/Windows/win.ini"):
        assert client.get(f"{M}/local/public/{path}").status_code == 404, path


def test_complete_checks_what_actually_arrived(admin):
    c = admin["client"]
    listing = new_listing(c)
    r = c.post(f"{M}/uploads", headers=csrf(c), json={
        "listing_id": listing["id"], "kind": "gallery", "filename": "x.jpg", "content_type": "image/jpeg", "size": 10})
    assert c.post(f"{M}/{r.json()['media']['id']}/complete", headers=csrf(c)).json()["error"]["code"] == "upload_missing"
    media, put = upload(c, listing["id"], "gallery", b"<script>alert(1)</script>")
    assert put.status_code == 200
    r = c.post(f"{M}/{media['id']}/complete", headers=csrf(c))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_image"


def test_upload_rules(admin, owner_engine):
    c = admin["client"]
    listing = new_listing(c)
    base = {"listing_id": listing["id"], "filename": "a", "size": 100}
    r = c.post(f"{M}/uploads", headers=csrf(c), json={**base, "kind": "gallery", "content_type": "image/gif"})
    assert r.json()["error"]["code"] == "unsupported_type"
    r = c.post(f"{M}/uploads", headers=csrf(c), json={**base, "kind": "video", "content_type": "video/mp4"})
    assert r.json()["error"]["code"] == "aspect_required"
    r = c.post(f"{M}/uploads", headers=csrf(c), json={**base, "kind": "gallery", "content_type": "image/jpeg",
                                                      "size": 26 * 1024 * 1024})
    assert r.json()["error"]["code"] == "file_too_large"
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE workspaces SET subscription_state = 'trialing' WHERE id = :w"),
                     {"w": admin["workspace_id"]})
    r = c.post(f"{M}/uploads", headers=csrf(c), json={**base, "kind": "video", "content_type": "video/mp4",
                                                      "aspect": "landscape", "size": 600 * 1024 * 1024})
    assert r.json()["error"]["code"] == "file_too_large"


def test_label_order_and_delete(admin):
    c = admin["client"]
    listing = new_listing(c)
    first, second = add_image(c, listing["id"]), add_image(c, listing["id"])
    r = c.patch(f"{M}/{first['id']}", headers=csrf(c), json={"label": " Kitchen ", "alt": "Open kitchen"})
    assert r.json()["label"] == "Kitchen" and r.json()["alt"] == "Open kitchen"
    r = c.put(f"{M}/order", headers=csrf(c), json={"listing_id": listing["id"], "kind": "gallery",
                                                    "ids": [second["id"], first["id"]]})
    assert [m["id"] for m in r.json()] == [second["id"], first["id"]]
    r = c.put(f"{M}/order", headers=csrf(c), json={"listing_id": listing["id"], "kind": "gallery", "ids": [first["id"]]})
    assert r.json()["error"]["code"] == "invalid_order"
    assert c.delete(f"{M}/{first['id']}", headers=csrf(c)).status_code == 204
    assert c.get(first["large_url"]).status_code == 404
    assert [m["id"] for m in c.get(M, params={"listing_id": listing["id"]}).json()] == [second["id"]]


def test_hero_upload_becomes_the_hero_and_publishes(admin):
    c = admin["client"]
    listing = new_listing(c)
    gallery = add_image(c, listing["id"])
    hero = add_image(c, listing["id"], kind="hero")
    assert c.get(f"/api/v1/listings/{listing['id']}").json()["hero"]["image_media_id"] == hero["id"]
    replacement = add_image(c, listing["id"], kind="hero")
    kinds = [m["kind"] for m in c.get(M, params={"listing_id": listing["id"]}).json()]
    assert kinds.count("hero") == 1
    r = c.put(f"/api/v1/listings/{listing['id']}/hero", headers=csrf(c),
              json={"enabled": True, "show_facts": True, "show_price": True, "image_media_id": gallery["id"]})
    assert r.json()["hero"]["image_media_id"] == gallery["id"]
    r = c.put(f"/api/v1/listings/{listing['id']}/hero", headers=csrf(c),
              json={"enabled": True, "show_facts": False, "show_price": True})
    assert r.json()["hero"]["image_media_id"] == gallery["id"]
    r = c.put(f"/api/v1/listings/{listing['id']}/hero", headers=csrf(c),
              json={"enabled": True, "show_facts": True, "show_price": True, "image_media_id": str(uuid4())})
    assert r.json()["error"]["code"] == "invalid_hero_image"

    assert publish(c, listing["id"]).status_code == 200
    with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
        live = s.execute(text("SELECT live FROM listings WHERE id = :id"), {"id": listing["id"]}).scalar_one()
    assert live["hero"]["image"]["id"] == gallery["id"]
    assert [g["id"] for g in live["gallery"]] == [gallery["id"]]
    public = c.get(live["gallery"][0]["url"])
    assert public.status_code == 200 and "immutable" in public.headers["cache-control"]
    assert replacement["id"] not in str(live["gallery"])
    # Deleting from the draft doesn't break the live page.
    c.delete(f"{M}/{gallery['id']}", headers=csrf(c))
    assert c.get(live["gallery"][0]["url"]).status_code == 200


# ---------- isolation ----------


def test_another_workspace_cannot_touch_media(admin, make_client):
    c = admin["client"]
    listing = new_listing(c)
    media = add_image(c, listing["id"])
    bob = make_client()
    sign_up(bob, "bob@example.com")
    assert bob.get(M, params={"listing_id": listing["id"]}).status_code == 404
    for method, url, body in (("post", f"{M}/{media['id']}/complete", None),
                              ("patch", f"{M}/{media['id']}", {"label": "x"}),
                              ("delete", f"{M}/{media['id']}", None)):
        r = bob.request(method.upper(), url, headers=csrf(bob), json=body)
        assert r.status_code == 404, (url, r.text)
    r = bob.post(f"{M}/uploads", headers=csrf(bob), json={
        "listing_id": listing["id"], "kind": "gallery", "filename": "x", "content_type": "image/jpeg", "size": 10})
    assert r.status_code == 404


def test_database_refuses_cross_workspace_media(admin, make_client):
    c = admin["client"]
    listing = new_listing(c)
    media = add_image(c, listing["id"])
    bob = make_client()
    bob_ws = sign_up(bob, "bob@example.com")["current_workspace_id"]
    bob_listing = new_listing(bob, "Bob's place")
    with tenant_session(None, bob_ws) as s:
        assert s.execute(text("SELECT count(*) FROM media")).scalar_one() == 0
    with pytest.raises(IntegrityError), tenant_session(None, bob_ws) as s:
        s.execute(text("""INSERT INTO media (workspace_id, listing_id, kind, key)
                          VALUES (:w, :l, 'gallery', 'private/x')"""), {"w": bob_ws, "l": listing["id"]})
    with pytest.raises(IntegrityError), tenant_session(None, bob_ws) as s:
        s.execute(text("UPDATE listing_hero SET image_media_id = :m WHERE listing_id = :l"),
                  {"m": media["id"], "l": bob_listing["id"]})


# ---------- walkthrough videos ----------


@needs_ffmpeg
def test_walkthrough_is_processed_and_published(admin, tmp_path):
    c = admin["client"]
    listing = new_listing(c, experience_type="immersive")
    codes = [b["code"] for b in c.get(f"/api/v1/listings/{listing['id']}").json()["publish_blockers"]]
    assert "walkthrough" in codes

    video, put = upload(c, listing["id"], "video", clip(tmp_path), "video/mp4", "walk.mp4", aspect="landscape")
    assert put.status_code == 200
    assert c.post(f"{M}/{video['id']}/complete", headers=csrf(c)).json()["status"] == "processing"
    r = publish(c, listing["id"])
    assert r.status_code == 409 and "still being prepared" in r.json()["error"]["message"]

    email.outbox.clear()
    assert worker.run_once() is True
    assert worker.run_once() is False
    ready = c.get(M, params={"listing_id": listing["id"]}).json()[0]
    assert ready["status"] == "ready" and ready["duration_ms"] >= 3900
    assert set(ready["warnings"]) == {"too_short", "low_resolution"}
    frames = ready["frames"]
    assert 50 <= frames["count"] <= 100
    assert c.get(frames["first"]).headers["content-type"] == "image/webp"
    urls = c.get(f"{M}/{frames['media_id']}/frames", params={"size": "large"}).json()
    assert urls["count"] == frames["count"] and len(urls["urls"]) == frames["count"]
    assert "ready" in email.outbox[-1].subject and email.outbox[-1].to == "admin@example.com"

    assert publish(c, listing["id"]).status_code == 200
    with tenant_session(admin["user_id"], admin["workspace_id"]) as s:
        live = s.execute(text("SELECT live FROM listings WHERE id = :id"), {"id": listing["id"]}).scalar_one()
    walk = live["walkthrough"]["landscape"]
    assert walk["count"] == frames["count"] and walk["large"]["width"] == 640
    last = c.get(walk["small"]["pattern"].replace("{n}", f"{walk['count']:04d}"))
    assert last.status_code == 200 and last.headers["content-type"] == "image/webp"


@needs_ffmpeg
def test_wrong_orientation_fails_with_a_clear_message(admin, tmp_path):
    c = admin["client"]
    listing = new_listing(c, experience_type="immersive")
    video, _ = upload(c, listing["id"], "video", clip(tmp_path, size="360x640", seconds=1), "video/mp4",
                      aspect="landscape")
    c.post(f"{M}/{video['id']}/complete", headers=csrf(c))
    worker.run_once()
    failed = c.get(M, params={"listing_id": listing["id"]}).json()[0]
    assert failed["status"] == "failed" and "portrait" in failed["error"]
    assert "couldn't process" in email.outbox[-1].subject
    codes = [b["code"] for b in c.get(f"/api/v1/listings/{listing['id']}").json()["publish_blockers"]]
    assert "walkthrough" in codes


@needs_ffmpeg
def test_new_walkthrough_replaces_the_old_one(admin, tmp_path):
    c = admin["client"]
    listing = new_listing(c, experience_type="immersive")
    ids = []
    for n in range(2):
        video, _ = upload(c, listing["id"], "video", clip(tmp_path, seconds=1, name=f"{n}.mp4"), "video/mp4",
                          aspect="landscape")
        c.post(f"{M}/{video['id']}/complete", headers=csrf(c))
        worker.run_once()
        ids.append(video["id"])
    assert [m["id"] for m in c.get(M, params={"listing_id": listing["id"]}).json()] == [ids[1]]
