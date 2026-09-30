def _make_admin(app, db_session):
    from server.auth import hash_password
    from server.models import User

    admin = User(
        email="admin@ex.com",
        password_hash=hash_password("adminpass"),
        friendly_name="admin",
        storage_quota_bytes=app.config["DEFAULT_USER_QUOTA_BYTES"],
        role="admin",
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def test_admin_can_create_user(client, app, db_session):
    _make_admin(app, db_session)
    tokens = client.post(
        "/api/user/login", json={"email": "admin@ex.com", "password": "adminpass"}
    ).get_json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.post(
        "/api/admin/user",
        json={"email": "new@ex.com", "password": "hunter2", "role": "user"},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.get_json()["email"] == "new@ex.com"


def test_non_admin_forbidden(client, signup_user):
    headers, _ = signup_user(email="reg@ex.com")
    r = client.post("/api/admin/user", json={"email": "x@x.com"}, headers=headers)
    assert r.status_code == 403
