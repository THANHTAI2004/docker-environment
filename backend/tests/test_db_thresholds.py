import importlib

import pytest


db_module = importlib.import_module("app.db")


class _FakeUpdateResult:
    def __init__(self, matched_count):
        self.matched_count = matched_count


class _FakeDevicesCollection:
    def __init__(self):
        self.doc = {
            "device_id": "dev-001",
            "settings": {"alert_thresholds": {"spo2_low": 92.0, "hr_high": 115}},
            "alert_thresholds": {"spo2_low": 92.0, "hr_high": 115},
        }

    async def find_one(self, query, projection=None):
        if query.get("device_id") != self.doc["device_id"]:
            return None
        return {
            "device_id": self.doc["device_id"],
            "settings": {"alert_thresholds": dict(self.doc["settings"]["alert_thresholds"])},
            "alert_thresholds": dict(self.doc["alert_thresholds"]),
        }

    async def update_one(self, query, update):
        if query.get("device_id") != self.doc["device_id"]:
            return _FakeUpdateResult(0)
        set_doc = update["$set"]
        thresholds = dict(set_doc["settings.alert_thresholds"])
        self.doc["settings"] = {"alert_thresholds": thresholds}
        self.doc["alert_thresholds"] = dict(set_doc["alert_thresholds"])
        self.doc["last_seen"] = set_doc["last_seen"]
        return _FakeUpdateResult(1)


@pytest.mark.asyncio
async def test_update_device_thresholds_merges_partial_payload_into_existing_overrides():
    database = db_module.Database()
    fake_devices = _FakeDevicesCollection()
    database.devices = fake_devices

    success = await database.update_device_thresholds(
        "dev-001",
        {"rr_low": 9, "hr_high": 120},
    )

    assert success is True
    assert fake_devices.doc["settings"]["alert_thresholds"] == {
        "spo2_low": 92.0,
        "hr_high": 120,
        "rr_low": 9,
    }
    assert fake_devices.doc["alert_thresholds"] == fake_devices.doc["settings"]["alert_thresholds"]

