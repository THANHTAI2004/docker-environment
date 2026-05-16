import importlib

import pytest


esp_module = importlib.import_module("app.api.esp")


@pytest.mark.asyncio
async def test_esp_ingest_accepts_temperature_below_30c(client, app_module, monkeypatch):
    captured = {}

    async def fake_require_device_token():
        return {"device_id": "dev-low-temp"}

    async def fake_process_health_reading(reading):
        captured["reading"] = dict(reading)
        return True

    app_module.app.dependency_overrides[esp_module.require_device_token] = fake_require_device_token
    monkeypatch.setattr(esp_module.health_service, "process_health_reading", fake_process_health_reading)

    try:
        response = await client.post(
            "/api/v1/esp/devices/dev-low-temp/readings",
            json={
                "timestamp": 1771763000.12,
                "vitals": {"heart_rate": 72, "spo2": 98, "temperature": 29.4},
            },
        )
    finally:
        app_module.app.dependency_overrides.pop(esp_module.require_device_token, None)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "device_id": "dev-low-temp"}
    assert captured["reading"]["device_id"] == "dev-low-temp"
    assert captured["reading"]["vitals"]["temperature"] == 29.4


@pytest.mark.asyncio
async def test_esp_ingest_accepts_new_three_board_payload_shapes(client, app_module, monkeypatch):
    captured = {}

    async def fake_require_device_token():
        return {"device_id": "dev-3board"}

    async def fake_process_health_reading(reading):
        captured["reading"] = dict(reading)
        return True

    app_module.app.dependency_overrides[esp_module.require_device_token] = fake_require_device_token
    monkeypatch.setattr(esp_module.health_service, "process_health_reading", fake_process_health_reading)

    try:
        response = await client.post(
            "/api/v1/esp/devices/dev-3board/readings",
            json={
                "timestamp": 1715670000.123,
                "device_type": "chest",
                "payload_type": "fall_alert",
                "fall": True,
                "fall_state": "DETECTED",
                "metadata": {
                    "schema_version": "2026-04-new-3board",
                    "signal_strength": -65,
                    "bridge_quality": 85,
                    "bridge_fresh": True,
                    "c3_online": True,
                    "mpu_online": True,
                    "sensor_state": "ACTIVE",
                    "device_name": "Vitals-1234",
                    "sensor_id": "SEN-XXXXXXXX",
                },
            },
        )
    finally:
        app_module.app.dependency_overrides.pop(esp_module.require_device_token, None)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "device_id": "dev-3board"}
    assert captured["reading"]["device_id"] == "dev-3board"
    assert captured["reading"]["payload_type"] == "fall_alert"
    assert captured["reading"]["fall"] is True
    assert captured["reading"]["fall_phase"] == "DETECTED"
    assert captured["reading"]["metadata"]["schema_version"] == "2026-04-new-3board"
