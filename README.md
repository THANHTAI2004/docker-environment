# Wearable Health Monitoring Server

README nay mo ta trang thai hien tai cua server trong repo `docker-environment`, dong bo voi:

- source backend FastAPI dang co trong `backend/app`
- `docker-compose.yml` va `.env` dang chay
- MongoDB da duoc reset va seed lai bo du lieu demo `*-401`

Cap nhat theo trang thai server hien tai: **2026-03-27**

## 1. Tong quan

He thong nay la backend cho bai toan theo doi suc khoe bang thiet bi deo. Server co 3 nhom client chinh:

- ESP32 wearable gui readings qua REST
- app mobile/web dang nhap bang user account va doc du lieu theo tung device
- admin tool dung de bootstrap user, register device, xoay token ESP va van hanh he thong

Backend hien tai da chuyen sang mo hinh **device-centric**:

- du lieu duoc doc theo `device_id`
- quyen truy cap suy ra tu `device_links`
- quyen hop le chi gom `owner` va `viewer`

`user.role` khong phai nguon quyen chinh cho app hang ngay. `role=admin` chi dung cho he thong va bootstrap.

## 2. Trang thai server dang chay

Server hien dang chay voi:

- local API: `http://127.0.0.1:18000`
- public API: `https://api.eldercare.io.vn`
- backend container: `wearable-backend`
- MongoDB container: `mongodb`
- Redis container: `wearable-redis`
- Cloudflare tunnel container: `cloudflared`

Trang thai container hien tai:

- backend: healthy
- mongodb: healthy
- redis: healthy

Health endpoint:

- `GET /live`
- `GET /ready`
- `GET /health`

Readiness payload hien tai:

```json
{
  "status": "ok",
  "database": "connected",
  "ingest_mode": "rest_api"
}
```

## 3. Kien truc tong the

```text
ESP32 Device
  -> HTTPS REST + X-Device-Token
  -> FastAPI Backend
  -> MongoDB

Mobile/Web/Admin App
  -> HTTPS REST + Authorization: Bearer <JWT>
  -> FastAPI Backend
  -> MongoDB

FastAPI Backend
  -> Redis (rate limit)
  -> Prometheus-style metrics
  -> structured logging
```

Thanh phan trong compose:

- `redis`: luu rate-limit state
- `mongodb`: database chinh
- `backend`: API FastAPI/Uvicorn
- `cloudflared`: stable tunnel public
- `cloudflared-quick`: quick tunnel profile
- `nodered`: profile `tools`, khong chay mac dinh

## 4. Cong nghe va runtime

- Python `3.11`
- FastAPI `0.100.0`
- Uvicorn `0.22.0`
- Motor `3.7.1`
- Redis client `5.2.1`
- Prometheus client `0.21.1`
- MongoDB image `8.2.5`
- Redis image `7-alpine`

Docker image backend:

- multi-stage build
- chay bang user khong phai root
- expose port noi bo `8000`

## 5. Cau truc repo

```text
backend/
  Dockerfile
  requirements-prod.txt
  requirements.txt
  app/
    main.py
    config.py
    db.py
    observability.py
    api/
      auth.py
      users.py
      devices.py
      alerts.py
      health.py
      esp.py
      push.py
    services/
      health_service.py
      alert_service.py
      push_notification_service.py
    models/
      push.py
    utils/
      auth.py
      access.py
      rate_limit.py
      ecg_processing.py

docs/
  app-api.md
  app_server_contract.md
  me-devices-contract.md

scripts/
  backup.sh
  restore.sh
  monitor.sh
  smoke-api.sh
  cloudflare-longterm.sh
  setup-mdns.sh

docker-compose.yml
docker-compose.prod.yml
docker-compose.network.yml
.env.example
README.md
```

## 6. Auth va phan quyen hien tai

### App/Web

Login hien tai dung:

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Bearer auth:

```http
Authorization: Bearer <access_token>
```

Refresh token la opaque token, duoc luu hash trong collection `auth_sessions`.

**Luu y quan trong:** login hien tai dung `phone_number + password`, khong dung `user_id + password`.

### Device permissions

Quyen du lieu device duoc suy ra tu `device_links.permission`:

