# Hướng Dẫn Kết Nối ESP32 Với Server

Tài liệu này mô tả chi tiết cách tích hợp firmware ESP32 với backend FastAPI trong repo này.

## 1. Mục tiêu tích hợp

- ESP32 gửi dữ liệu sức khỏe lên server qua HTTPS REST.
- ESP32 nhận lệnh đo ECG từ server bằng cơ chế polling command queue.
- ESP32 gửi ACK trạng thái thực thi lệnh ECG.

## 2. Kiến trúc kết nối

```text
ESP32
  -> POST /api/v1/esp/devices/{device_id}/readings
  -> GET  /api/v1/esp/devices/{device_id}/commands/next
  -> POST /api/v1/esp/devices/{device_id}/commands/{command_id}/ack

Server (FastAPI)
  -> MongoDB: health_readings, device_commands, devices
```

## 3. Điều kiện tiên quyết

- Server đã chạy và ready (`GET /ready` hoặc `GET /health` trả HTTP `200`).
- Device đã được đăng ký trong hệ thống.
- ESP token đã được cấp cho device.

## 4. Cấu hình cần có trên ESP32

```cpp
API_BASE = "https://api.example.com";   // hoặc URL Cloudflare/public URL
DEVICE_ID = "dev-esp-001";
DEVICE_TOKEN = "...";                   // lấy từ endpoint rotate token
```

Headers bắt buộc cho tất cả endpoint ESP:

```http
X-Device-Token: <DEVICE_TOKEN>
Content-Type: application/json
```

## 5. Chuẩn bị device và token từ phía server

### 5.1 Đăng ký thiết bị

```bash
curl -X POST "$BASE_URL/api/v1/devices/register" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "dev-esp-001",
    "device_type": "chest",
    "device_name": "ESP Chest 001",
    "user_id": "user-001"
  }'
```

### 5.2 Cấp/rotate ESP token

```bash
curl -X POST "$BASE_URL/api/v1/devices/dev-esp-001/esp-token" \
  -H "Authorization: Bearer $ADMIN_JWT"
```

Response mẫu:

```json
{
  "device_id": "dev-esp-001",
  "esp_token": "<plain-token-only-returned-once>"
}
```

Lưu ý:
- Server chỉ trả token plain text đúng 1 lần tại thời điểm rotate.
- Trong DB chỉ lưu hash token (`esp_token_hash`).
- Hai endpoint chuẩn bị thiết bị ở mục 5 là admin-only và hiện yêu cầu admin JWT.
- App/request ECG phía người dùng cuối đã chuyển sang JWT Bearer + RBAC.

## 6. API ESP chi tiết

## 6.1 Gửi reading

- Method: `POST`
- Path: `/api/v1/esp/devices/{device_id}/readings`

Payload khuyến nghị:

```json
{
  "timestamp": 1771763000.12,
  "seq": 1001,
  "vitals": {
    "heart_rate": 80,
    "respiratory_rate": 16,
    "temperature": 36.8,
    "spo2": 98
  },
  "metadata": {
    "battery_level": 87,
    "signal_strength": -61,
    "firmware_version": "1.2.3"
  }
}
```

Payload có ECG:

```json
{
  "timestamp": 1771763001.33,
  "seq": 1002,
  "vitals": {
    "heart_rate": 82,
    "respiratory_rate": 17,
    "temperature": 36.9,
    "spo2": 97
  },
  "ecg": {
    "waveform": [0.12, 0.14, 0.16, 0.11],
    "sampling_rate": 250,
    "quality": "good",
    "lead_off": false
  }
}
```

Response thành công:

```json
{
  "status": "success",
  "device_id": "dev-esp-001"
}
```

## 6.2 Poll command ECG

- Method: `GET`
- Path: `/api/v1/esp/devices/{device_id}/commands/next`

Khi chưa có command:

```json
{
  "status": "idle"
}
```

Khi có command:

```json
{
  "status": "ok",
  "command_id": "67ba...",
  "request_id": "uuid",
  "command": "ecg_request",
  "payload": {
    "duration_seconds": 10,
    "sampling_rate": 250
  },
  "created_at": "2026-02-22T12:00:00",
  "expires_at": "2026-02-22T12:05:00"
}
```

