import importlib

import pytest


alert_service_module = importlib.import_module("app.services.alert_service")


@pytest.mark.asyncio
async def test_check_health_reading_inserts_alert_and_triggers_push(monkeypatch):
    captured = {}

    async def fake_get_alert_recipient_user_ids(device_id):
        return ["owner-001", "viewer-001"]

    async def fake_insert_alert(doc):
        captured["inserted_alert"] = dict(doc)
        return "alert-001"

    async def fake_send_alert_notification(alert):
        captured["push_alert"] = dict(alert)
        return {"status": "sent", "success_count": 1, "failure_count": 0}

    monkeypatch.setattr(alert_service_module.db, "get_alert_recipient_user_ids", fake_get_alert_recipient_user_ids)
    monkeypatch.setattr(alert_service_module.db, "insert_alert", fake_insert_alert)
    monkeypatch.setattr(
        alert_service_module.push_notification_service,
        "send_alert_notification",
        fake_send_alert_notification,
    )

    alerts = await alert_service_module.alert_service.check_health_reading(
        {
            "device_id": "dev-001",
            "timestamp": 1771763000.12,
            "vitals": {"spo2": 82},
        },
        {"spo2_critical": 85},
    )

    assert len(alerts) == 1
    assert captured["inserted_alert"]["alert_type"] == "spo2_low"
    assert captured["inserted_alert"]["message"] == "SpO2 xuống mức nguy hiểm (82%)"
    assert captured["inserted_alert"]["recipient_user_ids"] == ["owner-001", "viewer-001"]
    assert captured["push_alert"]["id"] == "alert-001"
    assert captured["push_alert"]["recipient_user_ids"] == ["owner-001", "viewer-001"]


@pytest.mark.asyncio
async def test_fall_detection_creates_critical_alert_and_triggers_push(monkeypatch):
    captured = {}

    async def fake_get_alert_recipient_user_ids(device_id):
        return ["owner-001"]

    async def fake_insert_alert(doc):
        captured["inserted_alert"] = dict(doc)
        return "alert-fall-001"

    async def fake_send_alert_notification(alert):
        captured["push_alert"] = dict(alert)
        return {"status": "sent", "success_count": 1, "failure_count": 0}

    monkeypatch.setattr(alert_service_module.db, "get_alert_recipient_user_ids", fake_get_alert_recipient_user_ids)
    monkeypatch.setattr(alert_service_module.db, "insert_alert", fake_insert_alert)
    monkeypatch.setattr(
        alert_service_module.push_notification_service,
        "send_alert_notification",
        fake_send_alert_notification,
    )

    alerts = await alert_service_module.alert_service.check_health_reading(
        {
            "device_id": "dev-fall-001",
            "timestamp": 1771763000.12,
            "fall": True,
            "fall_phase": "IMPACT",
            "vitals": {"heart_rate": 72, "spo2": 98},
        }
    )

    assert len(alerts) == 1
    assert captured["inserted_alert"]["alert_type"] == "fall_detected"
    assert captured["inserted_alert"]["severity"] == "critical"
    assert captured["inserted_alert"]["metric"] == "fall"
    assert captured["inserted_alert"]["message"] == "Phát hiện té ngã (va chạm)"
    assert captured["push_alert"]["id"] == "alert-fall-001"
