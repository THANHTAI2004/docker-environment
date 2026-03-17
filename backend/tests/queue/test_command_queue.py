from datetime import datetime, timedelta

import pytest

from app.db import (
    COMMAND_STATUS_ACKED,
    COMMAND_STATUS_COMPLETED,
    COMMAND_STATUS_DISPATCHED,
    COMMAND_STATUS_FAILED,
    COMMAND_STATUS_QUEUED,
    Database,
)
from app.utils.auth import hash_password


def _make_phone_lookup(users):
    async def fake_get_user_auth_by_phone(phone_number):
        for user in users.values():
            if user.get("phone_number") == phone_number:
                return user
        return None

    return fake_get_user_auth_by_phone


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._index = 0

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        value = self._docs[self._index]
        self._index += 1
        return dict(value)


class _FakeCollection:
    def __init__(self, docs):
        self.docs = [dict(doc) for doc in docs]

    def _match_value(self, actual, expected):
        if isinstance(expected, dict):
            for op, value in expected.items():
                if op == "$in" and actual not in value:
                    return False
                if op == "$lte" and not (actual is not None and actual <= value):
                    return False
                if op == "$gt" and not (actual is not None and actual > value):
                    return False
                if op == "$exists" and ((actual is not None) != value):
                    return False
            return True
        return actual == expected

    def _matches(self, doc, query):
        for key, value in query.items():
            if key == "$or":
                if not any(self._matches(doc, item) for item in value):
                    return False
                continue
            if not self._match_value(doc.get(key), value):
                return False
        return True

    def find(self, query):
        return _AsyncCursor(doc for doc in self.docs if self._matches(doc, query))

    async def update_one(self, query, update):
        matched = 0
        modified = 0
        for doc in self.docs:
            if self._matches(doc, query):
                matched += 1
                for field, value in update.get("$set", {}).items():
                    doc[field] = value
                modified += 1
                break

        class Result:
            matched_count = matched
            modified_count = modified

        return Result()


@pytest.mark.asyncio
async def test_request_ecg_returns_already_queued_for_duplicate(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "chest", "device_name": "Chest 1"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}

    async def fake_enqueue_device_command(doc):
        return {
            "status": "duplicate",
            "command_id": "cmd-001",
            "request_id": "req-001",
            "expires_at": datetime.utcnow() + timedelta(minutes=5),
        }

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "enqueue_device_command", fake_enqueue_device_command)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/dev-001/ecg/request",
        headers={"Authorization": f"Bearer {token}"},
        json={"duration_seconds": 10, "sampling_rate": 250},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "already_queued"


@pytest.mark.asyncio
async def test_request_ecg_returns_409_when_pending_limit_reached(client, app_module, monkeypatch):
    users = {
        "patient-001": {
            "_id": "1",
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "role": "patient",
            "is_active": True,
            "password_hash": hash_password("PatientPass1"),
            "caregivers": [],
        }
    }

    async def fake_get_user_auth(user_id):
        return users.get(user_id)

    async def fake_get_device(device_id):
        return {"device_id": device_id, "device_type": "chest", "device_name": "Chest 1"}

    async def fake_get_device_link(device_id, user_id):
        return {"device_id": device_id, "user_id": user_id, "link_role": "owner"}

    async def fake_enqueue_device_command(doc):
        return {"status": "limit_reached", "pending_count": 3}

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "enqueue_device_command", fake_enqueue_device_command)

    login = await client.post(
        "/api/v1/auth/login",
        json={"phone_number": "0987654321", "password": "PatientPass1"},
    )
    token = login.json()["access_token"]

    response = await client.post(
        "/api/v1/devices/dev-001/ecg/request",
        headers={"Authorization": f"Bearer {token}"},
        json={"duration_seconds": 10, "sampling_rate": 250},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_esp_ack_done_maps_to_completed_lifecycle(client, app_module, monkeypatch):
    async def fake_get_device_by_token_hash(device_id, token_hash):
        return {"device_id": device_id, "device_type": "chest"}

    async def fake_acknowledge_device_command(device_id, command_id, status, message=None):
        return status == "done"

    monkeypatch.setattr(app_module.db, "get_device_by_token_hash", fake_get_device_by_token_hash)
    monkeypatch.setattr(app_module.db, "acknowledge_device_command", fake_acknowledge_device_command)

    response = await client.post(
        "/api/v1/esp/devices/dev-001/commands/cmd-001/ack",
        headers={"X-Device-Token": "device-token"},
        json={"status": "done", "message": "ok"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.asyncio
async def test_recover_stale_device_commands_requeues_timed_out_dispatch(monkeypatch):
    db = Database()
    now = datetime.utcnow()
    db.device_commands = _FakeCollection(
        [
            {
                "_id": "cmd-1",
                "command": "ecg_request",
                "status": COMMAND_STATUS_DISPATCHED,
                "dispatch_count": 1,
                "dispatched_at": now - timedelta(seconds=120),
                "expires_at": now + timedelta(minutes=5),
            }
        ]
    )

    summary = await db.recover_stale_device_commands()

    assert summary["requeued"] == 1
    assert db.device_commands.docs[0]["status"] == COMMAND_STATUS_QUEUED
    assert db.device_commands.docs[0]["next_retry_at"] > now


@pytest.mark.asyncio
async def test_recover_stale_device_commands_fails_after_retry_limit(monkeypatch):
    db = Database()
    now = datetime.utcnow()
    db.device_commands = _FakeCollection(
        [
            {
                "_id": "cmd-2",
                "command": "ecg_request",
                "status": COMMAND_STATUS_DISPATCHED,
                "dispatch_count": 3,
                "dispatched_at": now - timedelta(seconds=120),
                "expires_at": now + timedelta(minutes=5),
            },
            {
                "_id": "cmd-3",
                "command": "ecg_request",
                "status": COMMAND_STATUS_ACKED,
                "dispatch_count": 1,
                "acked_at": now - timedelta(seconds=5),
                "expires_at": now + timedelta(minutes=5),
            },
        ]
    )

    summary = await db.recover_stale_device_commands()

    assert summary["failed"] == 1
    assert summary["completed"] == 1
    assert db.device_commands.docs[0]["status"] == COMMAND_STATUS_FAILED
    assert db.device_commands.docs[1]["status"] == COMMAND_STATUS_COMPLETED
