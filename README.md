# Wearable Health Monitoring Backend

Tài liệu này mô tả kiến trúc server, đặc tả API, luồng dữ liệu ESP -> server -> app, và quy trình kết nối triển khai thực tế.

Phiên bản tài liệu: `v1.1`  
Cập nhật: `2026-02-23`

## 1) Mục tiêu và phạm vi

- ESP32 gửi dữ liệu sức khỏe lên backend bằng HTTPS REST.
- Flutter App đọc dữ liệu bằng HTTPS REST (latest/history/ecg/summary).
- ECG on-demand vận hành bằng command queue REST polling, không dùng MQTT public.
- MongoDB chỉ truy cập qua backend service.
- Chuẩn hóa contract để team Firmware ESP và team App triển khai đồng nhất.

## 2) Kiến trúc tổng quan

```text
ESP32
  -> HTTPS /api/v1/esp/* (X-Device-Token)
Cloudflare Tunnel (tuỳ chọn)
  -> FastAPI Backend (:8000)
FastAPI Backend
  -> MongoDB
Flutter App
  -> HTTPS /api/v1/* (X-API-Key)
```

## 3) Công nghệ sử dụng

- Python 3.11
- FastAPI (REST API)
- MongoDB + Motor (async)
- Pydantic (validation/schema)
- Docker Compose
- Cloudflare Tunnel (named tunnel hoặc quick tunnel)
- Node-RED (tuỳ chọn, profile `tools`)

## 4) Thành phần runtime

- `backend` (FastAPI):
  - Expose cổng `8000` trong container.
  - Cổng host đọc từ `BACKEND_HOST_PORT` (mặc định `8000`).
- `mongodb`:
  - Cổng `27017` trong container.
  - Cổng host đọc từ `MONGO_HOST_PORT` (mặc định `27017`).
- `cloudflared`:
  - Profile `cloudflare`, dùng `CLOUDFLARE_TUNNEL_TOKEN`.
- `cloudflared-quick`:
  - Profile `cloudflare-quick`, không cần token, domain tạm.
- `nodered`:
  - Profile `tools`, phục vụ tooling.

## 5) Đặc tả xác thực

### 5.1 App/Admin API

- Áp dụng cho tất cả route `/api/v1/*` trừ ESP route.
- Header bắt buộc:

```http
X-API-Key: <API_KEY>
```

### 5.2 ESP API

- Áp dụng cho `/api/v1/esp/*`.
- Header bắt buộc:

```http
X-Device-Token: <ESP_TOKEN>
```

- Token được cấp bởi backend:
  - `POST /api/v1/devices/{device_id}/esp-token`
- Backend chỉ lưu hash (`esp_token_hash`), token plain chỉ trả về một lần.

## 6) Đặc tả API cho ESP

### 6.1 Gửi reading

- Method: `POST`
- Path: `/api/v1/esp/devices/{device_id}/readings`
- Auth: `X-Device-Token`

Quy tắc quan trọng:

- `device_id` từ path là nguồn chính (server gán lại vào payload).
- Nếu thiết bị đã map `user_id`, server tự điền `user_id` khi thiếu.
- Hỗ trợ `vitals` dạng nested (khuyến nghị).
- Vẫn hỗ trợ field phẳng cũ để tương thích ngược.
- Nếu có `seq`, backend deduplicate theo cặp `(device_id, seq)`.

Schema khuyến nghị:

```json
{
  "timestamp": 1771763000.12,
  "seq": 1,
  "vitals": {
    "heart_rate": 80,
    "respiratory_rate": 16,
    "temperature": 36.8,
    "spo2": 98
  }
}
```

Schema có ECG:

