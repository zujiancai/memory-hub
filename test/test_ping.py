def test_ping(client):
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["commit"] == "test-sha"
    assert isinstance(body["version"], str)
