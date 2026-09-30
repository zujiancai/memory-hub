def test_worker_processes_photo(client, signup_user, upload_asset, app, db_session):
    from server.models import Asset
    from server.worker import drain_once

    headers, _ = signup_user(email="w@ex.com")
    asset_json, _, _ = upload_asset(headers)
    n = drain_once(app)
    assert n == 1
    row = db_session.get(Asset, asset_json["id"])
    db_session.refresh(row)
    assert row.poster_blob_sha256, "poster blob should be populated"
    assert row.width and row.height, "dimensions should be populated"
    assert row.exif_json is not None
