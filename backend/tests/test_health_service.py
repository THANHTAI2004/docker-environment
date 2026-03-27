import importlib

import pytest

from app.services.health_service import health_service

health_service_module = importlib.import_module("app.services.health_service")


@pytest.mark.asyncio
async def test_duplicate_reading_does_not_generate_duplicate_alert(monkeypatch):
    calls = {"alerts": 0}

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "wrist", "alert_thresholds": {}}

    async def fake_insert_health_reading(doc):
        return "duplicate"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        return True

    async def fake_check_health_reading(doc, thresholds):
        calls["alerts"] += 1
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-001",
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 180},
        }
    )

    assert success is True
    assert calls["alerts"] == 0


@pytest.mark.asyncio
async def test_unknown_payload_fields_are_not_persisted_in_normalized_health_reading(monkeypatch):
    captured = {}

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "wrist", "alert_thresholds": {}}

    async def fake_insert_health_reading(doc):
        captured["doc"] = doc
        return "inserted"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        return True

    async def fake_check_health_reading(doc, thresholds):
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-001",
            "unexpected_field": 101,
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 72},
        }
    )

    assert success is True
    assert "unexpected_field" not in captured["doc"]


@pytest.mark.asyncio
async def test_device_uid_is_not_persisted_in_normalized_health_reading(monkeypatch):
    captured = {}

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "wrist", "alert_thresholds": {}}

    async def fake_insert_health_reading(doc):
        captured["doc"] = doc
        return "inserted"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        return True

    async def fake_check_health_reading(doc, thresholds):
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-001",
            "device_uid": "legacy-device-id",
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 72},
        }
    )

    assert success is True
    assert captured["doc"]["device_id"] == "dev-001"
    assert "device_uid" not in captured["doc"]


@pytest.mark.asyncio
async def test_missing_device_type_uses_registered_device_type_and_keeps_signal_quality(monkeypatch):
    captured = {}

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "chest", "alert_thresholds": {}}

    async def fake_insert_health_reading(doc):
        captured["doc"] = doc
        return "inserted"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        captured["metadata"] = metadata
        return True

    async def fake_check_health_reading(doc, thresholds):
        captured["alert_doc"] = doc
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-002",
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 85, "spo2": 97},
            "metadata": {"signal_strength": -58, "signal_quality": 92, "firmware_version": "fw-1.2.3"},
        }
    )

    assert success is True
    assert captured["doc"]["device_type"] == "chest"
    assert captured["doc"]["metadata"]["signal_quality"] == 92
    assert captured["doc"]["signal_quality"] == 92
    assert captured["metadata"]["signal_quality"] == 92
    assert captured["alert_doc"]["device_type"] == "chest"


@pytest.mark.asyncio
async def test_device_settings_thresholds_are_forwarded_to_alert_service(monkeypatch):
    captured = {}

    async def fake_get_device(device_id):
        return {
            "device_id": device_id,
            "device_type": "wrist",
            "settings": {"alert_thresholds": {"hr_high": 111, "spo2_low": 91.0}},
            "alert_thresholds": {"hr_high": 140},
        }

    async def fake_insert_health_reading(doc):
        captured["doc"] = doc
        return "inserted"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        return True

    async def fake_check_health_reading(doc, thresholds):
        captured["thresholds"] = thresholds
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-003",
            "timestamp": 1771763000.12,
            "vitals": {"heart_rate": 120, "spo2": 89},
        }
    )

    assert success is True
    assert captured["doc"]["device_id"] == "dev-003"
    assert captured["thresholds"] == {"hr_high": 111, "spo2_low": 91.0}


@pytest.mark.asyncio
async def test_fall_payload_and_upload_reason_are_persisted_and_forwarded(monkeypatch):
    captured = {}

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "chest", "alert_thresholds": {}}

    async def fake_insert_health_reading(doc):
        captured["doc"] = doc
        return "inserted"

    async def fake_update_device_last_seen(device_id):
        return True

    async def fake_update_device_metadata(device_id, metadata):
        captured["metadata"] = metadata
        return True

    async def fake_check_health_reading(doc, thresholds):
        captured["alert_doc"] = doc
        return []

    monkeypatch.setattr(health_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(health_service_module.db, "insert_health_reading", fake_insert_health_reading)
    monkeypatch.setattr(health_service_module.db, "update_device_last_seen", fake_update_device_last_seen)
    monkeypatch.setattr(health_service_module.db, "update_device_metadata", fake_update_device_metadata)
    monkeypatch.setattr(health_service_module.alert_service, "check_health_reading", fake_check_health_reading)

    success = await health_service.process_health_reading(
        {
            "device_id": "dev-fall-001",
            "timestamp": 1771763000.12,
            "device_type": "chest",
            "fall": True,
            "fall_phase": "IMPACT",
            "vitals": {"heart_rate": 72, "spo2": 98, "temperature": 36.7},
            "metadata": {
                "battery_level": 95,
                "signal_strength": -62,
                "signal_quality": 84,
                "upload_reason": "routine",
                "firmware_version": "esp32-s3-gateway-nimble-v1",
            },
        }
    )

    assert success is True
    assert captured["doc"]["fall"] is True
    assert captured["doc"]["fall_phase"] == "IMPACT"
    assert captured["doc"]["metadata"]["upload_reason"] == "routine"
    assert captured["doc"]["upload_reason"] == "routine"
    assert "respiratory_rate" not in captured["doc"].get("vitals", {})
    assert captured["alert_doc"]["fall"] is True
