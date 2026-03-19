# `/api/v1/me/devices` Contract

This document defines the official response contract for `GET /api/v1/me/devices`.

## Purpose

The mobile or web app should treat this endpoint as the primary source of truth for:

- which devices belong to the current user
- whether the current user is `owner` or `viewer` on each device
- who else is linked to the same device

Device permissions are derived from `device_links` only.

## Response shape

```json
{
  "user_id": "user-001",
  "count": 1,
  "items": [
    {
      "device_id": "dev-001",
      "device_type": "wrist",
      "device_name": "ESP32 Device",
      "firmware_version": "1.0.0",
      "registered_at": "2026-03-17T10:00:00Z",
      "last_seen": "2026-03-17T10:05:00Z",
      "status": "active",
      "permission": "owner",
      "link_role": "owner",
      "linked_at": "2026-03-17T10:01:00Z",
      "linked_by": "user-001",
      "linked_users": [
        {
          "user_id": "user-001",
          "name": "User A",
          "phone_number": "+84900000001",
          "permission": "owner",
          "link_role": "owner"
        },
        {
          "user_id": "user-002",
          "name": "User B",
          "phone_number": "+84900000002",
          "permission": "viewer",
          "link_role": "viewer"
        }
      ]
    }
  ]
}
```

## Field notes

- `permission` is the canonical field for device access in the new contract.
- `link_role` is a temporary backward-compatible alias and will be removed later.
- `linked_users[].permission` is the canonical permission of each linked account on the same device.
- Valid permission values are only `owner` and `viewer`.
- Apps should not derive device permissions from `user.role`.
