from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.utils.auth import hash_pairing_code, hash_password


def _make_phone_lookup(users):
    async def fake_get_user_auth_by_phone(phone_number):
        for user in users.values():
            if user.get("phone_number") == phone_number:
                return user
        return None

    return fake_get_user_auth_by_phone


@pytest.mark.asyncio
async def test_ready_returns_503_when_db_down(client, app_module, monkeypatch):
    async def fake_ping():
        return False

    monkeypatch.setattr(app_module.db, "ping", fake_ping)
    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["database"] == "disconnected"


@pytest.mark.asyncio
async def test_metrics_are_disabled_by_default(client):
    response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_login_returns_refresh_token_and_session_id(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    response = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body["access_token"], str)
    assert isinstance(body["refresh_token"], str)
    assert isinstance(body["session_id"], str)
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["session_id"]
    assert body["user_id"] == "patient-001"


@pytest.mark.asyncio
async def test_login_with_phone_number_normalizes_and_returns_tokens(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "date_of_birth": "2004-02-01",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    response = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body.keys()) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_at",
        "refresh_expires_at",
        "session_id",
        "user_id",
    }
    assert body["user_id"] == "patient-001"
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_creates_user_with_normalized_phone(client, app_module, monkeypatch):
    created = {}

    async def fake_phone_exists(phone_number):
        return phone_number in created

    async def fake_generate_user_id():
        return "user-a1b2c3d4"

    async def fake_create_user_with_phone(doc):
        created[doc["phone_number"]] = dict(doc)
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "phone_exists", fake_phone_exists)
    monkeypatch.setattr(app_module.db, "generate_user_id", fake_generate_user_id)
    monkeypatch.setattr(app_module.db, "create_user_with_phone", fake_create_user_with_phone)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Dang Thanh Tai",
            "phone_number": "0987654321",
            "date_of_birth": "2004-02-01",
            "password": "MatKhau123",
        },
    )

    body = response.json()
    saved_user = created["+84987654321"]
    assert response.status_code == 200
    assert body == {"status": "success", "user_id": "user-a1b2c3d4"}
    assert isinstance(body["status"], str)
    assert isinstance(body["user_id"], str)
    assert saved_user["name"] == "Dang Thanh Tai"
    assert saved_user["phone_number"] == "+84987654321"
    assert saved_user["date_of_birth"] == "2004-02-01"
    assert "role" not in saved_user
    assert saved_user["is_active"] is True
    assert saved_user["password_hash"] != "MatKhau123"


@pytest.mark.asyncio
async def test_register_returns_409_when_phone_number_exists(client, app_module, monkeypatch):
    async def fake_phone_exists(phone_number):
        return phone_number == "+84987654321"

    monkeypatch.setattr(app_module.db, "phone_exists", fake_phone_exists)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Dang Thanh Tai",
            "phone_number": "84987654321",
            "date_of_birth": "2004-02-01",
            "password": "MatKhau123",
        },
    )

    assert response.status_code == 409
    assert response.json()["message"] == "Phone number already registered"


@pytest.mark.asyncio
async def test_register_rejects_future_date_of_birth(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Dang Thanh Tai",
            "phone_number": "0987654321",
            "date_of_birth": "2099-02-01",
            "password": "MatKhau123",
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "Date of birth cannot be in the future"


@pytest.mark.asyncio
async def test_me_returns_extended_profile_fields(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "date_of_birth": "2004-02-01",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_user(user_id):
        user = users.get(user_id)
        if not user:
            return None
        sanitized = dict(user)
        sanitized.pop("password_hash", None)
        return sanitized

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert response.status_code == 200
    assert {"user_id", "name", "phone_number", "date_of_birth", "is_active"} <= set(body.keys())
    assert isinstance(body["user_id"], str)
    assert isinstance(body["name"], str)
    assert isinstance(body["phone_number"], str)
    assert isinstance(body["is_active"], bool)
    assert body["user_id"] == "patient-001"
    assert body["phone_number"] == "+84987654321"
    assert body["date_of_birth"] == "2004-02-01"
    assert "role" not in body
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))

    response = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "WrongPass1"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_invalidates_old_refresh(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    login_body = login.json()

    refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_body["refresh_token"]},
    )
    refresh_body = refresh.json()

    reused = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_body["refresh_token"]},
    )

    assert login.status_code == 200
    assert refresh.status_code == 200
    assert refresh_body["session_id"] == login_body["session_id"]
    assert refresh_body["refresh_token"] != login_body["refresh_token"]
    assert refresh_body["access_token"] != login_body["access_token"]
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_current_session(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_user(user_id):
        user = users.get(user_id)
        if not user:
            return None
        sanitized = dict(user)
        sanitized.pop("password_hash", None)
        return sanitized

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert logout.status_code == 200
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_after_logout_is_rejected(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_user(user_id):
        return users.get(user_id)

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    login_body = login.json()

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login_body['access_token']}"},
    )
    refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_body["refresh_token"]},
    )

    assert logout.status_code == 200
    assert refresh.status_code == 401


