def test_delete_and_trash_lifecycle(client, signup_user, upload_asset):
    headers, _ = signup_user(email="tr@ex.com")
    asset, _, data = upload_asset(headers)
    asset_id = asset["id"]

    # Soft delete.
    r = client.delete(f"/api/asset/{asset_id}", headers=headers)
    assert r.status_code == 200

    # No longer visible in Library.
    r_list = client.get("/api/asset", headers=headers)
    assert r_list.get_json()["items"] == []

    # Trash requires PIN session.
    r_trash = client.get("/api/trash", headers=headers)
    assert r_trash.status_code == 403

    # Set + verify PIN.
    assert client.post("/api/user/deleted-pin", json={"pin": "1234"}, headers=headers).status_code == 200
    r_verify = client.post("/api/user/deleted-pin/verify", json={"pin": "1234"}, headers=headers)
    assert r_verify.status_code == 200

    # Trash listing visible.
    r_trash2 = client.get("/api/trash", headers=headers)
    assert r_trash2.status_code == 200
    items = r_trash2.get_json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == asset_id

    # Restore returns it to Library.
    r_restore = client.post(f"/api/trash/{asset_id}/restore", headers=headers)
    assert r_restore.status_code == 200
    assert client.get("/api/asset", headers=headers).get_json()["items"][0]["id"] == asset_id


def test_permanent_delete_decrements_blob_refcount_and_quota(client, signup_user, upload_asset, db_session):
    from server.models import Blob, User

    headers, payload = signup_user(email="pd@ex.com")
    user_id = payload["user"]["id"]
    asset, sha, data = upload_asset(headers)
    size = len(data)

    # Prime PIN session.
    client.post("/api/user/deleted-pin", json={"pin": "9999"}, headers=headers)
    client.post("/api/user/deleted-pin/verify", json={"pin": "9999"}, headers=headers)

    # Soft delete then permanent delete.
    client.delete(f"/api/asset/{asset['id']}", headers=headers)
    r_perm = client.delete(f"/api/trash/{asset['id']}", headers=headers)
    assert r_perm.status_code == 200

    assert db_session.get(Blob, sha) is None
    user = db_session.get(User, user_id)
    assert user.storage_used_bytes == 0


def test_bad_pin_denied_and_purge_requires_pin(client, signup_user, upload_asset):
    headers, _ = signup_user(email="bp@ex.com")
    upload_asset(headers)
    client.post("/api/user/deleted-pin", json={"pin": "abcd"}, headers=headers)
    bad = client.post("/api/user/deleted-pin/verify", json={"pin": "wrong"}, headers=headers)
    assert bad.status_code == 401

    # Purge without pin body fails.
    r = client.post("/api/trash/purge", json={"pin": "wrong"}, headers=headers)
    assert r.status_code == 401
