def _install_fake_exchange(app, sub: str, email: str, name: str):
    def _fake(client_id, client_secret, redirect_uri, code, verifier):
        return sub, email, name

    app.extensions["google_oauth_exchange"] = _fake


def test_google_oauth_start_returns_verifier(client, app):
    r = client.get("/api/user/oauth/google/start")
    assert r.status_code == 200
    body = r.get_json()
    assert body["authorize_url"].startswith("https://accounts.google.com/")
    assert body["code_verifier"]
    assert body["state"]


def test_google_oauth_callback_creates_and_reuses(client, app):
    _install_fake_exchange(app, sub="12345", email="new@google.com", name="New Person")
    r = client.post(
        "/api/user/oauth/google/callback",
        json={"code": "abc", "code_verifier": "xyz"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["user"]["email"] == "new@google.com"
    first_user_id = body["user"]["id"]

    # Second call with same sub reuses user.
    r2 = client.post(
        "/api/user/oauth/google/callback",
        json={"code": "abc2", "code_verifier": "xyz2"},
    )
    assert r2.status_code == 200
    assert r2.get_json()["user"]["id"] == first_user_id


def test_google_oauth_callback_missing_code(client):
    r = client.post("/api/user/oauth/google/callback", json={})
    assert r.status_code == 400
