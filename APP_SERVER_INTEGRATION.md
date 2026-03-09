# Hướng Dẫn Kết Nối App Với Server

Tài liệu này mô tả chi tiết cách tích hợp ứng dụng (Flutter/Web/Admin app) với backend FastAPI.

## 1. Mục tiêu tích hợp

- App gọi API server để lấy dữ liệu sức khỏe theo user/device.
- App tạo yêu cầu đo ECG on-demand cho thiết bị ESP.
- App đọc alert và các thống kê tổng hợp để hiển thị dashboard.

## 2. Kiến trúc kết nối App -> Server

```text
App (Flutter/Web)
  -> HTTPS REST + X-API-Key
  -> FastAPI Backend
  -> MongoDB
```

Lưu ý:
- App không truy cập MongoDB trực tiếp.
- Tất cả dữ liệu đi qua API backend.

## 3. Cấu hình bắt buộc phía App

Biến môi trường tối thiểu:

```env
API_BASE_URL=https://api.example.com
API_KEY=replace-with-api-key
USER_ID=user-001
DEVICE_ID=dev-esp-001
REQUEST_TIMEOUT_MS=15000
POLL_INTERVAL_MS=2000
```

Headers bắt buộc cho App/Admin API:

```http
X-API-Key: <API_KEY>
Content-Type: application/json
```

## 4. Danh sách endpoint App cần dùng

## 4.1 User
- `POST /api/v1/users`
- `GET /api/v1/users/{user_id}`
- `PATCH /api/v1/users/{user_id}/thresholds`

## 4.2 Health theo user
- `GET /api/v1/users/{user_id}/latest`
- `GET /api/v1/users/{user_id}/vitals?limit=100`
- `GET /api/v1/users/{user_id}/ecg?limit=10`
- `GET /api/v1/users/{user_id}/summary?period=24h`

`period` hợp lệ: `1h | 6h | 24h | 7d | 30d`

## 4.3 Device
- `POST /api/v1/devices/register`
- `GET /api/v1/devices/{device_id}`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/history?limit=100`
- `GET /api/v1/devices/{device_id}/summary?period=24h`
- `POST /api/v1/devices/{device_id}/ecg/request`

## 4.4 Alerts
- `GET /api/v1/users/{user_id}/alerts`
- `POST /api/v1/alerts/{alert_id}/acknowledge`

## 5. Luồng dữ liệu chính cho App

Luồng vitals thường:
1. App gọi `GET /users/{user_id}/latest` để cập nhật realtime.
2. App gọi `GET /users/{user_id}/vitals` để lấy danh sách biểu đồ.
3. App gọi `GET /users/{user_id}/summary` để hiển thị số liệu tổng hợp.

Luồng ECG on-demand:
1. App gọi `POST /devices/{device_id}/ecg/request`.
2. Server enqueue command cho ESP (`device_commands`).
3. ESP poll command, đo ECG, gửi reading, ACK done/failed.
4. App polling `GET /users/{user_id}/ecg` để nhận kết quả ECG mới.

## 6. Request/response mẫu

## 6.1 Tạo user

```bash
curl -X POST "$BASE_URL/api/v1/users" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "name": "Nguyen Van A",
    "role": "patient"
  }'
```

Response:

```json
{
  "status": "success",
  "user_id": "user-001"
}
```

## 6.2 Yêu cầu ECG

```bash
curl -X POST "$BASE_URL/api/v1/devices/dev-esp-001/ecg/request" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-001",
    "duration_seconds": 10,
    "sampling_rate": 250
  }'
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

## 6.3 Đọc dữ liệu ECG

```bash
curl -X GET "$BASE_URL/api/v1/users/user-001/ecg?limit=5" \
  -H "X-API-Key: $API_KEY"
```

## 7. Ví dụ tích hợp Flutter (Dio)

`pubspec.yaml`:

```yaml
dependencies:
  dio: ^5.6.0
  flutter_dotenv: ^5.1.0
```