```json
{
  "timestamp": 1771763000.12,
  "seq": 2,
  "vitals": {
    "heart_rate": 82,
    "respiratory_rate": 17,
    "temperature": 36.9,
    "spo2": 97
  },
  "ecg": {
    "waveform": [0.12, 0.14, 0.16],
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

### 6.2 Poll command

- Method: `GET`
- Path: `/api/v1/esp/devices/{device_id}/commands/next`
- Auth: `X-Device-Token`

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

### 6.3 ACK command

- Method: `POST`
- Path: `/api/v1/esp/devices/{device_id}/commands/{command_id}/ack`
- Auth: `X-Device-Token`

Body:

```json
{
  "status": "done",
  "message": "ECG captured and uploaded"
}
```

Giá trị `status` hợp lệ: `done | failed`

Response:

```json
{
  "status": "success",
  "command_id": "67ba..."
}
```

## 7) Đặc tả API cho App/Admin

### 7.1 User API

- `POST /api/v1/users`
- `GET /api/v1/users/{user_id}`
- `PATCH /api/v1/users/{user_id}/thresholds`

### 7.2 Device API

- `POST /api/v1/devices/register`
- `GET /api/v1/devices/{device_id}`
- `POST /api/v1/devices/{device_id}/esp-token`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/history?limit=100`
- `GET /api/v1/devices/{device_id}/summary?period=24h`

### 7.3 Dữ liệu user cho app

- `GET /api/v1/users/{user_id}/latest`
- `GET /api/v1/users/{user_id}/vitals?limit=100`
- `GET /api/v1/users/{user_id}/ecg?limit=10`
- `GET /api/v1/users/{user_id}/summary?period=24h`

### 7.4 Yêu cầu ECG từ app

- `POST /api/v1/devices/{device_id}/ecg/request`

Body mẫu:

```json
{
  "user_id": "dev-user-001",
  "duration_seconds": 10,
  "sampling_rate": 250
}
```

Response mẫu:

```json
{
  "status": "queued",
  "delivery": "rest_polling",
  "request_id": "uuid",
  "command_id": "67ba...",
  "expires_at": "2026-02-22T12:05:00"
}
```

## 8) Đặc tả luồng dữ liệu

### 8.1 Luồng ingest ESP -> Server -> App

1. ESP gửi reading qua `/api/v1/esp/devices/{device_id}/readings`.
2. Backend xác thực token và validate schema.
3. Backend lưu vào `health_readings`.
4. App gọi latest/history/ecg để lấy dữ liệu hiển thị.

### 8.2 Luồng ECG on-demand

1. App gọi `/api/v1/devices/{device_id}/ecg/request`.
2. Backend tạo command trong `device_commands` với `status=pending`.
3. ESP poll `/commands/next`, backend chuyển `pending -> dispatched`.
4. ESP đo ECG, gửi lại reading có trường `ecg`.
5. ESP gọi ACK, backend cập nhật `status=done|failed`.
6. App polling API để nhận kết quả ECG.

### 8.3 Vòng đời command

- `pending`: vừa enqueue, chờ ESP nhận.
- `dispatched`: ESP đã nhận command từ poll.
- `done`: ESP hoàn tất và ACK thành công.
- `failed`: ESP ACK thất bại hoặc không đo được.

TTL command:

- Điều khiển bởi `COMMAND_TTL_SECONDS` (mặc định `300` giây).
- Command hết hạn được dọn tự động theo index TTL `expires_at`.

## 9) Đặc tả dữ liệu lưu trữ MongoDB

### 9.1 Collections chính

- `health_readings`: dữ liệu sức khỏe chuẩn hóa.
- `device_commands`: queue command cho ESP polling.
- `devices`: thông tin thiết bị và `esp_token_hash`.
- `users`: hồ sơ người dùng.
- `alerts`: cảnh báo theo ngưỡng.

### 9.2 Trường dữ liệu quan trọng

`health_readings`:

- `device_id`, `user_id`, `timestamp`, `seq`
- `vitals.heart_rate`, `vitals.respiratory_rate`, `vitals.temperature`, `vitals.spo2`
- `ecg.waveform`, `ecg.sampling_rate`, `ecg.quality`, `ecg.lead_off`
- `received_at`, `recorded_at`

`device_commands`:

- `device_id`, `user_id`, `request_id`
- `command` (`ecg_request`)
- `payload.duration_seconds`, `payload.sampling_rate`
- `status`, `created_at`, `expires_at`, `dispatched_at`, `completed_at`

### 9.3 Validation quan trọng

