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

Server cũng trả `refresh_token` opaque ở login. App nên lưu an toàn và gọi `POST /api/v1/auth/refresh` khi access token hết hạn.

### Dang nhap

`POST /api/v1/auth/login`

Request:

```json
{
  "phone_number": "+84911100401",
  "password": "PatientPass1"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque-refresh-token>",
  "token_type": "bearer",
  "expires_at": "2026-03-13T11:55:37.198839+00:00",
  "refresh_expires_at": "2026-04-12T11:55:37.198839+00:00",
  "session_id": "session-id",
  "user_id": "user-owner-401"
}
```

### Refresh token

`POST /api/v1/auth/refresh`

Request:

```json
{
  "refresh_token": "<opaque-refresh-token>"
}
```

### Logout

`POST /api/v1/auth/logout`

Ghi chu:
- can `Authorization: Bearer <access_token>`
- server revoke session hien tai, access token va refresh token cua session do se mat hieu luc

### Lay profile nguoi dung dang dang nhap

`GET /api/v1/auth/me`

Dung de hien thi ten, role, email, phone, trang thai active.

## Luong app khuyen nghi

1. Dang nhap bang `phone_number` va `password`.
2. Goi `POST /api/v1/me/push-tokens` ngay sau login de dang ky FCM token hien tai.
3. Goi `GET /api/v1/me/devices` de lay danh sach thiet bi da lien ket.
4. User chon 1 thiet bi trong danh sach.
5. Goi `latest`, `history`, `summary` de hien thi chi so.
6. Neu can man hinh quan ly, goi `linked-users` de xem ai dang lien ket voi thiet bi.
7. Logout thi goi `DELETE /api/v1/me/push-tokens/{installation_id}` truoc hoac cung luc voi `POST /api/v1/auth/logout`.

## Device Linking

### Danh sach thiet bi cua user hien tai

`GET /api/v1/me/devices`

Contract chinh thuc duoc mo ta tai `docs/me-devices-contract.md`.

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

### Cap nhat nguong canh bao

`PATCH /api/v1/devices/{device_id}/thresholds`

Chi `owner` moi duoc sua. Payload dung field phang:

```json
{
  "spo2_low": 92,
  "spo2_critical": 86,
  "temp_high": 37.8,
  "temp_critical": 39.2,
  "temp_low": 35.8,
  "hr_low": 52,
  "hr_low_critical": 42,
  "hr_high": 115,
  "hr_critical": 145
}
```

Ghi chu:
- app co the gui mot phan payload, khong can day du tat ca field
- backend merge payload moi vao custom thresholds hien co, khong ghi mat cac field khac
- backend luu vao document device o ca `settings.alert_thresholds` va `alert_thresholds`
- reading moi tu ESP se dung nguong moi nay de sinh alert

### Doc nguong hien tai

`GET /api/v1/devices/{device_id}/thresholds`

Response:

```json
{
  "device_id": "dev-001",
  "thresholds": {
    "spo2_low": 92,
    "spo2_critical": 85,
    "temp_high": 38.0,
    "temp_critical": 39.5,
    "temp_low": 35.5,
    "hr_low": 50,
    "hr_low_critical": 40,
    "hr_high": 115,
    "hr_critical": 150
  }
}
```

Ghi chu:
- response tra ve bo nguong hieu luc day du sau khi merge default thresholds voi custom thresholds cua device
- `owner` va `viewer` deu doc duoc neu dang con linked voi device

### Chi so moi nhat

`GET /api/v1/devices/{device_id}/latest`

Truong chinh:
- `timestamp`
- `fall`
- `fall_phase`
- `vitals.heart_rate`
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
    "fall_count": 1
  },
  "total_readings": 1,
  "reading_density_per_hour": 0.04,
  "clock_skew_tolerance_seconds": 300
}
```

### ESP payload co ho tro fall detection

`POST /api/v1/esp/devices/{device_id}/readings`

Payload vi du:

```json
{
  "timestamp": 1712345678.123,
  "device_type": "chest",
  "fall": false,
  "fall_phase": "IDLE",
  "vitals": {
    "heart_rate": 72,
    "spo2": 98,
    "temperature": 36.7
  },
  "ecg": {
    "waveform": [0.01, 0.02, 0.01],
    "sampling_rate": 250,
    "quality": "good",
    "lead_off": false,
    "ecg_hr": 71
  },
  "metadata": {
    "battery_level": 95,
    "signal_strength": -62,
    "signal_quality": 84,
    "upload_reason": "routine",
    "firmware_version": "esp32-s3-gateway-nimble-v1"
  }
}
```

Ghi chu:
- backend bo qua `respiratory_rate`
- khi `fall=true`, backend tao alert `fall_detected` muc `critical` va day push neu user da dang ky FCM token

### Alias giu tuong thich nguoc

Nhung route sau van ton tai, nhung khong con public that su. Chung van bat buoc phai dang nhap:

- `GET /api/v1/public/devices/{device_id}`
- `GET /api/v1/public/devices/{device_id}/latest`
- `GET /api/v1/public/devices/{device_id}/history`
- `GET /api/v1/public/devices/{device_id}/summary`
- `GET /api/v1/public/devices/{device_id}/alerts`
- `GET /api/v1/public/devices/{device_id}/ecg`

App moi nen uu tien dung nhom `/api/v1/devices/...`.

## Push Notifications

### Dang ky FCM token

`POST /api/v1/me/push-tokens`

Request:

```json
{
  "installation_id": "android-owner-401",
  "fcm_token": "<firebase-registration-token>",
  "platform": "android"
}
```

Ghi chu:
- goi sau login hoac moi lan FCM token thay doi
- `platform`: `android`, `ios`, hoac `web`

### Go token khi logout

`DELETE /api/v1/me/push-tokens/{installation_id}`

Ghi chu:
- nen goi khi user logout de backend deactivate token
- backend giu lich su token nhung danh dau `is_active=false`

### Rule nhan push

- `owner` va `viewer` dang con linked deu co the nhan push
- chi `owner` moi duoc acknowledge alert
- push cung `alert_type` se cooldown `5 phut`
- neu severity tang tu `warning` len `critical`, push moi van duoc gui ngay ca khi dang trong cooldown

## ECG

### Doc du lieu ECG lien tuc

Endpoint `POST /api/v1/devices/{device_id}/ecg/request` da bi bo.

ESP can tu gui waveform qua:

- `POST /api/v1/esp/devices/{device_id}/readings`

App doc lai du lieu ECG da luu qua:

- `GET /api/v1/devices/{device_id}/ecg`

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
