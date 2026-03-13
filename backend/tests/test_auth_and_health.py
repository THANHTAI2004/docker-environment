import pytest

from app.utils.auth import hash_password


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
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_latest_reading", fake_get_latest_reading)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "patient-001", "password": "PatientPass1"},
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
async def test_device_summary_tolerates_small_future_clock_skew(client, app_module, monkeypatch):
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
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "get_readings_by_device", fake_get_readings_by_device)
    monkeypatch.setattr(app_module.settings, "device_clock_skew_tolerance_seconds", 300)
    monkeypatch.setattr("time.time", lambda: 1000.0)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "patient-001", "password": "PatientPass1"},
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
                "link_role": "owner",
            }
        ]

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "list_devices_for_user", fake_list_devices_for_user)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "patient-001", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/me/devices",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["device_id"] == "dev-001"


@pytest.mark.asyncio
async def test_linked_user_can_access_device(client, app_module, monkeypatch):
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
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "patient-001", "password": "PatientPass1"},
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
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        },
        "patient-002": {
            "_id": "2",
            "user_id": "patient-002",
            "name": "Patient Two",
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
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "patient-001", "password": "PatientPass1"},
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
            "role": "caregiver",
            "is_active": True,
            "password_hash": hash_password("CaregiverPass1"),
            "caregivers": [],
        },
        "patient-001": {
            "_id": "11",
            "user_id": "patient-001",
            "name": "Patient One",
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
    monkeypatch.setattr(app_module.db, "get_user", fake_get_user)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "caregiver-001", "password": "CaregiverPass1"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/users/patient-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["user_id"] == "patient-001"
