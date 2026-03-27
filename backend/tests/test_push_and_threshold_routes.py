import pytest

from app.utils.auth import hash_password


def _make_phone_lookup(users):
    async def fake_get_user_auth_by_phone(phone_number):
        for user in users.values():
            if user.get("phone_number") == phone_number:
                return user
        return None

    return fake_get_user_auth_by_phone


@pytest.mark.asyncio
async def test_owner_can_update_device_thresholds_with_backend_field_names(client, app_module, monkeypatch):
    users = {
        "owner-001": {
            "_id": "1",
            "user_id": "owner-001",
            "name": "Owner One",
            "phone_number": "+84987654321",
            "is_active": True,
            "password_hash": hash_password("OwnerPass123"),
            "caregivers": [],
        }
    }
    device_state = {
        "device_id": "dev-001",
        "device_name": "Wrist 1",
        "device_type": "wrist",
        "settings": {},
        "alert_thresholds": None,
    }
    captured = {}

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return device_state if device_id == "dev-001" else None

    async def fake_get_device_link(device_id, user_id):
        if device_id == "dev-001" and user_id == "owner-001":
            return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}
        return None

    async def fake_update_device_thresholds(device_id, thresholds):
        captured["thresholds"] = dict(thresholds)
        device_state["settings"] = {"alert_thresholds": dict(thresholds)}
        device_state["alert_thresholds"] = dict(thresholds)
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "update_device_thresholds", fake_update_device_thresholds)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "OwnerPass123"},
    )
    token = login.json()["access_token"]

    response = await client.patch(
        "/api/v1/devices/dev-001/thresholds",
        headers={"Authorization": f"Bearer {token}"},
        json={"spo2_low": 92.0, "hr_high": 115, "temp_low": 35.4},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert captured["thresholds"] == {"spo2_low": 92.0, "hr_high": 115, "temp_low": 35.4}
    assert device_state["settings"]["alert_thresholds"] == captured["thresholds"]
    assert device_state["alert_thresholds"] == captured["thresholds"]
    assert response.json()["updated_thresholds"] == captured["thresholds"]


@pytest.mark.asyncio
async def test_linked_user_can_read_effective_device_thresholds(client, app_module, monkeypatch):
    users = {
        "viewer-001": {
            "_id": "2",
            "user_id": "viewer-001",
            "name": "Viewer One",
            "phone_number": "+84911110002",
            "is_active": True,
            "password_hash": hash_password("ViewerPass123"),
            "caregivers": [],
        }
    }
    device_state = {
        "device_id": "dev-001",
        "device_name": "Wrist 1",
        "device_type": "wrist",
        "settings": {"alert_thresholds": {"spo2_low": 92.0, "hr_high": 115, "rr_low": 9}},
        "alert_thresholds": {"spo2_low": 88.0, "hr_high": 140, "rr_high": 20},
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return device_state if device_id == "dev-001" else None

    async def fake_get_device_link(device_id, user_id):
        if device_id == "dev-001" and user_id == "viewer-001":
            return {"device_id": device_id, "user_id": user_id, "link_role": "viewer"}
        return None

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0911110002", "password": "ViewerPass123"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/devices/dev-001/thresholds",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "device_id": "dev-001",
        "thresholds": {
            "spo2_low": 92.0,
            "spo2_critical": 85.0,
            "temp_high": 38.0,
            "temp_critical": 39.5,
            "temp_low": 35.5,
            "hr_low": 50,
            "hr_low_critical": 40,
            "hr_high": 115,
            "hr_critical": 150,
        },
    }


@pytest.mark.asyncio
async def test_register_push_token_for_current_user(client, app_module, monkeypatch):
    users = {
        "user-001": {
            "_id": "1",
            "user_id": "user-001",
            "name": "User One",
            "phone_number": "+84987654321",
            "is_active": True,
            "password_hash": hash_password("UserPass123"),
            "caregivers": [],
        }
    }
    captured = {}

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_upsert_push_token(user_id, installation_id, fcm_token, platform, session_id=None):
        captured["payload"] = {
            "user_id": user_id,
            "installation_id": installation_id,
            "fcm_token": fcm_token,
            "platform": platform,
            "session_id": session_id,
        }
        return "created"

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "upsert_push_token", fake_upsert_push_token)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "UserPass123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/me/push-tokens",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "installation_id": "install-001",
            "fcm_token": "fcm-token-abcdefghijklmnopqrstuvwxyz",
            "platform": "android",
        },
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert captured["payload"]["user_id"] == "user-001"
    assert captured["payload"]["installation_id"] == "install-001"
    assert captured["payload"]["platform"] == "android"
    assert isinstance(captured["payload"]["session_id"], str)
    assert response.json()["result"] == "created"


@pytest.mark.asyncio
async def test_delete_push_token_for_current_user(client, app_module, monkeypatch):
    users = {
        "user-001": {
            "_id": "1",
            "user_id": "user-001",
            "name": "User One",
            "phone_number": "+84987654321",
            "is_active": True,
            "password_hash": hash_password("UserPass123"),
            "caregivers": [],
        }
    }
    captured = {}

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_deactivate_push_token(user_id, installation_id):
        captured["payload"] = {
            "user_id": user_id,
            "installation_id": installation_id,
        }
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "deactivate_push_token", fake_deactivate_push_token)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "UserPass123"},
    )
    token = login.json()["access_token"]

    response = await client.delete(
        "/api/v1/me/push-tokens/install-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert captured["payload"] == {"user_id": "user-001", "installation_id": "install-001"}
    assert response.json()["status"] == "success"