@pytest.mark.asyncio
async def test_expired_access_token_is_rejected(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_auth_session(session_id):
        return {
            "session_id": session_id,
            "user_id": "patient-001",
            "expires_at": datetime.utcnow() + timedelta(days=1),
        }

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_auth_session", fake_get_auth_session)

    expired_token = jwt.encode(
        {
            "sub": "patient-001",
            "role": "patient",
            "sid": "expired-session",
            "token_type": "access",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        app_module.settings.jwt_secret,
        algorithm=app_module.settings.jwt_algorithm,
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.json()["message"] == "Access token expired"


@pytest.mark.asyncio
async def test_public_device_latest_now_requires_auth(client):
    response = await client.get("/api/v1/public/devices/dev-001/latest")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_public_device_latest_with_auth_returns_data(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Wristband 1", "device_type": "wrist"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}

    async def fake_get_latest_reading(device_id):
        return {
            "_id": "abc123",
            "device_id": device_id,
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 82, "spo2": 98},
        }

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_latest_reading", fake_get_latest_reading)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/public/devices/dev-001/latest",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["device_id"] == "dev-001"
    assert response.json()["vitals"]["heart_rate"] == 82


@pytest.mark.asyncio
async def test_device_ecg_endpoint_returns_items(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Chest 1", "device_type": "chest"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}

    async def fake_get_device_ecg_readings(device_id, quality_filter=None, limit=10):
        return [
            {
                "_id": "ecg-001",
                "device_id": device_id,
                "timestamp": 1771763000.12,
                "ecg": {"quality": quality_filter or "good", "waveform": [0.1, 0.2, 0.1]},
            }
        ]

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_device_ecg_readings", fake_get_device_ecg_readings)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/devices/dev-001/ecg?quality_filter=good&limit=5",
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert login.status_code == 200
    assert response.status_code == 200
    assert body["device_id"] == "dev-001"
    assert body["count"] == 1
    assert isinstance(body["items"], list)
    assert body["items"][0]["device_id"] == "dev-001"
    assert body["items"][0]["ecg"]["quality"] == "good"
    assert "deviceId" not in body


@pytest.mark.asyncio
async def test_device_summary_tolerates_small_future_clock_skew(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }
    observed = {}

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Wristband 1", "device_type": "wrist"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}

    async def fake_get_readings_by_device(device_id, start_time=None, end_time=None, limit=100):
        observed["start_time"] = start_time
        observed["end_time"] = end_time
        observed["limit"] = limit
        return [
            {
                "_id": "abc123",
                "device_id": device_id,
                "timestamp": 1010,
                "vitals": {"heart_rate": 82, "spo2": 98, "temperature": 36.7},
            }
        ]

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_readings_by_device", fake_get_readings_by_device)
    monkeypatch.setattr(app_module.settings, "device_clock_skew_tolerance_seconds", 300)
    monkeypatch.setattr("time.time", lambda: 1000.0)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/devices/dev-001/summary?period=1h",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["total_readings"] == 1
    assert response.json()["summary"]["heart_rate"]["avg"] == 82
    assert response.json()["clock_skew_tolerance_seconds"] == 300
    assert observed["start_time"] == -2600.0
    assert observed["end_time"] == 1300.0
    assert observed["limit"] == 10000


@pytest.mark.asyncio
async def test_me_devices_returns_linked_devices(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_list_devices_for_user(user_id):
        return [
            {
                "device_id": "dev-001",
                "device_name": "Wristband 1",
                "device_type": "wrist",
                "firmware_version": "1.0.0",
                "registered_at": "2026-03-17T10:00:00Z",
                "last_seen": "2026-03-17T10:05:00Z",
                "status": "active",
                "link_role": "owner",
                "linked_at": "2026-03-17T10:01:00Z",
                "linked_by": "admin-001",
                "linked_users": [
                    {
                        "user_id": "patient-001",
                        "name": "Patient One",
                        "phone_number": "+84987654321",
                        "link_role": "owner",
                    },
                    {
                        "user_id": "viewer-001",
                        "name": "Viewer One",
                        "phone_number": "+84987654322",
                        "link_role": "viewer",
                    }
                ],
            }
        ]

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "list_devices_for_user", fake_list_devices_for_user)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/me/devices",
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert login.status_code == 200
    assert response.status_code == 200
    assert body["user_id"] == "patient-001"
    assert body["count"] == 1
    assert isinstance(body["items"], list)
    assert body["items"][0]["device_id"] == "dev-001"
    assert body["items"][0]["device_type"] == "wrist"
    assert body["items"][0]["device_name"] == "Wristband 1"
    assert body["items"][0]["link_role"] == "owner"
    assert isinstance(body["items"][0]["linked_users"], list)
    assert body["items"][0]["linked_users"][0]["user_id"] == "patient-001"
    assert body["items"][0]["linked_users"][0]["phone_number"] == "+84987654321"
    assert body["items"][0]["linked_users"][0]["link_role"] == "owner"
    assert body["items"][0]["linked_users"][1]["link_role"] == "viewer"
    assert "deviceId" not in body["items"][0]


@pytest.mark.asyncio
async def test_viewer_can_access_device(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {
            "_id": "devdoc1",
            "device_id": device_id,
            "device_name": "Wristband 1",
            "device_type": "wrist",
            "status": "active",
        }

    async def fake_get_device_link(device_id, user_id):
        if device_id == "dev-001" and user_id == "patient-001":
            return {"device_id": device_id, "user_id": user_id, "link_role": "viewer"}
        return None

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/devices/dev-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["device_id"] == "dev-001"


@pytest.mark.asyncio
async def test_claim_device_assigns_owner_link(client, app_module, monkeypatch):
    users = {
        "user-001": {
            "_id": "1",
            "user_id": "user-001",
            "name": "User One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("UserPass123"),
            "caregivers": [],
        }
    }
    captured = {}

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {
            "device_id": device_id,
            "device_name": "Wristband 1",
            "device_type": "wrist",
            "pairing_code_hash": hash_pairing_code("PAIR-1234"),
        }

    async def fake_get_device_owner_link(device_id):
        return None

    async def fake_upsert_device_link(device_id, user_id, permission, added_by_user_id):
        captured.update(
            {
                "device_id": device_id,
                "user_id": user_id,
                "permission": permission,
                "added_by_user_id": added_by_user_id,
            }
        )
        return "linked"

    async def fake_clear_device_pairing_code(device_id):
        captured["pairing_code_cleared_for"] = device_id
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_owner_link", fake_get_device_owner_link)
    monkeypatch.setattr(app_module.db, "upsert_device_link", fake_upsert_device_link)
    monkeypatch.setattr(app_module.db, "clear_device_pairing_code", fake_clear_device_pairing_code)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "UserPass123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/dev-001/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"pairing_code": "PAIR-1234"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "status": "claimed",
        "device_id": "dev-001",
        "user_id": "user-001",
        "permission": "owner",
        "link_role": "owner",
    }
    assert captured == {
        "device_id": "dev-001",
        "user_id": "user-001",
        "permission": "owner",
        "added_by_user_id": "user-001",
        "pairing_code_cleared_for": "dev-001",
    }


@pytest.mark.asyncio
async def test_claim_device_returns_409_when_owner_exists(client, app_module, monkeypatch):
    users = {
        "user-001": {
            "_id": "1",
            "user_id": "user-001",
            "name": "User One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("UserPass123"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {
            "device_id": device_id,
            "device_name": "Wristband 1",
            "device_type": "wrist",
            "pairing_code_hash": hash_pairing_code("PAIR-1234"),
        }

    async def fake_get_device_owner_link(device_id):
        return {"device_id": device_id, "user_id": "owner-001", "link_role": "owner"}

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_owner_link", fake_get_device_owner_link)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "UserPass123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/dev-001/claim",
        headers={"Authorization": f"Bearer {token}"},
        json={"pairing_code": "PAIR-1234"},
    )

    assert login.status_code == 200
    assert response.status_code == 409
    assert response.json()["message"] == "This device already has an owner"


@pytest.mark.asyncio
async def test_owner_can_add_and_remove_viewer(client, app_module, monkeypatch):
    users = {
        "owner-001": {
            "_id": "1",
            "user_id": "owner-001",
            "name": "Owner One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("OwnerPass123"),
            "caregivers": [],
        }
    }
    target_users = {
        "viewer-001": {
            "user_id": "viewer-001",
            "name": "Viewer One",
            "phone_number": "+84987654322",
            "role": "user",
            "is_active": True,
        }
    }
    links = {
        "owner-001": {"device_id": "dev-001", "user_id": "owner-001", "link_role": "owner"},
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Wristband 1", "device_type": "wrist"}

    async def fake_get_device_link(device_id, user_id):
        return links.get(user_id)

    async def fake_get_user(user_id):
        return target_users.get(user_id)

    async def fake_upsert_device_link(device_id, user_id, link_role, linked_by):
        links[user_id] = {
            "device_id": device_id,
            "user_id": user_id,
            "link_role": link_role,
            "linked_by": linked_by,
        }
        return "linked"

    async def fake_delete_device_link(device_id, user_id):
        return links.pop(user_id, None) is not None

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(app_module.db, "upsert_device_link", fake_upsert_device_link)
    monkeypatch.setattr(app_module.db, "delete_device_link", fake_delete_device_link)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "OwnerPass123"},
    )
    token = login.json()["access_token"]

    add_response = await client.post(
        "/api/v1/devices/dev-001/viewers",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "viewer-001"},
    )
    remove_response = await client.delete(
        "/api/v1/devices/dev-001/viewers/viewer-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert add_response.status_code == 200
    assert add_response.json() == {
        "status": "linked",
        "device_id": "dev-001",
        "user_id": "viewer-001",
        "link_role": "viewer",
    }
    assert remove_response.status_code == 200
    assert remove_response.json() == {
        "status": "success",
        "device_id": "dev-001",
        "user_id": "viewer-001",
    }


@pytest.mark.asyncio
async def test_viewer_cannot_add_viewer(client, app_module, monkeypatch):
    users = {
        "viewer-001": {
            "_id": "1",
            "user_id": "viewer-001",
            "name": "Viewer One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("ViewerPass123"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Wristband 1", "device_type": "wrist"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "viewer"}

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "ViewerPass123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/dev-001/viewers",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_id": "viewer-002"},
    )

    assert login.status_code == 200
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_remove_viewer(client, app_module, monkeypatch):
    users = {
        "owner-001": {
            "_id": "1",
            "user_id": "owner-001",
            "name": "Owner One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("OwnerPass123"),
            "caregivers": [],
        }
    }
    links = {
        "owner-001": {"device_id": "dev-001", "user_id": "owner-001", "link_role": "owner"},
        "viewer-001": {"device_id": "dev-001", "user_id": "viewer-001", "link_role": "viewer"},
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Wristband 1", "device_type": "wrist"}

    async def fake_get_device_link(device_id, user_id):
        return links.get(user_id)

    async def fake_delete_device_link(device_id, user_id):
        return links.pop(user_id, None) is not None

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "delete_device_link", fake_delete_device_link)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "OwnerPass123"},
    )
    token = login.json()["access_token"]

    response = await client.delete(
        "/api/v1/devices/dev-001/viewers/viewer-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "device_id": "dev-001",
        "user_id": "viewer-001",
    }


@pytest.mark.asyncio
async def test_viewer_cannot_request_ecg(client, app_module, monkeypatch):
    users = {
        "viewer-001": {
            "_id": "1",
            "user_id": "viewer-001",
            "name": "Viewer One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("ViewerPass123"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Chest 1", "device_type": "chest"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "viewer"}

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "ViewerPass123"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/dev-001/ecg/request",
        headers={"Authorization": f"Bearer {token}"},
        json={"duration_seconds": 10, "sampling_rate": 250},
    )

    assert login.status_code == 200
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_access_latest_history_summary_and_ecg(client, app_module, monkeypatch):
    users = {
        "viewer-001": {
            "_id": "1",
            "user_id": "viewer-001",
            "name": "Viewer One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("ViewerPass123"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Chest 1", "device_type": "chest", "status": "active"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "viewer"}

    async def fake_get_latest_reading(device_id):
        return {
            "_id": "reading-001",
            "device_id": device_id,
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 82, "spo2": 98},
        }

    async def fake_get_readings_by_device(device_id, start_time=None, end_time=None, limit=100):
        return [
            {
                "_id": "reading-002",
                "device_id": device_id,
                "timestamp": 1771763000.12,
                "vitals": {"heart_rate": 82, "spo2": 98, "temperature": 36.7},
            }
        ]

    async def fake_get_device_ecg_readings(device_id, quality_filter=None, limit=10):
        return [
            {
                "_id": "ecg-001",
                "device_id": device_id,
                "timestamp": 1771763000.12,
                "ecg": {"quality": quality_filter or "good", "waveform": [0.1, 0.2, 0.1]},
            }
        ]

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_latest_reading", fake_get_latest_reading)
    monkeypatch.setattr(app_module.db, "get_readings_by_device", fake_get_readings_by_device)
    monkeypatch.setattr(app_module.db, "get_device_ecg_readings", fake_get_device_ecg_readings)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "ViewerPass123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    latest = await client.get("/api/v1/devices/dev-001/latest", headers=headers)
    history = await client.get("/api/v1/devices/dev-001/history", headers=headers)
    summary = await client.get("/api/v1/devices/dev-001/summary", headers=headers)
    ecg = await client.get("/api/v1/devices/dev-001/ecg", headers=headers)

    assert login.status_code == 200
    assert latest.status_code == 200
    assert history.status_code == 200
    assert summary.status_code == 200
    assert ecg.status_code == 200
    assert latest.json()["device_id"] == "dev-001"
    assert history.json()["device_id"] == "dev-001"
    assert summary.json()["device_id"] == "dev-001"
    assert ecg.json()["device_id"] == "dev-001"


@pytest.mark.asyncio
async def test_linked_users_returns_link_roles(client, app_module, monkeypatch):
    users = {
        "owner-001": {
            "_id": "1",
            "user_id": "owner-001",
            "name": "Owner One",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("OwnerPass123"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Wristband 1", "device_type": "wrist", "status": "active"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}

    async def fake_list_users_for_device(device_id):
        return [
            {
                "user_id": "owner-001",
                "name": "Owner One",
                "phone_number": "+84987654321",
                "link_role": "owner",
            },
            {
                "user_id": "viewer-001",
                "name": "Viewer One",
                "phone_number": "+84987654322",
                "link_role": "viewer",
            },
        ]

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "list_users_for_device", fake_list_users_for_device)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "OwnerPass123"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/devices/dev-001/linked-users",
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert login.status_code == 200
    assert response.status_code == 200
    assert body["device_id"] == "dev-001"
    assert body["count"] == 2
    assert body["items"][0]["link_role"] == "owner"
    assert body["items"][1]["link_role"] == "viewer"


@pytest.mark.asyncio
async def test_create_user_rejects_admin_api_key_when_bootstrap_disabled(client, app_module, monkeypatch):
    async def fake_create_user(doc):
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "create_user", fake_create_user)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

    payload = {
        "user_id": "patient-001",
        "name": "Patient One",
        "role": "patient",
        "password": "VeryStrongPass1",
    }

    forbidden = await client.post("/api/v1/users", json=payload, headers={"X-API-Key": "wrong-key"})
    disabled = await client.post(
        "/api/v1/users",
        json=payload,
        headers={"X-API-Key": app_module.settings.admin_api_key},
    )

    assert forbidden.status_code == 403
    assert disabled.status_code == 403


@pytest.mark.asyncio
async def test_create_user_allows_admin_api_key_when_bootstrap_enabled(client, app_module, monkeypatch):
    async def fake_create_user(doc):
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "create_user", fake_create_user)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)
    monkeypatch.setattr(app_module.settings, "allow_admin_api_key_bootstrap", True)

    payload = {
        "user_id": "patient-001",
        "name": "Patient One",
        "role": "patient",
        "password": "VeryStrongPass1",
    }

    allowed = await client.post(
        "/api/v1/users",
        json=payload,
        headers={"X-API-Key": app_module.settings.admin_api_key},
    )

    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_patient_cannot_access_other_user(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        },
        "patient-002": {
            "_id": "2",
            "user_id": "patient-002",
            "name": "Patient Two",
            "phone_number": "+84987654322",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass2"),
            "caregivers": [],
        },
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_user(user_id):
        user = users.get(user_id)
        if not user:
            return None
        sanitized = dict(user)
        sanitized.pop("password_hash", None)
        return sanitized

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/users/patient-002",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_users_with_shared_device_access_can_view_each_other(client, app_module, monkeypatch):
    users = {
        "user-001": {
            "_id": "10",
            "user_id": "user-001",
            "name": "User One",
            "phone_number": "+84987654323",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("SharedPass1"),
            "caregivers": [],
        },
        "user-002": {
            "_id": "11",
            "user_id": "user-002",
            "name": "User Two",
            "phone_number": "+84987654321",
            "role": "user",
            "is_active": True,
            "password_hash": hash_password("OtherPass1"),
            "caregivers": [],
        },
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_user(user_id):
        user = users.get(user_id)
        if not user:
            return None
        sanitized = dict(user)
        sanitized.pop("password_hash", None)
        return sanitized

    async def fake_users_share_device_access(actor_user_id, target_user_id):
        return actor_user_id == "user-001" and target_user_id == "user-002"

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(app_module.db, "users_share_device_access", fake_users_share_device_access)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654323", "password": "SharedPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/users/user-002",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["user_id"] == "user-002"
