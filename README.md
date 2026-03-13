# Wearable Health Monitoring Backend

Tài liệu này mô tả hệ thống server trong repo `docker-environment`, theo đúng cấu trúc 15 mục yêu cầu để phục vụ team backend, firmware (ESP32) và app Flutter/Web.

Cập nhật theo source hiện tại: **2026-03-09**

## 1. Mục tiêu hệ thống

Server dùng để làm gì:
- Nhận dữ liệu sức khỏe từ thiết bị đeo (nhịp tim, SpO2, nhiệt độ, nhịp thở, ECG).
- Chuẩn hóa, lưu trữ dữ liệu vào MongoDB.
- Phân tích ngưỡng để tạo cảnh báo tự động.
- Cung cấp API cho app/web truy vấn dữ liệu realtime và lịch sử.

Phục vụ app/web/device nào:
- ESP32 wearable device (chest/wrist): gửi readings và nhận command ECG.
- Flutter app (mobile/web): lấy latest/history/summary/ECG và gửi yêu cầu ECG on-demand.
- Admin/client nội bộ: quản lý user, device, token, thresholds.

Người dùng hoặc client nào kết nối vào:
- Thiết bị ESP32 qua `/api/v1/esp/*`.
- App/Admin qua `/api/v1/*`.
- Health check nội bộ qua `/live`, `/ready`, `/health`.

## 2. Tổng quan kiến trúc

Mô hình tổng thể của hệ thống:

```text
ESP32 (X-Device-Token)
    -> FastAPI Backend (wearable-backend)
        -> MongoDB (mongodb)
        -> Redis (rate limit)
Flutter/Web/Admin (JWT Bearer)
    -> FastAPI Backend
```

Các thành phần chính:
- Backend: FastAPI (`backend/app`).
- Database: MongoDB.
- Rate limit/cache: Redis.
- Queue: sử dụng collection MongoDB `device_commands` (không dùng Redis/RabbitMQ).
- Proxy/Tunnel: Cloudflare Tunnel (optional), Nginx config mẫu.
- Container: Docker Compose.

Cách các thành phần giao tiếp với nhau:
- ESP32 -> Backend: HTTPS REST + `X-Device-Token`.
- App/Web -> Backend: HTTPS REST + `Authorization: Bearer <JWT>`.
- Backend -> MongoDB: Motor async driver.
- Backend -> Redis: Redis async client cho rate limit.
- Cloudflare/Nginx (nếu bật) đứng trước backend làm public endpoint/reverse proxy.

## 3. Công nghệ sử dụng

Ngôn ngữ, framework:
- Python 3.11
- FastAPI
- Uvicorn
- Pydantic v2 + pydantic-settings

Database:
- MongoDB

Web server / reverse proxy:
- Uvicorn chạy trong container backend
- Nginx cấu hình mẫu tại `nginx/nginx.conf` (chưa chạy mặc định trong compose)

Docker, cloud, CI/CD nếu có:
- Docker Compose (`docker-compose.yml`)
- Production override (`docker-compose.prod.yml`)
- Network mode compose (`docker-compose.network.yml`)
- Cloudflare Tunnel (`cloudflared`, `cloudflared-quick`)
- CI/CD: GitHub Actions tối thiểu tại `.github/workflows/ci.yml`

Ví dụ stack hiện tại:
- Python + FastAPI
- MongoDB
- Nginx (optional)
- Docker Compose

## 4. Cấu trúc thư mục/source code

Thư mục nào dùng để làm gì:

```text
backend/
  Dockerfile
  requirements.txt
  app/
    main.py            # Entry point FastAPI
    config.py          # Settings từ env
    db.py              # Kết nối Mongo + index + CRUD
    api/               # Routes
      devices.py
      users.py
      health.py
      alerts.py
      esp.py
    models/            # Pydantic models
    services/          # Business logic
      health_service.py
      alert_service.py
    utils/             # Auth, validators, ECG utils

scripts/
  backup.sh
  restore.sh
  monitor.sh
  cloudflare-longterm.sh
  setup-mdns.sh

nginx/
  nginx.conf

logs/                 # Log monitor script
backups/              # File backup Mongo
```

