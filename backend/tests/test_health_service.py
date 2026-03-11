import importlib

import pytest

from app.services.health_service import health_service

health_service_module = importlib.import_module("app.services.health_service")


@pytest.mark.asyncio
async def test_duplicate_reading_does_not_generate_duplicate_alert(monkeypatch):
    calls = {"alerts": 0}

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "wrist"}

    async def fake_insert_health_reading(doc):
        return "duplicate"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        return True

    async def fake_get_user(user_id):
        return {"user_id": user_id, "alert_thresholds": {}}

    async def fake_check_health_reading(doc, thresholds):
        calls["alerts"] += 1
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.db, "get_user", fake_get_user)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-001",
            "user_id": "patient-001",
            "seq": 101,
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 180},
        }
    )

    assert success is True
    assert calls["alerts"] == 0
