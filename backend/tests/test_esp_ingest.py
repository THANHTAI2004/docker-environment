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