File chính để chạy server:
- `backend/app/main.py` (chạy bằng `uvicorn app.main:app ...`)
- Hoặc chạy full stack qua `docker-compose.yml`

Nơi chứa config, route, model, service, util:
- Config: `backend/app/config.py`, root `.env`
- Route: `backend/app/api/*`
- Model: `backend/app/models/*`
- Service: `backend/app/services/*`
- Util: `backend/app/utils/*`

## 5. Môi trường chạy

Hệ điều hành hoặc container:
- Linux/WSL2 + Docker Engine là môi trường khuyến nghị.
- Backend container dùng base image `python:3.11-slim`.

Yêu cầu cài đặt:
- Docker + Docker Compose plugin.
- Nếu chạy local không Docker: Python 3.11, pip.

Version cần dùng:
- `fastapi==0.100.0`
- `uvicorn[standard]==0.22.0`
- `motor==3.7.1`
- `python-dotenv==1.0.0`
- `pydantic-settings==2.0.3`

Cách cài dependency (local):

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. Cấu hình hệ thống

Biến môi trường cần thiết:
- Mongo: `MONGO_ROOT_USERNAME`, `MONGO_ROOT_PASSWORD`, `MONGO_HOST_PORT`, `MONGO_BIND_IP`
- API/Auth: `API_KEY`, `ADMIN_API_KEY`, `DEVICE_TOKEN_SECRET`, `JWT_SECRET`
- Backend: `BACKEND_HOST_PORT`, `BACKEND_BIND_IP`, `EXPOSE_API_DOCS`
- CORS: `CORS_ALLOW_ORIGINS`, `CORS_ALLOW_ORIGIN_REGEX`
- Rate-limit: `RATE_LIMIT_ENABLED`, `RATE_LIMIT_STORAGE`, `REDIS_URL`, `RATE_LIMIT_GENERAL_PER_MINUTE`, `RATE_LIMIT_ESP_PER_MINUTE`
- Command queue: `COMMAND_TTL_SECONDS`
- Cloudflare (optional): `CLOUDFLARE_TUNNEL_TOKEN`, `CLOUDFLARE_PUBLIC_URL`

Port chạy:
- Backend: `${BACKEND_BIND_IP}:${BACKEND_HOST_PORT}` (mặc định `127.0.0.1:8000`)
- MongoDB: `${MONGO_BIND_IP}:${MONGO_HOST_PORT}` (mặc định `127.0.0.1:27017`)
- Node-RED (optional): `${NODERED_BIND_IP}:${NODERED_HOST_PORT}` (mặc định `127.0.0.1:1880`)

Key/token:
- `Authorization: Bearer <JWT>` cho app/admin.
- `ADMIN_API_KEY` là bootstrap/break-glass secret cho một số endpoint admin-only.
- `X-Device-Token` cho ESP.
- Token thiết bị được hash (`sha256(secret:token)`) trước khi lưu vào DB.

Config database:
- Backend dùng `MONGO_URI` và `MONGO_DB` (compose set mặc định DB `wearable`).
- Collections chính: `health_readings`, `device_commands`, `devices`, `users`, `alerts`.

Config bảo mật:
- CORS whitelist + regex.
- JWT + RBAC (`admin / caregiver / patient`) cho app/admin.
- Redis-backed rate limit theo JWT subject / API key / device.
- API docs mặc định tắt (`EXPOSE_API_DOCS=false`).

## 7. Cách khởi động server

Lệnh chạy local:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# set env phù hợp trước khi chạy
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Lệnh chạy bằng Docker:

```bash
cp .env.example .env
# chỉnh .env

docker compose up -d --build
```

