# Production Runbook

## 1. Deploy checklist

- Cập nhật image/code mới nhất.
- Xác nhận `.env` có giá trị mạnh và khác nhau cho `API_KEY`, `ADMIN_API_KEY`, `DEVICE_TOKEN_SECRET`, `JWT_SECRET`.
- Chạy `docker compose config` để validate config.
- Chạy test/CI xanh trước khi deploy.
- Backup Mongo trước mọi thay đổi schema quan trọng.

## 2. Deploy

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps
curl -fsS http://127.0.0.1:${BACKEND_HOST_PORT:-8000}/ready
```

## 3. Rollback

- Checkout lại commit/tag trước đó.
- Rebuild và restart stack bằng compose production.
- Verify `/ready`, `/metrics`, logs backend, queue backlog.
- Nếu schema/data mới gây lỗi, cân nhắc restore Mongo từ backup gần nhất đã verify.

## 4. Backup and restore

Backup:

```bash
./scripts/backup.sh
```

Restore:

```bash
./scripts/restore.sh backups/<backup-file>.tar.gz
```

Yêu cầu:
- Định kỳ test restore trên môi trường staging hoặc node phụ.
- Đặt retention policy rõ ràng cho backup offsite/on-site.

## 5. Incident: MongoDB unavailable

- Kiểm tra `docker compose ps` và `docker compose logs mongodb`.
- Xác nhận disk usage, volume mount, credentials.
- Verify `/ready` trả lại `200` sau khi Mongo hồi phục.
- Theo dõi alert backlog, command backlog, tốc độ ingest sau khi recover.

## 6. Key and token rotation

- Rotate `ADMIN_API_KEY`, `API_KEY`, `JWT_SECRET`, `DEVICE_TOKEN_SECRET` theo lịch định kỳ.
- Sau khi rotate `JWT_SECRET`, buộc app/web login lại.
- Rotate `esp_token` cho từng thiết bị khi nghi ngờ lộ token hoặc khi thay firmware/owner.
- Ghi nhận mọi rotation trong audit log và ticket vận hành.

## 7. Queue operations

- Theo dõi command backlog qua `/metrics`.
- Nếu backlog tăng bất thường:
  - kiểm tra ESP còn poll `/commands/next` không
  - xem command có chuyển sang `retry_pending`/`expired` nhiều không
  - hủy command stuck bằng endpoint cancel khi cần

## 8. Monitoring checklist

- `/ready` fail alert.
- Tăng `5xx` bất thường.
- Tăng `429` bất thường.
- Queue backlog tăng kéo dài.
- Reading/phút hoặc alert/phút tụt mạnh so với baseline.

## 9. Post-deploy validation

- Login JWT thành công với admin/caregiver/patient test account.
- Patient không xem được dữ liệu user khác.
- Caregiver chỉ xem được patient được gán.
- Admin vẫn rotate token, register device, request ECG được.
- Duplicate reading không sinh alert trùng.
