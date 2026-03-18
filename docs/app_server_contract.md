# App Server Contract

This document defines the server-side contract for the app-facing device ownership and sharing APIs.

All device permissions are derived from `device_links` only.

## `POST /api/v1/devices/{device_id}/claim`

Claim an unowned device for the current authenticated user.

Request body:

```json
{}
```

Response body:

```json
{
  "status": "claimed",
  "device_id": "dev-001",
  "user_id": "user-001",
  "link_role": "owner"
}
```

Error codes:

- `401 Unauthorized`: missing or invalid bearer token
- `404 Not Found`: device does not exist
- `409 Conflict`: device already has an owner
- `500 Internal Server Error`: claim write failed

## `POST /api/v1/devices/{device_id}/viewers`

Add one viewer to a device. Only the current owner may call this endpoint.

Request body:

```json
{
  "user_id": "user-002"
}
```

Response body:

```json
{
  "status": "linked",
  "device_id": "dev-001",
  "user_id": "user-002",
  "link_role": "viewer"
}
```

Error codes:

- `401 Unauthorized`: missing or invalid bearer token
- `403 Forbidden`: caller is not the device owner
- `404 Not Found`: device or target user does not exist
- `400 Bad Request`: target link is an owner link and cannot be downgraded here
- `500 Internal Server Error`: link write failed

## `DELETE /api/v1/devices/{device_id}/viewers/{user_id}`

Remove one viewer from a device. Only the current owner may call this endpoint.

Request body:

- none

Response body:

```json
{
  "status": "success",
  "device_id": "dev-001",
  "user_id": "user-002"
}
```

Error codes:

- `401 Unauthorized`: missing or invalid bearer token
- `403 Forbidden`: caller is not the device owner
- `404 Not Found`: link does not exist
- `400 Bad Request`: target link is an owner link or is not a viewer link

## `GET /api/v1/me/devices`

Return the current user's linked devices and device-level permission.

Request body:

- none

Response body:

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
      "link_role": "owner",
      "linked_at": "2026-03-17T10:01:00Z",
      "linked_by": "user-001",
      "linked_users": [
        {
          "user_id": "user-001",
          "name": "User A",
          "phone_number": "+84900000001",
          "link_role": "owner"
        },
        {
          "user_id": "user-002",
          "name": "User B",
          "phone_number": "+84900000002",
          "link_role": "viewer"
        }
      ]
    }
  ]
}
```

Error codes:

- `401 Unauthorized`: missing or invalid bearer token

## `GET /api/v1/devices/{device_id}/linked-users`

Return all users linked to a device. Accessible to both `owner` and `viewer`.

Request body:

- none

Response body:

```json
{
  "device_id": "dev-001",
  "count": 2,
  "items": [
    {
      "user_id": "user-001",
      "name": "User A",
      "phone_number": "+84900000001",
      "link_role": "owner"
    },
    {
      "user_id": "user-002",
      "name": "User B",
      "phone_number": "+84900000002",
      "link_role": "viewer"
    }
  ]
}
```

Error codes:

- `401 Unauthorized`: missing or invalid bearer token
- `403 Forbidden`: caller has no link to the device
- `404 Not Found`: device does not exist