Cách stop/restart:

```bash
docker compose stop
docker compose restart backend
docker compose down
```

Cách kiểm tra server đã lên chưa:

```bash
curl -sS http://127.0.0.1:8000/ready
docker compose ps
docker compose logs -f backend
```

Smoke test nhanh sau deploy:

```bash
SMOKE_BASE_URL=http://127.0.0.1:18000 \
SMOKE_USER_ID=<user_id> \
SMOKE_PASSWORD='<password>' \
SMOKE_DEVICE_ID=<device_id> \
./scripts/smoke-api.sh
```

Tai lieu API danh cho app: `docs/app-api.md`

## 8. API và chức năng chính

Các endpoint chính:

App/Admin (`/api/v1`):
- `POST /auth/login`
- `GET /auth/me`
- `POST /users`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}/thresholds`
- `POST /devices/register`
- `GET /devices/{device_id}`
- `POST /devices/{device_id}/esp-token`
- `POST /devices/{device_id}/ecg/request`
- `GET /devices/{device_id}/latest`
- `GET /devices/{device_id}/history`
- `GET /devices/{device_id}/vitals`
- `GET /devices/{device_id}/summary`
- `GET /users/{user_id}/latest`
- `GET /users/{user_id}/vitals`
- `GET /users/{user_id}/ecg`
- `GET /users/{user_id}/summary`
- `GET /users/{user_id}/alerts`
- `POST /alerts/{alert_id}/acknowledge`
- `POST /health/readings` (test/manual ingest)

Ghi chú quyền:
- Endpoint bootstrap/break-glass admin: `POST /users`, `POST /devices/register`, `POST /devices/{device_id}/esp-token`, `POST /devices/{device_id}/commands/{command_id}/cancel`, `POST /health/readings`, `POST /readings`
- App/Web thường dùng JWT Bearer cho đọc dữ liệu và request ECG.
- RBAC: `admin` xem toàn bộ, `patient` chỉ xem dữ liệu của chính mình, `caregiver` chỉ xem patient được gán.

ESP (`/api/v1/esp`):
- `POST /devices/{device_id}/readings`
- `GET /devices/{device_id}/commands/next`
- `POST /devices/{device_id}/commands/{command_id}/ack`

Legacy:
- `POST /readings`
- `GET /history/{device_id}`

Input/output (ví dụ nhanh):

```json
POST /api/v1/esp/devices/dev-001/readings
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

```json
{
  "status": "success",
  "device_id": "dev-001"
}
```

Xác thực:
- App/Admin: JWT Bearer qua `Authorization`.
- Một số endpoint admin-only hỗ trợ `ADMIN_API_KEY` làm bootstrap/break-glass.
- ESP: bắt buộc header `X-Device-Token`.

Mã lỗi thường gặp:
- `400`: request hợp lệ cú pháp nhưng sai logic nghiệp vụ
- `401`: thiếu/sai bearer token, admin key hoặc device token
- `403`: đúng danh tính nhưng không đủ quyền/ownership
- `404`: không tìm thấy tài nguyên/dữ liệu
- `422`: lỗi validation payload
- `429`: vượt rate limit
- `500`: lỗi nội bộ server

Tài liệu `/docs` nếu có:
- Chỉ bật khi `EXPOSE_API_DOCS=true`.
- Khi bật: `/docs`, `/redoc`, `/openapi.json`.

## 9. Database

Loại database:
- MongoDB

Collection chính:
- `health_readings`
- `device_commands`
- `devices`
- `users`
- `alerts`
- `readings` (legacy)

