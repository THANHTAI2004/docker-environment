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
async def test_create_user_requires_admin_api_key(client, app_module, monkeypatch):
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
    allowed = await client.post(
        "/api/v1/users",
        json=payload,
        headers={"X-API-Key": app_module.settings.admin_api_key},
    )

    assert forbidden.status_code == 403
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
