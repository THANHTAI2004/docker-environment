import pytest


@pytest.mark.asyncio
async def test_live_returns_200(client):
    response = await client.get("/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_metrics_returns_403_when_token_or_ip_invalid(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.settings, "expose_metrics", True)
    monkeypatch.setattr(app_module.settings, "metrics_token", "metrics-secret")
    monkeypatch.setattr(app_module.settings, "metrics_allow_ips", "10.0.0.1")

    response = await client.get("/metrics")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_metrics_returns_200_with_valid_token_and_allowed_ip(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.settings, "expose_metrics", True)
    monkeypatch.setattr(app_module.settings, "metrics_token", "metrics-secret")
    monkeypatch.setattr(app_module.settings, "metrics_allow_ips", "127.0.0.1,::1,localhost,testclient")

    response = await client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})

    assert response.status_code == 200
    assert "wearable_http_requests_total" in response.text
    assert "wearable_esp_readings_received_total" in response.text
