"""Device authentication and offline-sync behaviour."""

from __future__ import annotations

import pytest
from app.database.base import utcnow
from app.database.models import Device, PairingCode
from app.security.tokens import (
    generate_device_token,
    generate_pairing_code,
    hash_pairing_code,
    new_device_id,
    parse_token,
    verify_token_secret,
)
from fastapi.testclient import TestClient


@pytest.fixture()
def client(db, monkeypatch):
    from app.main import create_app

    app = create_app()
    # The worker thread is irrelevant to these tests and slows them down.
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    with TestClient(app) as test_client:
        yield test_client


def test_unpaired_device_is_rejected(client):
    for path in ("/api/v1/drafts", "/api/v1/system/home", "/api/v1/approvals"):
        response = client.get(path) if path != "/api/v1/approvals" else client.post(path, json={})
        assert response.status_code == 401, path


def test_garbage_token_is_rejected(client):
    response = client.get("/api/v1/drafts", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_token_for_unknown_device_is_rejected(client):
    token, _ = generate_device_token(new_device_id())
    response = client.get("/api/v1/drafts", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_revoked_device_loses_access(db, client):
    from datetime import timedelta

    code = generate_pairing_code()
    db.add(PairingCode(code_hash=hash_pairing_code(code), expires_at=utcnow() + timedelta(minutes=5)))
    db.commit()

    paired = client.post(
        "/api/v1/auth/pair", json={"code": code, "device_name": "test phone"}
    )
    assert paired.status_code == 200
    token = paired.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    assert client.post("/api/v1/auth/revoke", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_expired_pairing_code_is_rejected(db, client):
    from datetime import timedelta

    code = generate_pairing_code()
    db.add(PairingCode(code_hash=hash_pairing_code(code), expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()

    response = client.post("/api/v1/auth/pair", json={"code": code, "device_name": "late phone"})
    assert response.status_code == 401


def test_pairing_code_is_single_use(db, client):
    from datetime import timedelta

    code = generate_pairing_code()
    db.add(PairingCode(code_hash=hash_pairing_code(code), expires_at=utcnow() + timedelta(minutes=5)))
    db.commit()

    assert client.post("/api/v1/auth/pair", json={"code": code, "device_name": "first"}).status_code == 200
    assert client.post("/api/v1/auth/pair", json={"code": code, "device_name": "second"}).status_code == 401


def test_token_is_never_stored_in_plaintext(db, client):
    from datetime import timedelta

    code = generate_pairing_code()
    db.add(PairingCode(code_hash=hash_pairing_code(code), expires_at=utcnow() + timedelta(minutes=5)))
    db.commit()

    token = client.post(
        "/api/v1/auth/pair", json={"code": code, "device_name": "phone"}
    ).json()["token"]

    device_id, secret = parse_token(token)
    device = db.get(Device, device_id)
    assert device is not None
    assert secret not in device.token_hash
    assert token not in device.token_hash
    assert verify_token_secret(secret, device.token_hash)


def test_approval_requires_the_hash_of_what_was_shown(db, client, make_draft):
    from datetime import timedelta

    draft = make_draft()
    code = generate_pairing_code()
    db.add(PairingCode(code_hash=hash_pairing_code(code), expires_at=utcnow() + timedelta(minutes=5)))
    db.commit()
    token = client.post(
        "/api/v1/auth/pair", json={"code": code, "device_name": "phone"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # No hash at all.
    missing = client.post(
        "/api/v1/approvals",
        json={"draft_id": draft.id, "action": "APPROVE"},
        headers=headers,
    )
    assert missing.status_code == 422

    # Hash of something else.
    stale = client.post(
        "/api/v1/approvals",
        json={"draft_id": draft.id, "action": "APPROVE", "expected_content_hash": "0" * 64},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "content_changed"
