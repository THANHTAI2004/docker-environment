import pytest


@pytest.mark.asyncio
async def test_live_returns_200(client):
    response = await client.get("/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_metrics_returns_403_when_token_or_ip_invalid(client, app_module, monkeypatch):
    async def fake_count_pending_commands():
        return 2

    async def fake_count_commands_by_status():
        return {"queued": 1, "dispatched": 1}

    monkeypatch.setattr(app_module.settings, "expose_metrics", True)
    monkeypatch.setattr(app_module.settings, "metrics_token", "metrics-secret")
    monkeypatch.setattr(app_module.settings, "metrics_allow_ips", "10.0.0.1")
    monkeypatch.setattr(app_module.db, "count_pending_commands", fake_count_pending_commands)
    monkeypatch.setattr(app_module.db, "count_commands_by_status", fake_count_commands_by_status)

    response = await client.get("/metrics")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_metrics_returns_200_with_valid_token_and_allowed_ip(client, app_module, monkeypatch):
    async def fake_count_pending_commands():
        return 3

    async def fake_count_commands_by_status():
        return {"queued": 2, "dispatched": 1, "failed": 4}

    monkeypatch.setattr(app_module.settings, "expose_metrics", True)
    monkeypatch.setattr(app_module.settings, "metrics_token", "metrics-secret")
    monkeypatch.setattr(app_module.settings, "metrics_allow_ips", "127.0.0.1,::1,localhost,testclient")
    monkeypatch.setattr(app_module.db, "count_pending_commands", fake_count_pending_commands)
    monkeypatch.setattr(app_module.db, "count_commands_by_status", fake_count_commands_by_status)

    response = await client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"})

    assert response.status_code == 200
    assert "wearable_device_commands_pending" in response.text
    assert "wearable_device_commands_current" in response.text
