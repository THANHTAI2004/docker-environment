# Hướng Dẫn Kết Nối Flutter Với Server

Tài liệu này hướng dẫn app Flutter kết nối backend FastAPI để lấy dữ liệu sức khỏe (vitals, ECG) từ server của bạn.

## 1) Mục tiêu tích hợp

- Flutter đọc dữ liệu từ server qua HTTPS REST.
- Flutter không truy cập MongoDB trực tiếp.
- ESP32 đẩy dữ liệu vào server, Flutter chỉ đọc dữ liệu đã được xử lý.
- ECG on-demand chạy theo cơ chế command queue và polling.

## 2) Kiến trúc kết nối tổng quan

```text
ESP32
  └─ HTTPS (X-Device-Token)
      └─ Cloudflare (api.yourdomain.com)
          └─ cloudflared (server)
              └─ FastAPI (localhost:8000)
                  └─ MongoDB

Flutter App
  └─ HTTPS (X-API-Key)
      └─ Cloudflare (api.yourdomain.com)
          └─ cloudflared (server)
              └─ FastAPI (localhost:8000)
                  └─ MongoDB
```

## 3) Luồng dữ liệu

### 3.1 Luồng vitals thường

1. ESP32 -> `POST /api/v1/esp/devices/{device_id}/readings`
2. FastAPI -> validate + normalize -> `MongoDB.health_readings`
3. Flutter -> `GET /api/v1/users/{user_id}/latest` (hoặc `/api/v1/users/{user_id}/vitals`, `/api/v1/devices/{device_id}/history`)

### 3.2 Luồng ECG on-demand

1. Flutter -> `POST /api/v1/devices/{device_id}/ecg/request`
2. FastAPI -> `MongoDB.device_commands` (`status=pending`)
3. ESP32 -> `GET /api/v1/esp/devices/{device_id}/commands/next`
4. FastAPI -> trả command `ecg_request` (`status=dispatched`)
5. ESP32 đo ECG
6. ESP32 -> `POST /api/v1/esp/devices/{device_id}/readings` (có `ecg`)
7. FastAPI -> `MongoDB.health_readings`
8. ESP32 -> `POST /api/v1/esp/devices/{device_id}/commands/{command_id}/ack`
9. FastAPI -> `MongoDB.device_commands` (`status=done|failed`)
10. Flutter -> `GET /api/v1/users/{user_id}/ecg` hoặc `/latest` để lấy kết quả

## 4) Mapping backend liên quan

```text
backend/app/
  main.py                 # bootstrap FastAPI
  db.py                   # Mongo CRUD + queue command
  api/
    esp.py                # ESP ingest/poll/ack
    devices.py            # register device, cấp token, tạo ECG command
    health.py             # latest/history/vitals/ecg cho app
    users.py              # user/threshold
  services/
    health_service.py     # xử lý reading + lưu DB + alert logic
  utils/
    auth.py               # X-API-Key + X-Device-Token
  models/
    health.py
    device.py
    user.py
    alert.py
```

Mongo collections chính:

- `health_readings`
- `device_commands`
- `devices`
- `users`
- `alerts`

## 5) Cấu hình Flutter bắt buộc

### 5.1 Thêm package

`pubspec.yaml`:

```yaml
dependencies:
  dio: ^5.6.0
  flutter_dotenv: ^5.1.0
```

### 5.2 Tạo file môi trường

Tạo `.env` ở root Flutter app:

```env
API_BASE_URL=https://api.yourdomain.com
API_KEY=replace-with-api-key
USER_ID=dev-user-001
DEVICE_ID=dev-esp-001
REQUEST_TIMEOUT_MS=15000
POLL_INTERVAL_MS=2000
```

### 5.3 Load env khi khởi động app

`lib/main.dart`:

```dart
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter/material.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: ".env");
  runApp(const MyApp());
}
```

## 6) Tạo API client cho Flutter

`lib/core/network/api_client.dart`:

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

## 7) API Flutter cần gọi

- `GET /api/v1/users/{user_id}/latest`
- `GET /api/v1/users/{user_id}/vitals?limit=100`
- `GET /api/v1/users/{user_id}/ecg?limit=10`
- `GET /api/v1/users/{user_id}/summary?period=24h`
- `POST /api/v1/devices/{device_id}/ecg/request`
- Theo thiết bị (tùy chọn):
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/history?limit=100`

Ví dụ gọi nhanh:

```dart
final dio = ApiClient.build();
final userId = dotenv.env['USER_ID']!;

