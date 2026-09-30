import hashlib


def test_avatar_upload(client, signup_user, sample_jpeg_factory):
    headers, payload = signup_user(email="av@ex.com")
    data = sample_jpeg_factory(color=(200, 50, 30))
    r = client.post(
        "/api/user/me/avatar",
        data=data,
        content_type="image/jpeg",
        headers=headers,
    )
    assert r.status_code == 200, r.get_json()
    sha = hashlib.sha256(data).hexdigest()
    assert r.get_json()["avatar_blob_key"] == sha


def test_avatar_upload_rejects_unsupported_mime(client, signup_user):
    headers, _ = signup_user(email="av2@ex.com")
    r = client.post(
        "/api/user/me/avatar",
        data=b"nope",
        content_type="text/plain",
        headers=headers,
    )
    assert r.status_code == 415


def test_avatar_upload_rejects_oversize(client, signup_user, sample_jpeg_factory, app):
    headers, _ = signup_user(email="av3@ex.com")
    # Force a tiny cap to make the test fast.
    app.config["MAX_AVATAR_BYTES"] = 100
    data = sample_jpeg_factory()
    r = client.post(
        "/api/user/me/avatar",
        data=data,
        content_type="image/jpeg",
        headers=headers,
    )
    assert r.status_code == 413