Schema dữ liệu (rút gọn):
- `health_readings`: `device_id`, `user_id`, `timestamp`, `vitals`, `ecg`, `metadata`, `recorded_at`, `received_at`, `seq`
- `device_commands`: `device_id`, `user_id`, `request_id`, `command`, `payload`, `status`, `expires_at`, `dispatched_at`, `completed_at`
- `devices`: `device_id`, `device_type`, `user_id`, `status`, `esp_token_hash`, `metadata`, `last_seen`
- `users`: `user_id`, `name`, `role`, `alert_thresholds`, `created_at`
- `alerts`: `device_id`, `user_id`, `severity`, `metric`, `value`, `threshold`, `acknowledged`

Index:
- `health_readings`: `(user_id, timestamp desc)`, `(device_id, timestamp desc)`
- Unique dedup: `(device_id, seq)` với partial index khi `seq` là number
- TTL: `health_readings.recorded_at` (~90 ngày)
- TTL: `alerts.recorded_at` (~180 ngày)
- TTL: `device_commands.expires_at` (xóa khi hết hạn)
- Unique: `devices.device_id`, `users.user_id`, `device_commands.request_id`

Quan hệ dữ liệu nếu có:
- Quan hệ mềm bằng khóa logic, không có foreign key cứng:
  - `devices.user_id` -> `users.user_id`
  - `health_readings.user_id/device_id` liên kết user/device
  - `alerts.user_id/device_id` liên kết user/device
  - `device_commands.device_id/user_id` liên kết command với thiết bị và user

## 10. Luồng xử lý dữ liệu

Request đi vào đâu:
- ESP đi vào `backend/app/api/esp.py`.
- App/Admin đi vào `backend/app/api/*.py` tương ứng domain.

Xử lý ở service nào:
- Health ingest xử lý ở `health_service.process_health_reading()`.
- Alert sinh ở `alert_service.check_health_reading()`.

Lưu database ra sao:
- `db.insert_health_reading()` lưu reading đã normalize.
- `db.enqueue_device_command()` tạo command ECG.
- `db.claim_next_device_command()` phát command cho ESP poll.
- `db.acknowledge_device_command()` cập nhật trạng thái done/failed.

Trả kết quả về client thế nào:
- API trả JSON trực tiếp.
- ESP nhận `status=idle|ok` khi poll command.
- App truy vấn `/latest`, `/vitals`, `/ecg`, `/summary` để hiển thị.

## 11. Bảo mật

Authentication / authorization:
- JWT Bearer cho app/admin.
- `ADMIN_API_KEY` cho bootstrap/break-glass admin.
- `X-Device-Token` cho API ESP.
- RBAC theo `admin / caregiver / patient`.
- Ownership check giữa `user_id` và `device_id`.

API key, JWT, token thiết bị:
- API key: env `API_KEY` chỉ dùng cho compatibility nội bộ nếu cần.
- Admin key: env `ADMIN_API_KEY` cho bootstrap/break-glass.
- JWT: access token ký bằng `JWT_SECRET`.
- Device token: cấp qua endpoint rotate token, lưu dưới dạng hash trong DB.

CORS:
- `CORS_ALLOW_ORIGINS` và `CORS_ALLOW_ORIGIN_REGEX`.

Mã hóa dữ liệu nếu có:
- Token thiết bị được băm SHA-256 với secret trước khi lưu (`sha256(secret:token)`).
- TLS/HTTPS phụ thuộc lớp reverse proxy/tunnel (Cloudflare/Nginx).

Giới hạn truy cập:
- Rate limit Redis-backed theo JWT subject / API key / device.
- Header phản hồi có `X-RateLimit-Remaining`, khi vượt giới hạn trả `429`.

## 12. Logging và giám sát

Log nằm ở đâu:
- Backend container: `docker compose logs backend`
- MongoDB container: `docker compose logs mongodb`
- Cloudflared: `docker compose logs cloudflared`
- Monitor script: `logs/health_monitor.log`

Cách xem log:

```bash
docker compose logs -f backend
docker compose logs -f mongodb
tail -f logs/health_monitor.log
```