`api_client.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiClient {
  static Dio build() {
    final timeoutMs = int.parse(dotenv.env['REQUEST_TIMEOUT_MS'] ?? '15000');
    return Dio(
      BaseOptions(
        baseUrl: dotenv.env['API_BASE_URL']!,
        connectTimeout: Duration(milliseconds: timeoutMs),
        receiveTimeout: Duration(milliseconds: timeoutMs),
        headers: {
          'X-API-Key': dotenv.env['API_KEY']!,
          'Content-Type': 'application/json',
        },
      ),
    );
  }
}
```

`health_api_service.dart`:

```dart
class HealthApiService {
  HealthApiService(this._dio);
  final Dio _dio;

  Future<Map<String, dynamic>> getLatest(String userId) async {
    final res = await _dio.get('/api/v1/users/$userId/latest');
    return Map<String, dynamic>.from(res.data as Map);
  }

  Future<Map<String, dynamic>> getVitals(String userId, {int limit = 100}) async {
    final res = await _dio.get(
      '/api/v1/users/$userId/vitals',
      queryParameters: {'limit': limit},
    );
    return Map<String, dynamic>.from(res.data as Map);
  }

  Future<Map<String, dynamic>> requestEcg(
    String deviceId,
    String userId,
  ) async {
    final res = await _dio.post(
      '/api/v1/devices/$deviceId/ecg/request',
      data: {
        'user_id': userId,
        'duration_seconds': 10,
        'sampling_rate': 250,
      },
    );
    return Map<String, dynamic>.from(res.data as Map);
  }
}
```

## 8. Polling ECG kết quả từ App

Khuyến nghị:
- Poll mỗi 2-3 giây.
- Timeout tổng 30-60 giây.
- Nếu quá timeout, thông báo user thử lại.

Ví dụ:

```dart
Future<Map<String, dynamic>?> waitForEcg(
  Dio dio,
  String userId,
) async {
  final deadline = DateTime.now().add(const Duration(seconds: 45));

  while (DateTime.now().isBefore(deadline)) {
    final res = await dio.get('/api/v1/users/$userId/ecg', queryParameters: {'limit': 1});
    final data = Map<String, dynamic>.from(res.data as Map);
    final items = (data['items'] as List?) ?? [];
    if (items.isNotEmpty) {
      return Map<String, dynamic>.from(items.first as Map);
    }
    await Future.delayed(const Duration(seconds: 2));
  }

  return null;
}
```

## 9. Quy tắc xử lý lỗi phía App

Mã lỗi thường gặp:
- `401`: thiếu/sai API key.
- `404`: chưa có dữ liệu cho user/device.
- `422`: request body sai schema.
- `429`: vượt rate limit.
- `500`: lỗi nội bộ backend.

Khuyến nghị UX/Retry:
- `401`: yêu cầu kiểm tra cấu hình key.
- `404`: hiển thị trạng thái "chưa có dữ liệu".
- `429`: backoff + giảm tần suất polling.
- `5xx/timeout`: retry có giới hạn số lần.

## 10. Bật tài liệu API `/docs`

Mặc định docs bị tắt.

Bật docs bằng env:

```env
EXPOSE_API_DOCS=true
```

Sau đó truy cập:
- `/docs`
- `/redoc`
- `/openapi.json`

## 11. Checklist QA kết nối App-Server

1. App gửi đúng `X-API-Key` cho mọi request `/api/v1/*`.
2. `GET /health` hoạt động trước khi test chức năng.
3. Luồng ingest từ ESP đã có dữ liệu trước khi test màn hình latest/vitals.
4. Luồng ECG request -> poll result chạy end-to-end thành công.
5. Kiểm tra trường hợp lỗi 401/404/422/429/500 có thông báo rõ ràng.
6. Log `request_id` khi gọi ECG để truy vết giữa app, server, firmware.

## 12. Troubleshooting nhanh

- App không gọi được API public:
  - Kiểm tra `API_BASE_URL`, DNS, SSL và Cloudflare tunnel.

- Có latest nhưng không có ECG:
  - ESP chưa gửi payload `ecg` hoặc chưa ACK command.

- Dữ liệu sai user:
  - Kiểm tra map `device_id <-> user_id` khi register device.

- /docs không mở được:
  - Chưa bật `EXPOSE_API_DOCS=true` và restart backend.