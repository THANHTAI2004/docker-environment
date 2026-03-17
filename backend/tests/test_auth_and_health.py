from datetime import datetime, timedelta, timezone

import jwt
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
        "role",
        "scopes",
    }
    assert isinstance(body["scopes"], list)
    assert body["user_id"] == "patient-001"
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_creates_patient_with_normalized_phone(client, app_module, monkeypatch):
    created = {}

    async def fake_phone_exists(phone_number):
        return phone_number in created

    async def fake_generate_patient_user_id():
        return "patient-a1b2c3d4"

    async def fake_create_user_with_phone(doc):
        created[doc["phone_number"]] = dict(doc)
        return True

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "phone_exists", fake_phone_exists)
    monkeypatch.setattr(app_module.db, "generate_patient_user_id", fake_generate_patient_user_id)
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
    assert body == {"status": "success", "user_id": "patient-a1b2c3d4"}
    assert isinstance(body["status"], str)
    assert isinstance(body["user_id"], str)
    assert saved_user["name"] == "Dang Thanh Tai"
    assert saved_user["phone_number"] == "+84987654321"
    assert saved_user["date_of_birth"] == "2004-02-01"
    assert saved_user["role"] == "patient"
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
    assert {"user_id", "name", "phone_number", "date_of_birth", "role", "is_active"} <= set(body.keys())
    assert isinstance(body["user_id"], str)
    assert isinstance(body["name"], str)
    assert isinstance(body["phone_number"], str)
    assert isinstance(body["is_active"], bool)
    assert body["user_id"] == "patient-001"
    assert body["phone_number"] == "+84987654321"
    assert body["date_of_birth"] == "2004-02-01"
    assert body["role"] == "patient"
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
                        "role": "patient",
                        "phone_number": "+84987654321",
                        "link_role": "owner",
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
    assert "deviceId" not in body["items"][0]


@pytest.mark.asyncio
async def test_linked_user_can_access_device(client, app_module, monkeypatch):
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
            return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}
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
async def test_caregiver_can_access_assigned_patient(client, app_module, monkeypatch):
    users = {
        "caregiver-001": {
            "_id": "10",
            "user_id": "caregiver-001",
            "name": "Caregiver One",
            "phone_number": "+84987654323",
            "role": "caregiver",
            "is_active": True,
            "password_hash": hash_password("CaregiverPass1"),
            "caregivers": [],
        },
        "patient-001": {
            "_id": "11",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": ["caregiver-001"],
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
        json={"phone_number": "0987654323", "password": "CaregiverPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/users/patient-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["user_id"] == "patient-001"
