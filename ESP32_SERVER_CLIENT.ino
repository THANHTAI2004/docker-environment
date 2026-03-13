#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <WiFiManager.h>
#include <HTTPClient.h>
#include <NimBLEDevice.h>
#include <ArduinoJson.h>
#include <time.h>
#include <vector>
// ===================== WIFI CONFIG PORTAL =====================
WiFiManager wm;
static const char* PORTAL_USER = "admin";
static const char* PORTAL_PASS = "123456";
static bool portalLoggedIn = false;
const char LOGIN_PAGE[] PROGMEM = R"rawliteral(
<!doctype html><html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chest Gateway Login</title>
<style>
body{font-family:system-ui;background:#0b1220;color:#e5e7eb;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{width:min(380px,92vw);background:#111a2e;border:1px solid rgba(148,163,184,.35);border-radius:18px;padding:18px 16px;box-shadow:0 18px 60px rgba(0,0,0,.5)}
input{width:100%;padding:10px 11px;border-radius:12px;border:1px solid rgba(148,163,184,.35);background:#0b1220;color:#e5e7eb;font-size:14px;outline:none;margin-bottom:10px}
button{width:100%;padding:11px;border-radius:999px;border:none;background:linear-gradient(135deg,#3b82f6,#6366f1);color:white;font-weight:700;cursor:pointer}
.err{min-height:16px;margin-top:10px;color:#fb7185;font-size:12px;text-align:center}
</style></head><body>
<div class="card">
<h2>Secure login</h2>
<form method="POST" action="/login">
<input name="user" placeholder="admin" required>
<input name="pass" type="password" placeholder="password" required>
<button type="submit">Continue</button>
</form>
<div class="err">%ERR%</div>
</div></body></html>
)rawliteral";
String buildWifiList() {
  String out;
  int n = WiFi.scanNetworks();
  if (n <= 0) {
    out += "<div style='color:#9ca3af;font-size:13px'>Khong tim thay mang Wi-Fi.</div>";
    return out;
  }
  out += "<div style='display:flex;flex-direction:column;gap:6px;max-height:240px;overflow:auto;padding:6px;border:1px solid rgba(148,163,184,.25);border-radius:12px;background:#0b1220'>";
  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    ssid.replace("\\", "\\\\");
    ssid.replace("'", "\\'");
    out += "<button type='button' style='text-align:left;padding:10px;border-radius:10px;border:1px solid rgba(148,163,184,.20);background:#111a2e;color:#e5e7eb;cursor:pointer' ";
    out += "onclick=\"document.getElementById('ssid').value='";
    out += ssid;
    out += "'\">";
    out += "<div style='font-weight:600'>" + WiFi.SSID(i) + "</div>";
    out += "<div style='font-size:12px;color:#9ca3af'>RSSI " + String(WiFi.RSSI(i)) + " dBm</div>";
    out += "</button>";
  }
  out += "</div>";
  WiFi.scanDelete();
  return out;
}
void sendLoginPage(const String& err = "") {
  String p = FPSTR(LOGIN_PAGE);
  p.replace("%ERR%", err);
  wm.server->send(200, "text/html", p);
}
void sendWifiPage() {
  if (!portalLoggedIn) {
    wm.server->sendHeader("Location", "/", true);
    wm.server->send(302, "text/plain", "");
    return;
  }
  String p;
  p += "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>";
  p += "<style>body{font-family:system-ui;background:#0b1220;color:#e5e7eb;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}.card{width:min(440px,92vw);background:#111a2e;border:1px solid rgba(148,163,184,.35);border-radius:18px;padding:18px 16px}input{width:100%;padding:10px;border-radius:12px;border:1px solid rgba(148,163,184,.35);background:#0b1220;color:#e5e7eb;margin:8px 0}button{width:100%;padding:11px;border-radius:999px;border:none;background:#16a34a;color:white;font-weight:800;margin-top:8px}</style>";
  p += "</head><body><div class='card'>";
  p += "<h2>Wi-Fi Setup</h2>";
  p += "<div style='font-size:12px;color:#9ca3af;margin-bottom:10px'>AP: " + wm.getConfigPortalSSID() + "</div>";
  p += buildWifiList();
  p += "<form method='GET' action='/wifisave'>";
  p += "<input id='ssid' name='s' placeholder='SSID' required>";
  p += "<input name='p' type='password' placeholder='Password'>";
  p += "<button type='submit'>Luu & ket noi</button></form>";
  p += "</div></body></html>";
  wm.server->send(200, "text/html", p);
}
void bindServerCallback() {
  if (!wm.server) return;
  wm.server->on("/", []() {
    if (portalLoggedIn) {
      wm.server->sendHeader("Location", "/wifi", true);
      wm.server->send(302, "text/plain", "");
    } else {
      sendLoginPage();
    }
  });
  wm.server->on("/login", []() {
    if (!wm.server->hasArg("user") || !wm.server->hasArg("pass")) {
      sendLoginPage("Missing fields");
      return;
    }
    String u = wm.server->arg("user");
    String p = wm.server->arg("pass");
    if (u == PORTAL_USER && p == PORTAL_PASS) {
      portalLoggedIn = true;
      wm.server->sendHeader("Location", "/wifi", true);
      wm.server->send(302, "text/plain", "");
    } else {
      portalLoggedIn = false;
      sendLoginPage("Wrong user/pass");
    }
  });
  wm.server->on("/wifi", []() { sendWifiPage(); });
}
bool setupWiFiWithPortal(const char* apName = "ChestGateway", const char* apPass = "12345678", uint16_t timeoutSec = 180) {
  WiFi.mode(WIFI_STA);
  portalLoggedIn = false;
  wm.setConfigPortalTimeout(timeoutSec);
  std::vector<const char*> menu = {"wifi", "exit"};
  wm.setMenu(menu);
  wm.setWebServerCallback(bindServerCallback);
  bool ok = wm.autoConnect(apName, apPass);
  if (ok) {
    Serial.print("[WiFi] OK IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WiFi] WiFiManager timeout/failed");
  }
  return ok;
}
// ===================== SERVER CONFIG =====================
// Loaded from current server env/database:
// - CLOUDFLARE_PUBLIC_URL=https://api.eldercare.io.vn
// - active device_id example: dev-esp-001
static const char* API_BASE_URL = "https://api.eldercare.io.vn";
static const char* DEVICE_ID = "dev-esp-001";
static const char* DEVICE_TYPE = "chest";
static const char* FIRMWARE_VERSION = "chest-gateway-1.1.0";
// Generate/rotate token from server API, then paste here.
// Current backend requires an admin JWT for:
// POST /api/v1/devices/{device_id}/esp-token
static const char* DEVICE_TOKEN = "lO_M2IxrOk9qXTz6B5gnykK9rleGTUskhbGpZWk0pNo";
static const unsigned long SEND_INTERVAL_MS = 10000;
static const unsigned long POLL_INTERVAL_MS = 3000;
static const unsigned long WIFI_RETRY_MS = 5000;
static const unsigned long HTTP_TIMEOUT_MS = 12000;
static const unsigned long READING_STALE_MS = 30000;
const char* NTP_SERVER = "pool.ntp.org";
const long GMT_OFFSET_SEC = 7 * 3600;
const int DAYLIGHT_OFFSET_SEC = 0;
unsigned long lastSendMs = 0;
unsigned long lastPollMs = 0;
unsigned long lastWifiRetryMs = 0;
uint32_t seqCounter = 1;
String endpointReadings() {
  return String(API_BASE_URL) + "/api/v1/esp/devices/" + DEVICE_ID + "/readings";
}
String endpointPollCommand() {
  return String(API_BASE_URL) + "/api/v1/esp/devices/" + DEVICE_ID + "/commands/next";
}
String endpointAck(const String& commandId) {
  return String(API_BASE_URL) + "/api/v1/esp/devices/" + DEVICE_ID + "/commands/" + commandId + "/ack";
}
double nowEpochSeconds() {
  time_t now = time(nullptr);
  if (now > 1700000000) {
    return (double)now + (millis() % 1000) / 1000.0;
  }
  return millis() / 1000.0;
}
int doHttpRequest(const String& method, const String& url, const String& body, String& responseOut) {
  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  bool beginOk = false;
  if (url.startsWith("https://")) {
    WiFiClientSecure client;
    client.setInsecure();  // Replace with CA cert for production
    beginOk = http.begin(client, url);
  } else {
    WiFiClient client;
    beginOk = http.begin(client, url);
  }
  if (!beginOk) {
    Serial.println("[HTTP] begin() failed");
    return -1;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.addHeader("User-Agent", "esp32-chest-gateway/1.0");
  int code = -1;
  if (method == "GET") {
    code = http.GET();
  } else if (method == "POST") {
    code = http.POST(body);
  }
  if (code > 0) {
    responseOut = http.getString();
  } else {
    responseOut = "";
    Serial.printf("[HTTP] request error: %s\n", http.errorToString(code).c_str());
  }
  http.end();
  return code;
}
void sendAck(const String& commandId, bool success, const String& message) {
  StaticJsonDocument<256> doc;
  doc["status"] = success ? "done" : "failed";
  doc["message"] = message;
  String body;
  serializeJson(doc, body);
  String resp;
  int code = doHttpRequest("POST", endpointAck(commandId), body, resp);
  Serial.printf("[ACK] code=%d body=%s\n", code, resp.c_str());
}
// ===================== BLE CONFIG =====================
static const char* SERVICE_UUID = "12345678-1234-1234-1234-1234567890ab";
static const char* CHAR_UUID = "12345678-1234-1234-1234-1234567890ac";
static const char* WRIST_NAME = "wrist01";
struct WristReading {
  int hr = 0;
  int spo2 = 0;
  float temp = NAN;
  int q = 0;
  bool valid = false;
  unsigned long updatedMs = 0;
};
static WristReading gReading;
portMUX_TYPE gDataMux = portMUX_INITIALIZER_UNLOCKED;
static NimBLEAdvertisedDevice* advDevice = nullptr;
static NimBLEClient* bleClient = nullptr;
static void notifyCB(NimBLERemoteCharacteristic*, uint8_t* pData, size_t length, bool) {
  StaticJsonDocument<192> doc;
  DeserializationError err = deserializeJson(doc, pData, length);
  if (err) {
    Serial.print("[BLE] JSON error: ");
    Serial.println(err.c_str());
    return;
  }
  int hr = doc["hr"] | 0;
  int spo2 = doc["spo2"] | 0;
  float temp = doc["temp"].isNull() ? NAN : doc["temp"].as<float>();
  int q = doc["q"] | 0;
  portENTER_CRITICAL(&gDataMux);
  gReading.hr = hr;
  gReading.spo2 = spo2;
  gReading.temp = temp;
  gReading.q = q;
  gReading.valid = true;
  gReading.updatedMs = millis();
  portEXIT_CRITICAL(&gDataMux);
  Serial.printf("[BLE] HR=%d SpO2=%d Temp=%.1f q=%d\n", hr, spo2, isnan(temp) ? 0.0f : temp, q);
}
static bool isWristHit(const NimBLEAdvertisedDevice& d) {
  if (d.haveName() && d.getName() == WRIST_NAME) return true;
  return d.isAdvertisingService(NimBLEUUID(SERVICE_UUID));
}
static bool bleConnectToWrist() {
  if (!advDevice) return false;
  if (bleClient) {
    bleClient->disconnect();
    NimBLEDevice::deleteClient(bleClient);
    bleClient = nullptr;
  }
  bleClient = NimBLEDevice::createClient();
  if (!bleClient->connect(advDevice)) {
    Serial.println("[BLE] connect failed");
    NimBLEDevice::deleteClient(bleClient);
    bleClient = nullptr;
    return false;
  }
  NimBLERemoteService* svc = bleClient->getService(SERVICE_UUID);
  if (!svc) {
    bleClient->disconnect();
    return false;
  }
  NimBLERemoteCharacteristic* chr = svc->getCharacteristic(CHAR_UUID);
  if (!chr || !chr->canNotify()) {
    bleClient->disconnect();
    return false;
  }
  bool ok = chr->subscribe(true, notifyCB);
  Serial.println(ok ? "[BLE] subscribed notify OK" : "[BLE] subscribe notify FAIL");
  if (!ok) {
    bleClient->disconnect();
  }
  return ok;
}
bool getReadingSnapshot(WristReading& out) {
  portENTER_CRITICAL(&gDataMux);
  out = gReading;
  portEXIT_CRITICAL(&gDataMux);
  if (!out.valid) return false;
  if (millis() - out.updatedMs > READING_STALE_MS) return false;
  return true;
}
void sendVitalsToServer() {
  WristReading r;
  if (!getReadingSnapshot(r)) {
    Serial.println("[READING] skipped: no fresh BLE data");
    return;
  }
  StaticJsonDocument<512> doc;
  doc["device_type"] = DEVICE_TYPE;
  doc["timestamp"] = nowEpochSeconds();
  doc["seq"] = seqCounter++;
  JsonObject vitals = doc.createNestedObject("vitals");
  vitals["heart_rate"] = r.hr;
  vitals["spo2"] = r.spo2;
  if (!isnan(r.temp)) {
    vitals["temperature"] = r.temp;
  }
  vitals["respiratory_rate"] = 16;  // placeholder if wrist payload does not provide RR
  JsonObject metadata = doc.createNestedObject("metadata");
  metadata["signal_strength"] = WiFi.RSSI();
  metadata["firmware_version"] = FIRMWARE_VERSION;
  metadata["signal_quality"] = r.q;
  String body;
  serializeJson(doc, body);
  String resp;
  int code = doHttpRequest("POST", endpointReadings(), body, resp);
  Serial.printf("[READING] code=%d body=%s\n", code, resp.c_str());
}
void handleCommandPoll() {
  String resp;
  int code = doHttpRequest("GET", endpointPollCommand(), "", resp);
  if (!(code >= 200 && code < 300)) {
    Serial.printf("[POLL] code=%d\n", code);
    return;
  }
  DynamicJsonDocument doc(2048);
  DeserializationError err = deserializeJson(doc, resp);
  if (err) {
    Serial.printf("[POLL] invalid json: %s\n", err.c_str());
    return;
  }
  const char* status = doc["status"] | "";
  if (strcmp(status, "idle") == 0) {
    return;
  }
  if (strcmp(status, "ok") != 0) {
    Serial.printf("[POLL] unexpected status: %s\n", status);
    return;
  }
  String commandId = doc["command_id"] | "";
  String command = doc["command"] | "";
  if (commandId.isEmpty() || command.isEmpty()) {
    Serial.println("[POLL] missing command fields");
    return;
  }
  if (command == "ecg_request") {
    // This gateway currently bridges BLE vitals and does not capture ECG waveform.
    sendAck(commandId, false, "ECG not supported on this firmware");
  } else {
    sendAck(commandId, false, "Unsupported command");
  }
}
void bleTask(void*) {
  while (true) {
    if (bleClient && bleClient->isConnected()) {
      vTaskDelay(pdMS_TO_TICKS(800));
      continue;
    }
    NimBLEScan* scan = NimBLEDevice::getScan();
    scan->clearResults();
    scan->setActiveScan(true);
    scan->setInterval(160);
    scan->setWindow(80);
    NimBLEScanResults res = scan->getResults(6000, false);
    if (advDevice) {
      delete advDevice;
      advDevice = nullptr;
    }
    for (int i = 0; i < res.getCount(); i++) {
      const NimBLEAdvertisedDevice* d = res.getDevice(i);
      if (d && isWristHit(*d)) {
        advDevice = new NimBLEAdvertisedDevice(*d);
        break;
      }
    }
    scan->clearResults();
    if (!advDevice) {
      Serial.println("[BLE] wrist not found");
      vTaskDelay(pdMS_TO_TICKS(3000));
      continue;
    }
    if (bleConnectToWrist()) {
      Serial.println("[BLE] connected OK");
    } else {
      Serial.println("[BLE] connect sequence failed");
      vTaskDelay(pdMS_TO_TICKS(3000));
    }
  }
}
void setup() {
  Serial.begin(115200);
  delay(200);
  setupWiFiWithPortal("ChestGateway", "12345678", 180);
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, NTP_SERVER);
  NimBLEDevice::init("chest-gateway");
  NimBLEDevice::setPower(6);
  NimBLEDevice::setMTU(247);
  xTaskCreatePinnedToCore(
    bleTask,
    "bleTask",
    8192,
    nullptr,
    1,
    nullptr,
    0
  );
  Serial.println("Ready: WiFi portal + BLE + Server API");
}
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiRetryMs >= WIFI_RETRY_MS) {
      lastWifiRetryMs = millis();
      WiFi.reconnect();
      Serial.println("[WiFi] reconnect requested");
    }
    delay(20);
    return;
  }
  unsigned long now = millis();
  if (now - lastSendMs >= SEND_INTERVAL_MS) {
    lastSendMs = now;
    sendVitalsToServer();
  }
  if (now - lastPollMs >= POLL_INTERVAL_MS) {
    lastPollMs = now;
    handleCommandPoll();
  }
  delay(20);
}
