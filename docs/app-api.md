# App API Guide

Tai lieu nay danh cho app mobile/web sau khi backend da chuyen sang mo hinh dang nhap + lien ket thiet bi.

## Base URL

- Local direct: `http://127.0.0.1:${BACKEND_HOST_PORT}`
- Qua domain public: dung domain Cloudflare/Nginx cua ban
- API prefix: `/api/v1`

## Auth

App dang nhap bang tai khoan nguoi dung, sau do gui JWT o header:

```http
Authorization: Bearer <access_token>
```

### Dang nhap

`POST /api/v1/auth/login`

Request:

```json
{
  "user_id": "patient-001",
  "password": "PatientPass1"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_at": "2026-03-13T11:55:37.198839+00:00",
  "user_id": "patient-001",
  "role": "patient",
  "scopes": ["patient"]
}
```

### Lay profile nguoi dung dang dang nhap

`GET /api/v1/auth/me`

Dung de hien thi ten, role, email, phone, trang thai active.

## Luong app khuyen nghi

1. Dang nhap bang `user_id` va `password`.
2. Goi `GET /api/v1/me/devices` de lay danh sach thiet bi da lien ket.
3. User chon 1 thiet bi trong danh sach.
4. Goi `latest`, `history`, `summary` de hien thi chi so.
5. Neu can man hinh quan ly, goi `linked-users` de xem ai dang lien ket voi thiet bi.

## Device Linking

### Danh sach thiet bi cua user hien tai

`GET /api/v1/me/devices`

Response:

```json
{
  "user_id": "patient-001",
  "count": 1,
  "items": [
    {
      "device_id": "dev-001",
      "device_type": "wrist",
      "device_name": "Wristband 1",
      "firmware_version": null,
      "registered_at": "2026-03-13T10:49:25.687000",
      "last_seen": "2026-03-13T10:49:55.219000",
      "status": "active",
      "link_role": "owner",
      "linked_at": "2026-03-13T10:49:37.038000",
      "linked_by": "patient-001"
    }
  ]
}
```

### Lien ket user hien tai voi mot thiet bi

`POST /api/v1/devices/{device_id}/links`

Request:

```json
{
  "link_role": "owner"
}
```

Ghi chu:
- `owner`: chu so huu chinh cua thiet bi
- `viewer`: tai khoan duoc xem du lieu
- Moi thiet bi chi co 1 `owner`
- Neu user thuong lien ket, `user_id` se mac dinh la chinh user dang dang nhap

### Xem ai dang lien ket voi thiet bi

`GET /api/v1/devices/{device_id}/linked-users`

Response:

```json
{
  "device_id": "dev-001",
  "count": 1,
  "items": [
    {
      "user_id": "patient-001",
      "name": "Patient One",
      "role": "patient",
      "email": null,
      "phone": null,
      "is_active": true,
      "link_role": "owner",
      "linked_at": "2026-03-13T10:49:37.038000",
      "linked_by": "patient-001"
    }
  ]
}
```

### Go lien ket

`DELETE /api/v1/devices/{device_id}/links/{user_id}`

Quyen:
- `admin` co the go bat ky user nao
- user thuong chi go duoc lien ket cua chinh minh

## Device Data

Tat ca endpoint duoi day deu can JWT hop le va user phai co link voi thiet bi.

### Thong tin thiet bi

`GET /api/v1/devices/{device_id}`

Truong chinh:
- `device_id`
- `device_type`
- `device_name`
- `registered_at`
- `last_seen`
- `status`
- `alert_thresholds`

### Chi so moi nhat

`GET /api/v1/devices/{device_id}/latest`

Truong chinh:
- `timestamp`
- `vitals.heart_rate`
- `vitals.respiratory_rate`
- `vitals.spo2`
- `vitals.temperature`
- `metadata.battery_level`
- `metadata.signal_strength`

### Lich su chi so

`GET /api/v1/devices/{device_id}/history`

Query params:
- `start_time`: unix timestamp giay
- `end_time`: unix timestamp giay
- `limit`: mac dinh `100`, toi da `2000`

Vi du:

```http
GET /api/v1/devices/dev-001/history?limit=50
GET /api/v1/devices/dev-001/history?start_time=1773395600&end_time=1773399200&limit=200
```

### Tong hop thong ke

`GET /api/v1/devices/{device_id}/summary`

Query params:
- `period`: `1h`, `6h`, `24h`, `7d`, `30d`

Response:

```json
{
  "device_id": "dev-001",
  "period": "24h",
  "device_type": "wrist",
  "summary": {
    "spo2": { "avg": 98.0, "min": 98.0, "max": 98.0 },
    "temperature": { "avg": 36.7, "min": 36.7, "max": 36.7 },
    "heart_rate": { "avg": 78.0, "min": 78, "max": 78 },
    "respiratory_rate": { "avg": 16.0, "min": 16, "max": 16 }
  },
  "total_readings": 1,
  "reading_density_per_hour": 0.04,
  "clock_skew_tolerance_seconds": 300
}
```

### Alias giu tuong thich nguoc

Nhung route sau van ton tai, nhung khong con public that su. Chung van bat buoc phai dang nhap:

- `GET /api/v1/public/devices/{device_id}`
- `GET /api/v1/public/devices/{device_id}/latest`
- `GET /api/v1/public/devices/{device_id}/history`
- `GET /api/v1/public/devices/{device_id}/summary`
- `GET /api/v1/public/devices/{device_id}/alerts`
- `GET /api/v1/public/devices/{device_id}/ecg`

App moi nen uu tien dung nhom `/api/v1/devices/...`.

## ECG

### Gui lenh yeu cau do ECG

`POST /api/v1/devices/{device_id}/ecg/request`

Request:

```json
{
  "duration_seconds": 30,
  "sampling_rate": 250
}
```

Response:

```json
{
  "status": "queued",
  "delivery": "rest_polling",
  "request_id": "<uuid>",
  "command_id": "<mongo_id>",
  "expires_at": "2026-03-13T11:05:00.000000"
}
```

## Error Guide

- `401 Unauthorized`: chua dang nhap, token sai, token het han
- `403 Forbidden`: user khong co link voi thiet bi hoac khong du quyen
- `404 Not Found`: user, thiet bi, du lieu, hoac link khong ton tai
- `409 Conflict`: thiet bi da co owner, hoac command ECG dang bi gioi han

## Smoke Test

Sau moi lan deploy, co the kiem tra nhanh bang script:

```bash
SMOKE_BASE_URL=http://127.0.0.1:18000 \
SMOKE_USER_ID=smoke-user-20260313 \
SMOKE_PASSWORD='SmokePass123!' \
SMOKE_DEVICE_ID=smoke-dev-20260313 \
./scripts/smoke-api.sh
```