- `owner`: doc du lieu, xem linked users, them/xoa viewer, sua thresholds, rotate ESP token
- `viewer`: doc du lieu va linked users

Rule canh bao hien tai:

- `owner` va `viewer` deu nam trong `recipient_user_ids` cua alert
- chi `owner` moi duoc `POST /api/v1/alerts/{alert_id}/acknowledge`

### Admin/bootstrap

Co 2 luong tao user:

- `POST /api/v1/auth/register`: user tu dang ky, backend tu generate `user_id`
- `POST /api/v1/users`: bootstrap/manual create

`POST /api/v1/users` mac dinh yeu cau admin JWT. Duong `ADMIN_API_KEY` chi duoc mo khi `ALLOW_ADMIN_API_KEY_BOOTSTRAP=true`.

### ESP32

ESP dung:

```http
X-Device-Token: <device_token>
```

ESP token va pairing code deu chi luu hash trong MongoDB.

## 7. API chinh thuc dang dung

### Auth

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/me/push-tokens`
- `DELETE /api/v1/me/push-tokens/{installation_id}`

### User va ownership

- `POST /api/v1/users`
- `GET /api/v1/me/devices`
- `GET /api/v1/users/{user_id}`
- `POST /api/v1/devices/register`
- `POST /api/v1/devices/{device_id}/claim`
- `POST /api/v1/devices/{device_id}/viewers`
- `GET /api/v1/devices/{device_id}/viewers`
- `GET /api/v1/devices/{device_id}/linked-users`
- `DELETE /api/v1/devices/{device_id}/viewers/{user_id}`
- `PATCH /api/v1/devices/{device_id}/thresholds`
- `POST /api/v1/devices/{device_id}/esp-token`

### Device data va alerts

- `GET /api/v1/devices/{device_id}`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/history`
- `GET /api/v1/devices/{device_id}/ecg`
- `GET /api/v1/devices/{device_id}/summary`
- `GET /api/v1/devices/{device_id}/alerts`
- `GET /api/v1/me/alerts`
- `POST /api/v1/alerts/{alert_id}/acknowledge`
- `POST /api/v1/health/readings`

### Threshold payload va push flow

`PATCH /api/v1/devices/{device_id}/thresholds` nhan payload field phang:

- `spo2_low`
- `spo2_critical`
- `temp_high`
- `temp_critical`
- `temp_low`
- `hr_low`
- `hr_low_critical`
- `hr_high`
- `hr_critical`
- `rr_low`
- `rr_high`

Backend luu dong thoi vao `settings.alert_thresholds` va `alert_thresholds` tren document device.

Push notification flow hien tai:

- app login xong goi `POST /api/v1/me/push-tokens`
- app logout thi goi `DELETE /api/v1/me/push-tokens/{installation_id}`
- alert moi se duoc gui push cho `owner` + `viewer` con active token
- push cung loai alert se bi cooldown `5 phut`, nhung van duoc gui lai neu severity tang tu `warning` len `critical`

### ESP endpoints

- `POST /api/v1/esp/devices/{device_id}/readings`

## 8. Endpoint cu van con ton tai

Van con co de tuong thich nguoc, nhung client moi khong nen dung:

- `GET /api/v1/users/{user_id}/vitals`
- `GET /api/v1/users/{user_id}/latest`
- `GET /api/v1/users/{user_id}/ecg`
- `GET /api/v1/users/{user_id}/summary`
- `GET /api/v1/users/{user_id}/alerts`
- `GET /api/v1/public/devices/*`
- `POST /api/v1/devices/{device_id}/links`
- `DELETE /api/v1/devices/{device_id}/links/{user_id}`
- `POST /api/v1/devices/{device_id}/caregivers`
- `DELETE /api/v1/devices/{device_id}/caregivers/{user_id}`
- `POST /readings`
- `GET /history/{device_id}`

Khuyen nghi cho app moi:

- `login -> /api/v1/me/devices -> /api/v1/devices/{device_id}/latest|history|summary|alerts|ecg`

## 9. Database va collections

Database mac dinh:

- `wearable`

Collections chinh:

- `users`
- `devices`
- `device_links`
- `health_readings`
- `alerts`
- `auth_sessions`
- `push_tokens`
- `audit_logs`
- `readings` (legacy)