final latest = await dio.get('/api/v1/users/$userId/latest');
final vitals = await dio.get('/api/v1/users/$userId/vitals', queryParameters: {'limit': 20});
final ecg = await dio.get('/api/v1/users/$userId/ecg', queryParameters: {'limit': 10});
```

## 8) Service mẫu cho Flutter

`lib/features/health/data/health_api_service.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import '../../../core/network/api_client.dart';

class HealthApiService {
  HealthApiService({Dio? dio}) : _dio = dio ?? ApiClient.build();
  final Dio _dio;

  String get _userId => dotenv.env['USER_ID']!;
  String get _deviceId => dotenv.env['DEVICE_ID']!;

  Future<Map<String, dynamic>> getLatest() async {
    final r = await _dio.get('/api/v1/users/$_userId/latest');
    return Map<String, dynamic>.from(r.data as Map);
  }

  Future<Map<String, dynamic>> getVitals({int limit = 100}) async {
    final r = await _dio.get(
      '/api/v1/users/$_userId/vitals',
      queryParameters: {'limit': limit},
    );
    return Map<String, dynamic>.from(r.data as Map);
  }

  Future<Map<String, dynamic>> getEcg({int limit = 10}) async {
    final r = await _dio.get(
      '/api/v1/users/$_userId/ecg',
      queryParameters: {'limit': limit},
    );
    return Map<String, dynamic>.from(r.data as Map);
  }

  Future<Map<String, dynamic>> requestEcg({
    int durationSeconds = 10,
    int samplingRate = 250,
  }) async {
    final r = await _dio.post(
      '/api/v1/devices/$_deviceId/ecg/request',
      data: {
        'user_id': _userId,
        'duration_seconds': durationSeconds,
        'sampling_rate': samplingRate,
      },
    );
    return Map<String, dynamic>.from(r.data as Map);
  }
}
```

## 9) Polling kết quả ECG từ Flutter

Sau khi gọi `requestEcg`, app nên polling `GET /api/v1/users/{user_id}/ecg` theo chu kỳ 2-3 giây trong một khoảng timeout (ví dụ 30-60 giây).

Ví dụ:

```dart
Future<Map<String, dynamic>?> waitForEcgResult(HealthApiService api) async {
  final pollMs = int.parse(dotenv.env['POLL_INTERVAL_MS'] ?? '2000');
  final deadline = DateTime.now().add(const Duration(seconds: 45));

  while (DateTime.now().isBefore(deadline)) {
    final ecg = await api.getEcg(limit: 1);
    final items = (ecg['items'] as List?) ?? [];
    if (items.isNotEmpty) return Map<String, dynamic>.from(items.first as Map);
    await Future.delayed(Duration(milliseconds: pollMs));
  }
  return null;
}
```

## 10) Checklist test kết nối

1. `API_BASE_URL` trỏ đúng domain backend qua Cloudflare.
2. Request Flutter có header `X-API-Key`.
3. Endpoint `/health` của backend trả `status=ok`.
4. `GET /api/v1/users/{user_id}/latest` trả về dữ liệu hoặc `404 No data found`.
5. Sau khi ESP gửi reading, `latest` phải có dữ liệu mới.
6. ECG flow: `request` -> chờ ESP poll/submit -> Flutter đọc được `/ecg`.

## 11) Lỗi thường gặp

- `401 Invalid or missing API key`: sai hoặc thiếu `X-API-Key`.
- `404 No data found`: chưa có reading cho `user_id` hoặc `device_id`.
- `422`: payload gọi `ecg/request` sai schema.
- `429 Too many requests`: giảm tần suất polling hoặc tăng giới hạn rate limit trên backend.

## 12) Khuyến nghị triển khai app

- Tách riêng `ApiClient`, `HealthApiService`, `Repository`, `ViewModel/Bloc`.
- Retry nhẹ cho lỗi mạng (`SocketException`, timeout).
- Debounce/tối ưu polling để tránh spam request.
- Log `request_id` của ECG để dễ truy vết khi debug.