- `heart_rate`: `0..300`
- `respiratory_rate`: `0..60`
- `spo2`: `0..100`
- `temperature`: `30..45`
- `ecg_request.duration_seconds`: `3..60`
- `ecg_request.sampling_rate`: `100..1000`

## 10) Đặc tả lỗi và mã trạng thái

Mã trạng thái:

- `200`: thành công
- `400`: request hợp lệ cú pháp nhưng sai logic nghiệp vụ
- `401`: thiếu/sai API key hoặc device token
- `404`: không tìm thấy resource
- `422`: lỗi validation payload/schema
- `429`: vượt rate limit
- `500`: lỗi nội bộ server

Mẫu lỗi `401`:

```json
{
  "detail": "Invalid or missing API key"
}
```

Mẫu lỗi `429`:

```json
{
  "message": "Too many requests"
}
```

Headers rate-limit:

- `Retry-After: 60`
- `X-RateLimit-Remaining: <number>`

## 11) Cấu hình môi trường quan trọng

Root `.env` (đọc bởi docker compose):

- `MONGO_ROOT_USERNAME`
- `MONGO_ROOT_PASSWORD`
- `MONGO_BIND_IP`
- `MONGO_HOST_PORT`
- `API_KEY`
- `DEVICE_TOKEN_SECRET`
- `CORS_ALLOW_ORIGINS`
- `CORS_ALLOW_ORIGIN_REGEX`
- `BACKEND_BIND_IP`
- `BACKEND_HOST_PORT`
- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_GENERAL_PER_MINUTE`
- `RATE_LIMIT_ESP_PER_MINUTE`
- `COMMAND_TTL_SECONDS`
- `EXPOSE_API_DOCS`
- `CLOUDFLARE_TUNNEL_TOKEN` (nếu dùng profile cloudflare)
- `CLOUDFLARE_PUBLIC_URL`

## 12) Hướng dẫn tích hợp nhanh

### 12.1 Chạy local

```bash
cp .env.example .env
docker compose up -d --build
curl -sS http://127.0.0.1:8000/health
```

### 12.2 Tạo fixture test cho ESP/App

```bash
BASE_URL="https://api.example.com"
API_KEY="replace-api-key"
DEVICE_ID="dev-esp-001"

curl -sS -X POST "$BASE_URL/api/v1/users" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"dev-user-001","name":"Dev User 001","role":"patient"}'

curl -sS -X POST "$BASE_URL/api/v1/devices/register" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"device_id":"dev-esp-001","device_type":"chest","device_name":"DEV ESP 001","user_id":"dev-user-001"}'

curl -sS -X POST "$BASE_URL/api/v1/devices/$DEVICE_ID/esp-token" \
  -H "X-API-Key: $API_KEY"
```

Sau khi nhận `esp_token`, gán vào firmware:

```bash
ESP_TOKEN="replace-esp-token"
```

Test ingest:

```bash
NOW=$(python3 -c "import time; print(time.time())")
curl -sS -X POST "$BASE_URL/api/v1/esp/devices/$DEVICE_ID/readings" \
  -H "X-Device-Token: $ESP_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"timestamp\":$NOW,\"seq\":1,\"vitals\":{\"heart_rate\":80,\"respiratory_rate\":16,\"temperature\":36.8,\"spo2\":98}}"
```

### 12.3 Kiểm tra app đọc dữ liệu

```bash
curl -sS "$BASE_URL/api/v1/users/dev-user-001/latest" \
  -H "X-API-Key: $API_KEY"

curl -sS "$BASE_URL/api/v1/users/dev-user-001/vitals?limit=20" \
  -H "X-API-Key: $API_KEY"

curl -sS "$BASE_URL/api/v1/users/dev-user-001/ecg?limit=10" \
  -H "X-API-Key: $API_KEY"
```

## 13) Tài liệu liên quan

- `FLUTTER_SERVER_INTEGRATION.md`
- `API_CONTRACT_PROD.md`
- `SERVER_SPEC.md`
- `DATA_FLOW.md`
- `ESP32_INTEGRATION.md`