Health check:
- API: `GET /health`
- Liveness: `GET /live`
- Readiness: `GET /ready` hoặc `GET /health` và sẽ trả `503` khi DB lỗi
- Docker healthcheck đã cấu hình cho backend dùng `/ready` và mongodb dùng ping nội bộ.
- Metrics: `GET /metrics`

Debug lỗi:
- Kiểm tra `docker compose ps`.
- So log backend/mongodb.
- Gọi test nhanh endpoint `/ready` hoặc `/health` và endpoint nghiệp vụ.

Monitoring nếu có:
- `scripts/monitor.sh` kiểm tra health endpoint, trạng thái container, disk usage.
- Prometheus có thể scrape `/metrics`.

## 13. Triển khai và vận hành

Deploy ở đâu:
- Triển khai bằng Docker Compose trên Linux/WSL server.

Domain:
- Dùng `CLOUDFLARE_PUBLIC_URL` nếu public qua Cloudflare Tunnel.
- Quick tunnel dùng domain tạm `*.trycloudflare.com`.

Reverse proxy / Cloudflare / Nginx:
- Cloudflare Tunnel là lựa chọn chính trong repo hiện tại.
- Nginx có cấu hình mẫu tại `nginx/nginx.conf` nếu muốn đặt reverse proxy riêng.

Backup, restore:

```bash
./scripts/backup.sh
./scripts/restore.sh backups/<backup-file>.tar.gz
```

Update version:

```bash
git pull
docker compose up -d --build
# production:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 14. Các lỗi thường gặp và cách xử lý

Port bị chiếm:
- Triệu chứng: container không bind được cổng.
- Cách xử lý: đổi `BACKEND_HOST_PORT`/`MONGO_HOST_PORT` trong `.env`, chạy lại compose.

Lỗi kết nối DB:
- Triệu chứng: `/health` báo `database: disconnected`.
- Cách xử lý: kiểm tra credentials Mongo, container `mongodb` healthy, URI kết nối đúng.

Lỗi cấu hình env:
- Triệu chứng: `401 Invalid or missing API key`, hoặc ESP token invalid.
- Cách xử lý: đồng bộ key/token, kiểm tra `.env`, rotate lại ESP token nếu cần.

Lỗi container:
- Triệu chứng: `unhealthy`, restart loop.
- Cách xử lý: kiểm tra `docker compose logs`, healthcheck, tài nguyên CPU/RAM/disk.

Lỗi permission:
- Triệu chứng: script backup/restore không chạy.
- Cách xử lý: `chmod +x scripts/*.sh`, kiểm tra quyền chạy Docker.

Lỗi WSL/dev environment nếu có:
- Triệu chứng: network/localhost không ổn định, hiệu năng I/O chậm.
- Cách xử lý: chạy command trong cùng môi trường WSL, kiểm tra Docker Desktop WSL integration.

## 15. Đánh giá và đề xuất

Ưu điểm hiện tại:
- Kiến trúc tách lớp khá rõ (api/service/db/models/utils).
- Hỗ trợ đầy đủ ingest + ECG on-demand queue polling.
- Có index, TTL, readiness, JWT/RBAC cơ bản, request ID, metrics, rate-limit Redis-backed.
- Có script vận hành (backup/restore/monitor/deploy cloudflare).

Hạn chế:
- Queue vẫn dùng Mongo polling nên hợp với small/medium scale hơn broker chuyên dụng.
- Chưa có refresh token/session revocation.
- Dashboard/alerting hạ tầng vẫn cần triển khai ngoài repo.

Hướng cải tiến sau này:
1. Thêm refresh token/session revocation và MFA cho admin.
2. Mở rộng test integration với Mongo/Redis thật trong CI.
3. Bổ sung alerting/dashboard production cho metrics và audit log.
4. Cân nhắc broker riêng nếu queue command tăng tải mạnh.
5. Chuẩn hóa runbook production cho backup/restore/disaster recovery.
