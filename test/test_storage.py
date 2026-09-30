def test_quota_endpoint(client, signup_user, upload_asset):
    headers, _ = signup_user(email="qq@ex.com")
    upload_asset(headers)
    r = client.get("/api/storage/quota", headers=headers)
    body = r.get_json()
    assert body["asset_count"] == 1
    assert body["used_bytes"] > 0
    assert body["deleted_pending_purge_bytes"] == 0

    # Soft delete moves bytes to deleted_pending_purge_bytes without changing used_bytes.
    asset_id_resp = client.get("/api/asset", headers=headers).get_json()["items"][0]["id"]
    client.delete(f"/api/asset/{asset_id_resp}", headers=headers)
    body2 = client.get("/api/storage/quota", headers=headers).get_json()
    assert body2["used_bytes"] == body["used_bytes"]
    assert body2["deleted_pending_purge_bytes"] == body["used_bytes"]
    assert body2["asset_count"] == 0
