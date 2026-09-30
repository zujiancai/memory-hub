def test_signup_returns_tokens_and_user(client):
    resp = client.post(
        "/api/user/signup",
        json={"email": "u@example.com", "password": "topsecret", "friendly_name": "U"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "u@example.com"
    assert body["user"]["role"] == "user"
    assert body["user"]["storage_quota_bytes"] > 0

    # Duplicate signup rejected.
    resp2 = client.post(
        "/api/user/signup",
        json={"email": "u@example.com", "password": "again", "friendly_name": "U"},
    )
    assert resp2.status_code == 409


def test_login_wrong_password(client, signup_user):
    signup_user(email="l@example.com", password="rightpass")
    resp = client.post("/api/user/login", json={"email": "l@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_success_and_refresh_rotates(client, signup_user):
    _, payload = signup_user(email="r@example.com", password="rotate-me")
    old_refresh = payload["refresh_token"]

    resp = client.post("/api/user/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new_payload = resp.get_json()
    assert new_payload["refresh_token"] != old_refresh

    # Old refresh token now revoked.
    resp2 = client.post("/api/user/refresh", json={"refresh_token": old_refresh})
    assert resp2.status_code == 401


def test_logout_revokes_refresh(client, signup_user):
    _, payload = signup_user(email="lo@example.com")
    r = client.post("/api/user/logout", json={"refresh_token": payload["refresh_token"]})
    assert r.status_code == 200

    r2 = client.post("/api/user/refresh", json={"refresh_token": payload["refresh_token"]})
    assert r2.status_code == 401


def test_me_endpoints(client, signup_user):
    headers, _ = signup_user(email="me@example.com", friendly_name="Original")
    r = client.get("/api/user/me", headers=headers)
    assert r.status_code == 200
    assert r.get_json()["friendly_name"] == "Original"

    r2 = client.patch(
        "/api/user/me",
        json={"friendly_name": "New Name", "avatar_generator_json": {"style": "notionists"}},
        headers=headers,
    )
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["friendly_name"] == "New Name"
    assert body["avatar_generator_json"]["style"] == "notionists"


def test_require_auth_denies_missing_token(client):
    r = client.get("/api/user/me")
    assert r.status_code == 401
