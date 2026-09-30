import hashlib


def test_upload_and_list(client, signup_user, upload_asset):
    headers, _ = signup_user(email="up@example.com")
    asset, sha, _ = upload_asset(headers)
    assert asset["kind"] == "photo"

    r = client.get("/api/asset", headers=headers)
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == asset["id"]
    assert items[0]["thumbnail_url"].startswith("memoryhub-local://")

    thumb = client.get(f"/api/asset/{asset['id']}/thumbnail", headers=headers)
    assert thumb.status_code == 302
    assert thumb.headers["Location"].startswith("memoryhub-local://")


def test_precheck_dedup_on_second_upload(client, signup_user, sample_jpeg_factory, blob_store):
    headers, _ = signup_user(email="d@example.com")
    data = sample_jpeg_factory(color=(1, 2, 3))
    sha = hashlib.sha256(data).hexdigest()

    r1 = client.post(
        "/api/asset/precheck", json={"sha256": sha, "size": len(data)}, headers=headers
    )
    assert r1.get_json()["exists"] is False
    blob_store.put(sha, data, content_type="image/jpeg")
    client.post(
        "/api/asset",
        json={"sha256": sha, "size": len(data), "original_filename": "a.jpg", "mime_type": "image/jpeg"},
        headers=headers,
    )

    r2 = client.post(
        "/api/asset/precheck", json={"sha256": sha, "size": len(data)}, headers=headers
    )
    body = r2.get_json()
    assert body["exists"] is True
    assert "upload_url" not in body


def test_precheck_ignores_phase2_fields(client, signup_user, sample_jpeg_factory):
    headers, _ = signup_user(email="p2@example.com")
    data = sample_jpeg_factory(color=(4, 5, 6))
    sha = hashlib.sha256(data).hexdigest()
    r = client.post(
        "/api/asset/precheck",
        json={
            "sha256": sha,
            "size": len(data),
            "phash": "deadbeefdeadbeef",
            "upload_quality": "space_saver",
        },
        headers=headers,
    )
    assert r.status_code == 200


def test_ownership_boundary(client, signup_user, upload_asset):
    headers_a, _ = signup_user(email="a@ex.com")
    asset_a, _, _ = upload_asset(headers_a)
    headers_b, _ = signup_user(email="b@ex.com")

    r = client.get(f"/api/asset/{asset_a['id']}", headers=headers_b)
    assert r.status_code == 404

    r_del = client.delete(f"/api/asset/{asset_a['id']}", headers=headers_b)
    assert r_del.status_code == 404


def test_quota_413(client, signup_user, sample_jpeg_factory, blob_store, db_session):
    from server.models import User

    headers, payload = signup_user(email="q@ex.com")
    user_id = payload["user"]["id"]

    # Shrink quota so the next upload will blow past it.
    data = sample_jpeg_factory(color=(9, 9, 9))
    sha = hashlib.sha256(data).hexdigest()
    user = db_session.get(User, user_id)
    user.storage_quota_bytes = len(data) - 1
    db_session.commit()

    blob_store.put(sha, data, content_type="image/jpeg")
    r = client.post(
        "/api/asset",
        json={"sha256": sha, "size": len(data), "original_filename": "x.jpg", "mime_type": "image/jpeg"},
        headers=headers,
    )
    assert r.status_code == 413

    # storage_used_bytes unchanged and blob row not created.
    from server.models import Blob

    assert db_session.get(Blob, sha) is None
    user = db_session.get(User, user_id)
    assert user.storage_used_bytes == 0


def test_get_asset_returns_read_url(client, signup_user, upload_asset):
    headers, _ = signup_user(email="g@ex.com")
    asset, _, _ = upload_asset(headers)
    r = client.get(f"/api/asset/{asset['id']}", headers=headers)
    body = r.get_json()
    assert body["read_url"].startswith("memoryhub-local://")
    assert body["poster_url"].startswith("memoryhub-local://")


def test_list_pagination_with_cursor(client, signup_user, upload_asset, sample_jpeg_factory):
    headers, _ = signup_user(email="pg@ex.com")
    for i in range(3):
        upload_asset(headers, jpeg_bytes=sample_jpeg_factory(color=(i, i, i)), filename=f"p{i}.jpg")

    r = client.get("/api/asset?limit=2", headers=headers)
    body = r.get_json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]

    r2 = client.get(f"/api/asset?limit=2&cursor={body['next_cursor']}", headers=headers)
    body2 = r2.get_json()
    assert len(body2["items"]) == 1
