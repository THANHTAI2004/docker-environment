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

    def sort(self, key_or_list, direction=None):
        if isinstance(key_or_list, list):
            sort_fields = list(reversed(key_or_list))
        else:
            sort_fields = [(key_or_list, direction if direction is not None else 1)]

        for field, sort_direction in sort_fields:
            reverse = sort_direction == -1
            self._docs.sort(key=lambda doc: (doc.get(field) is None, doc.get(field)), reverse=reverse)
        return self

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
    body = response.json()
    assert body["status"] == "already_queued"
    assert body["delivery"] == "rest_polling"
    assert body["command_id"] == "cmd-001"
    assert body["request_id"] == "req-001"


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
async def test_request_ecg_returns_queued_contract(client, app_module, monkeypatch):
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
        return {"status": "queued", "command_id": "cmd-002"}

    async def fake_insert_audit_log(doc):
        return True

    monkeypatch.setattr(app_module.db, "get_user_auth", fake_get_user_auth)
    monkeypatch.setattr(app_module.db, "get_user_auth_by_phone", _make_phone_lookup(users))
    monkeypatch.setattr(app_module.db, "get_device", fake_get_device)
    monkeypatch.setattr(app_module.db, "get_device_link", fake_get_device_link)
    monkeypatch.setattr(app_module.db, "enqueue_device_command", fake_enqueue_device_command)
    monkeypatch.setattr(app_module.db, "insert_audit_log", fake_insert_audit_log)

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

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "queued"
    assert body["delivery"] == "rest_polling"
    assert body["command_id"] == "cmd-002"
    assert isinstance(body["request_id"], str)
    assert isinstance(body["expires_at"], str)


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


@pytest.mark.asyncio
async def test_list_devices_for_user_includes_linked_users():
    db = Database()
    db.device_links = _FakeCollection(
        [
            {
                "_id": "link-1",
                "device_id": "dev-001",
                "user_id": "patient-001",
                "link_role": "owner",
                "linked_at": "2026-03-17T10:01:00Z",
                "linked_by": "admin-001",
            },
            {
                "_id": "link-2",
                "device_id": "dev-001",
                "user_id": "caregiver-001",
                "link_role": "viewer",
                "linked_at": "2026-03-17T10:02:00Z",
                "linked_by": "admin-001",
            },
        ]
    )
    db.devices = _FakeCollection(
        [
            {
                "_id": "device-1",
                "device_id": "dev-001",
                "device_type": "wrist",
                "device_name": "Wristband 1",
                "firmware_version": "1.0.0",
                "status": "active",
            }
        ]
    )
    db.users = _FakeCollection(
        [
            {
                "_id": "user-1",
                "user_id": "patient-001",
                "name": "Patient One",
                "role": "patient",
                "phone_number": "+84987654321",
            },
            {
                "_id": "user-2",
                "user_id": "caregiver-001",
                "name": "Caregiver One",
                "role": "caregiver",
                "phone_number": "+84987654323",
            },
        ]
    )

    items = await db.list_devices_for_user("patient-001")

    assert len(items) == 1
    assert items[0]["device_id"] == "dev-001"
    assert items[0]["link_role"] == "owner"
    assert items[0]["linked_users"] == [
        {
            "user_id": "patient-001",
            "name": "Patient One",
            "phone_number": "+84987654321",
            "link_role": "owner",
        },
        {
            "user_id": "caregiver-001",
            "name": "Caregiver One",
            "phone_number": "+84987654323",
            "link_role": "viewer",
        },
    ]


@pytest.mark.asyncio
async def test_list_users_for_device_returns_phone_number_and_link_role():
    db = Database()
    db.device_links = _FakeCollection(
        [
            {
                "_id": "link-1",
                "device_id": "dev-001",
                "user_id": "owner-001",
                "link_role": "owner",
                "linked_at": "2026-03-17T10:01:00Z",
                "linked_by": "owner-001",
            },
            {
                "_id": "link-2",
                "device_id": "dev-001",
                "user_id": "viewer-001",
                "link_role": "caregiver",
                "linked_at": "2026-03-17T10:02:00Z",
                "linked_by": "owner-001",
            },
        ]
    )
    db.users = _FakeCollection(
        [
            {
                "_id": "user-1",
                "user_id": "owner-001",
                "name": "Owner One",
                "role": "user",
                "phone_number": "+84987654321",
            },
            {
                "_id": "user-2",
                "user_id": "viewer-001",
                "name": "Viewer One",
                "role": "user",
                "phone_number": "+84987654322",
            },
        ]
    )

    items = await db.list_users_for_device("dev-001")

    assert items == [
        {
            "user_id": "owner-001",
            "name": "Owner One",
            "phone_number": "+84987654321",
            "link_role": "owner",
            "linked_at": "2026-03-17T10:01:00Z",
            "linked_by": "owner-001",
        },
        {
            "user_id": "viewer-001",
            "name": "Viewer One",
            "phone_number": "+84987654322",
            "link_role": "viewer",
            "linked_at": "2026-03-17T10:02:00Z",
            "linked_by": "owner-001",
        },
    ]


@pytest.mark.asyncio
async def test_alert_recipients_include_owner_and_viewer_links():
    db = Database()
    db.device_links = _FakeCollection(
        [
            {"_id": "1", "device_id": "dev-001", "user_id": "owner-001", "link_role": "owner"},
            {"_id": "2", "device_id": "dev-001", "user_id": "viewer-001", "link_role": "viewer"},
            {"_id": "3", "device_id": "dev-001", "user_id": "legacy-001", "link_role": "caregiver"},
        ]
    )

    recipients = await db.get_alert_recipient_user_ids("dev-001")

    assert recipients == ["owner-001", "viewer-001", "legacy-001"]