Index va retention dang duoc tao boi backend:

- `health_readings.recorded_at`: TTL `90 ngay`
- `alerts.recorded_at`: TTL `180 ngay`
- `devices.device_id`: unique
- `users.user_id`: unique
- `users.phone_number`: unique sparse
- `device_links(device_id, user_id)`: unique

## 10. Du lieu demo hien co tren server

MongoDB da duoc xoa du lieu cu va seed lai bo demo moi vao ngay **2026-03-20**.

So luong record hien tai:

- `users`: `6`
- `devices`: `3`
- `device_links`: `3`
- `health_readings`: `6`
- `alerts`: `11`

### Users demo

- `admin-ops-401` | `Admin Ops 401` | phone `+84909000401` | role `admin`
- `user-owner-401` | `Owner Demo 401` | phone `+84911100401`
- `user-viewer-401` | `Viewer Demo 401` | phone `+84922200401`
- `user-private-401` | `Private Demo 401` | phone `+84933300401`
- `user-claim-401` | `Claim Demo 401` | phone `+84944400401`
- `user-friend-401` | `Friend Demo 401` | phone `+84955500401`

### Devices demo

- `dev-shared-401` | `Shared Wrist 401` | owner `user-owner-401`
- `dev-private-401` | `Private Chest 401` | owner `user-private-401`
- `dev-free-401` | `Free Wrist 401` | chua co owner

### Muc dich tung device

- `dev-shared-401`: test owner/viewer sharing
- `dev-private-401`: test vitals xau, alert warning/critical
- `dev-free-401`: test claim device bang pairing code

### Ghi chu

- bo demo hien tai da co san `1` mau ECG tren `dev-shared-401`
- `dev-private-401` da co nhieu alert de test man hinh alerts
- login app phai dung `phone_number`, khong dung `user_id`

## 11. Luong xu ly du lieu

### ESP ingest

1. ESP goi `POST /api/v1/esp/devices/{device_id}/readings` kem `X-Device-Token`
2. backend validate token va payload
3. `health_service` normalize va luu vao `health_readings`
4. backend lay `alert_thresholds` cua device va truyen vao `alert_service`
5. `alert_service` sinh alert neu vuot nguong, gan `recipient_user_ids`
6. neu co push token active, server gui push qua FCM theo rule cooldown/escalation
7. app doc lai qua `latest`, `history`, `summary`, `alerts`, `ecg`

### ECG continuous

1. ESP do ECG lien tuc va gui waveform qua `POST /api/v1/esp/devices/{device_id}/readings`
2. backend normalize va luu vao `health_readings.ecg`
3. app doc lai qua `GET /api/v1/devices/{device_id}/ecg`

### Claim device

1. admin register device qua `POST /api/v1/devices/register`
2. backend tra `pairing_code` mot lan
3. user login va goi `POST /api/v1/devices/{device_id}/claim`
4. backend tao owner link trong `device_links`
5. pairing code hash bi clear sau khi claim thanh cong

## 12. Cach chay server

### Chay bang Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Health check local theo server dang chay hien tai:

```bash
curl -sS http://127.0.0.1:18000/ready
```

### Chay backend local

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-prod.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Luu y:

- local mode van can MongoDB va Redis
- `config.py` se fail-fast neu secret dang de placeholder

## 13. Bien moi truong quan trong

### Secrets va auth

- `API_KEY`
- `ADMIN_API_KEY`
- `DEVICE_TOKEN_SECRET`
- `JWT_SECRET`
- `REFRESH_TOKEN_SECRET`

### Database va network

- `MONGO_ROOT_USERNAME`
- `MONGO_ROOT_PASSWORD`
- `MONGO_BIND_IP`
- `MONGO_HOST_PORT`
- `BACKEND_BIND_IP`
- `BACKEND_HOST_PORT`
- `REDIS_URL`

Gia tri dang chay tren server local hien tai:

- `BACKEND_HOST_PORT=18000`
- `MONGO_HOST_PORT=27017`
- `CLOUDFLARE_PUBLIC_URL=https://api.eldercare.io.vn`

### Queue, rate limit, observability

- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_STORAGE`
- `RATE_LIMIT_GENERAL_PER_MINUTE`
- `RATE_LIMIT_ESP_PER_MINUTE`
- `EXPOSE_API_DOCS`
- `EXPOSE_METRICS`
- `METRICS_TOKEN`
- `METRICS_ALLOW_IPS`
- `ALLOW_ADMIN_API_KEY_BOOTSTRAP`

### Push notifications

- `PUSH_NOTIFICATIONS_ENABLED`
- `PUSH_NOTIFICATION_COOLDOWN_SECONDS`
- `MONGO_PUSH_TOKENS_COLLECTION`
- `FCM_PROJECT_ID`
- `FCM_SERVICE_ACCOUNT_PATH`
- `FCM_SERVICE_ACCOUNT_JSON`

### Firebase config nhanh

Khuyen nghi cho Docker Compose:

1. tao service account cho Firebase project cua app
2. copy JSON key thanh mot dong
3. dien vao `.env`:

```env
PUSH_NOTIFICATIONS_ENABLED=true
PUSH_NOTIFICATION_COOLDOWN_SECONDS=300
FCM_PROJECT_ID=<firebase-project-id>
FCM_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"<firebase-project-id>","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n","client_email":"firebase-adminsdk-xxx@<firebase-project-id>.iam.gserviceaccount.com","client_id":"...","token_uri":"https://oauth2.googleapis.com/token"}
```

Ghi chu:

- voi Docker, `FCM_SERVICE_ACCOUNT_JSON` de dung hon `FCM_SERVICE_ACCOUNT_PATH`
- chi bat `PUSH_NOTIFICATIONS_ENABLED=true` sau khi da dien xong `FCM_PROJECT_ID` va service account
- app login xong phai goi `POST /api/v1/me/push-tokens`

## 14. Docs, metrics va logging

Swagger/OpenAPI docs:

- `EXPOSE_API_DOCS=false` tren server hien tai
- vi vay `/docs`, `/redoc`, `/openapi.json` dang tat

Metrics:

- endpoint: `GET /metrics`
- chi mo khi `EXPOSE_METRICS=true`
- co allow-list IP va co the dung `X-Metrics-Token`

Logs:

```bash
docker compose logs -f backend
docker compose logs -f mongodb
docker compose logs -f wearable-redis
tail -f logs/health_monitor.log
```

Moi response API deu co `X-Request-ID` de truy vet.

## 15. Backup, restore, monitor

Backup:

```bash
bash scripts/backup.sh
```

Restore:

```bash
bash scripts/restore.sh backups/<backup-file>.tar.gz --force
```

Monitor:

```bash
bash scripts/monitor.sh
```

Cloudflare:

```bash
docker compose --profile cloudflare up -d cloudflared
docker compose --profile cloudflare-quick up -d cloudflared-quick
```

## 16. Smoke test

Server hien tai da co du lieu demo, nen co the smoke test bang login that.

Vi du voi owner demo tren local port `18000`:

```bash
curl -X POST http://127.0.0.1:18000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+84911100401",
    "password": "OwnerPass401!"
  }'
```

Sau khi lay access token, test:

- `GET /api/v1/me/devices`
- `GET /api/v1/devices/dev-shared-401/latest`
- `GET /api/v1/devices/dev-shared-401/ecg`
- `GET /api/v1/devices/dev-shared-401/alerts`

**Luu y:** `scripts/smoke-api.sh` hien van dung payload login kieu `user_id`, nen chua dong bo hoan toan voi auth flow hien tai cua server.

## 17. Tai lieu lien quan

- `docs/app-api.md`
- `docs/app_server_contract.md`
- `docs/me-devices-contract.md`
- `.env.example`
- `docker-compose.yml`
- `backend/app/*`

## 18. Ghi chu cho team

- Neu lam app moi, hay uu tien nhom route `/api/v1/me/devices` va `/api/v1/devices/...`
- Neu lam firmware, bam sat nhom `/api/v1/esp/*`
- Neu lam admin tooling, dung admin JWT cho van hanh hang ngay
- Chi mo `ALLOW_ADMIN_API_KEY_BOOTSTRAP=true` trong thoi gian bootstrap co kiem soat
- Neu can reset lai du lieu demo, backup truoc roi moi xoa MongoDB
