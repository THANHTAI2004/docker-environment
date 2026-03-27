import importlib

import pytest


push_service_module = importlib.import_module("app.services.push_notification_service")


@pytest.mark.asyncio
async def test_push_notification_is_suppressed_during_cooldown_without_escalation(monkeypatch):
    captured = {}

    async def fake_get_recent_dispatched_alert(device_id, alert_type, timestamp, cooldown_seconds):
        captured["cooldown_args"] = (device_id, alert_type, timestamp, cooldown_seconds)
        return {"_id": "prev-alert", "severity": "warning"}

    async def fake_update_alert_push_status(alert_id, fields):
        captured["status_update"] = {"alert_id": alert_id, "fields": dict(fields)}
        return True

    monkeypatch.setattr(push_service_module.settings, "push_notifications_enabled", True)
    monkeypatch.setattr(
        push_service_module.db,
        "get_recent_dispatched_alert",
        fake_get_recent_dispatched_alert,
    )
    monkeypatch.setattr(
        push_service_module.db,
        "update_alert_push_status",
        fake_update_alert_push_status,
    )

    result = await push_service_module.push_notification_service.send_alert_notification(
        {
            "id": "alert-002",
            "device_id": "dev-001",
            "alert_type": "hr_high",
            "severity": "warning",
            "timestamp": 1771763000.12,
            "recipient_user_ids": ["owner-001"],
        }
    )

    assert result["status"] == "suppressed_cooldown"
    assert captured["status_update"]["alert_id"] == "alert-002"
    assert captured["status_update"]["fields"]["push_status"] == "suppressed_cooldown"


@pytest.mark.asyncio
async def test_push_notification_is_sent_when_alert_escalates(monkeypatch):
    captured = {"status_updates": []}

    async def fake_get_recent_dispatched_alert(device_id, alert_type, timestamp, cooldown_seconds):
        return {"_id": "prev-alert", "severity": "warning"}

    async def fake_list_active_push_tokens(user_ids):
        return [
            {
                "user_id": "owner-001",
                "installation_id": "inst-001",
                "fcm_token": "token-001",
                "platform": "android",
                "is_active": True,
            }
        ]

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_name": "Shared Wrist 401"}

    async def fake_update_alert_push_status(alert_id, fields):
        captured["status_updates"].append({"alert_id": alert_id, "fields": dict(fields)})
        return True

    async def fake_deactivate_push_tokens_by_fcm_tokens(fcm_tokens):
        captured["deactivated_tokens"] = list(fcm_tokens)
        return 0

    async def fake_dispatch_multicast(tokens, title, body, data):
        captured["dispatch"] = {
            "tokens": list(tokens),
            "title": title,
            "body": body,
            "data": dict(data),
        }
        return {
            "success_count": 1,
            "failure_count": 0,
            "invalid_tokens": [],
            "error_codes": [],
        }

    monkeypatch.setattr(push_service_module.settings, "push_notifications_enabled", True)
    monkeypatch.setattr(
        push_service_module.db,
        "get_recent_dispatched_alert",
        fake_get_recent_dispatched_alert,
    )
    monkeypatch.setattr(
        push_service_module.db,
        "list_active_push_tokens",
        fake_list_active_push_tokens,
    )
    monkeypatch.setattr(push_service_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(
        push_service_module.db,
        "update_alert_push_status",
        fake_update_alert_push_status,
    )
    monkeypatch.setattr(
        push_service_module.db,
        "deactivate_push_tokens_by_fcm_tokens",
        fake_deactivate_push_tokens_by_fcm_tokens,
    )
    monkeypatch.setattr(
        push_service_module.push_notification_service,
        "_dispatch_multicast",
        fake_dispatch_multicast,
    )

    result = await push_service_module.push_notification_service.send_alert_notification(
        {
            "id": "alert-003",
            "device_id": "dev-001",
            "alert_type": "hr_high",
            "severity": "critical",
            "metric": "heart_rate",
            "message": "Heart rate critically high (170 bpm)",
            "timestamp": 1771763000.12,
            "recipient_user_ids": ["owner-001"],
        }
    )

    assert result["status"] == "sent"
    assert captured["dispatch"]["tokens"] == ["token-001"]
    assert captured["dispatch"]["title"] == "CRITICAL: Shared Wrist 401"
    assert captured["dispatch"]["data"]["type"] == "health_alert"
    assert captured["dispatch"]["data"]["alert_type"] == "hr_high"
    assert captured["status_updates"][-1]["fields"]["push_status"] == "sent"