## 6.3 ACK command

- Method: `POST`
- Path: `/api/v1/esp/devices/{device_id}/commands/{command_id}/ack`

Body:

```json
{
  "status": "done",
  "message": "ECG captured and uploaded"
}
```

`status` hợp lệ: `done | failed`

Response:

```json
{
  "status": "success",
  "command_id": "67ba..."
}
```

## 7. Luồng ECG end-to-end cho firmware

1. Poll `/commands/next` theo chu kỳ (khuyến nghị 1-3 giây).
2. Nếu `status=ok` và `command=ecg_request`:
- Đo ECG theo `payload.duration_seconds` và `payload.sampling_rate`.
- Gửi reading có object `ecg` lên `/readings`.
- Gửi ACK `done` hoặc `failed`.
3. Nếu `status=idle`: sleep ngắn rồi poll lại.

## 8. Quy tắc dữ liệu và validation quan trọng

Vitals:
- `heart_rate`: `0..300`
- `respiratory_rate`: `0..60`
- `spo2`: `0..100`
- `temperature`: `30..45`

ECG command:
- `duration_seconds`: `3..60`
- `sampling_rate`: `100..1000`

ECG payload:
- `waveform`: mảng số
- `quality`: `good | fair | poor`

Dedup retransmit:
- Server deduplicate theo `(device_id, seq)` khi `seq` là số.
- Reading retry cùng `seq` sẽ không sinh alert mới.
- Firmware nên tăng `seq` theo từng reading để đảm bảo idempotency.

## 9. Mã lỗi thường gặp và cách xử lý

- `401 Missing device token`: thiếu `X-Device-Token`.
- `401 Invalid device token`: token sai hoặc đã rotate.
- `404 Device not found` hoặc `404 Command not found`: sai `device_id` hoặc `command_id`.
- `422`: payload sai schema/range.
- `429`: vượt rate limit route ESP.
- `500`: lỗi backend, cần retry có backoff.

Khuyến nghị retry:
- `5xx`, timeout, network lỗi: retry exponential backoff.
- `4xx` xác thực/schema: không retry mù, cần sửa payload/config.

## 10. Script test nhanh bằng curl

```bash
BASE_URL="http://127.0.0.1:8000"
DEVICE_ID="dev-esp-001"
ESP_TOKEN="replace-token"

# 1) Gửi reading
curl -X POST "$BASE_URL/api/v1/esp/devices/$DEVICE_ID/readings" \
  -H "X-Device-Token: $ESP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": 1771763000.12,
    "seq": 1,
    "vitals": {
      "heart_rate": 80,
      "respiratory_rate": 16,
      "temperature": 36.8,
      "spo2": 98
    }
  }'

# 2) Poll command
curl -X GET "$BASE_URL/api/v1/esp/devices/$DEVICE_ID/commands/next" \
  -H "X-Device-Token: $ESP_TOKEN"
```

## 11. Checklist firmware trước khi go-live

1. Có watchdog/retry khi mất mạng.
2. Đồng bộ thời gian thiết bị (NTP) để `timestamp` chính xác.
3. Sử dụng `seq` tăng dần cho mỗi reading.
4. Bảo vệ token trong firmware (không log plain token ra serial production).
5. Có cơ chế fallback nếu poll command thất bại liên tục.
6. Khi nhận command, đảm bảo gửi ACK `done/failed` để server đóng vòng đời command.

## 12. Troubleshooting nhanh

- Poll luôn `idle`:
  - Kiểm tra app đã gọi `POST /api/v1/devices/{device_id}/ecg/request` chưa.
  - Kiểm tra đúng `device_id` giữa app và firmware.

- Gửi reading thành công nhưng app không thấy dữ liệu:
  - Device chưa map `user_id` hoặc app query sai `user_id`.
  - Kiểm tra `GET /api/v1/users/{user_id}/latest`.

- 401 sau khi chạy ổn định một thời gian:
  - Token có thể đã rotate.
  - Cấp token mới và cập nhật firmware.
