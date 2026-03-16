import pytest

from app.utils.auth import hash_password


@pytest.mark.asyncio
async def test_patient_cannot_register_device(client, app_module, monkeypatch):
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

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "patient-001", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/register",
        headers={"Authorization": f"Bearer {token}"},
        json={"device_id": "dev-001", "device_type": "wrist", "device_name": "Wrist 1"},
    )

    assert login.status_code == 200
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_device_without_link(client, app_module, monkeypatch):
    users = {
        "admin-001": {
            "_id": "10",
            "user_id": "admin-001",
            "name": "Admin One",
            "role": "admin",
            "is_active": True,
            "password_hash": hash_password("AdminPass123"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {
            "device_id": device_id,
            "device_name": "Wrist 1",
            "device_type": "wrist",
            "status": "active",
        }

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)

    login = await client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin-001", "password": "AdminPass123"},
    )
    token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/devices/dev-001",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["device_id"] == "dev-001"
