/*
 * Nurby ESP32 Buzzer Alarm
 * ------------------------
 * A tiny Wi-Fi alarm. Nurby POSTs an alert to /alert and this sketch
 * chirps a piezo buzzer. Optionally verifies the HMAC-SHA256 signature
 * Nurby sends in the X-Nurby-Signature header.
 *
 * Hardware:
 *   Buzzer + -> GPIO 23
 *   Buzzer - -> GND
 *
 * Libraries (Arduino IDE -> Library Manager):
 *   - WiFi (bundled with ESP32 core)
 *   - WebServer (bundled with ESP32 core)
 *   - mbedTLS (bundled with ESP32 core, used for HMAC)
 *
 * Fill in WIFI_SSID, WIFI_PASS, and SHARED_SECRET below, then flash.
 * Watch the Serial Monitor at 115200 baud for the board's IP address.
 */

#include <WiFi.h>
#include <WebServer.h>
#include "mbedtls/md.h"

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

// Must match the "secret" set on the Nurby webhook action. Leave empty
// to skip signature verification (fine on a trusted LAN).
const char* SHARED_SECRET = "";

const int BUZZER_PIN = 23;

WebServer server(80);

void beepPattern() {
  for (int i = 0; i < 3; i++) {
    tone(BUZZER_PIN, 2000, 150);
    delay(220);
  }
}

String hmacSha256Hex(const String& key, const String& msg) {
  byte hmacResult[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char*)key.c_str(), key.length());
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)msg.c_str(), msg.length());
  mbedtls_md_hmac_finish(&ctx, hmacResult);
  mbedtls_md_free(&ctx);
  String out = "";
  for (int i = 0; i < 32; i++) {
    char buf[3];
    sprintf(buf, "%02x", hmacResult[i]);
    out += buf;
  }
  return out;
}

bool signatureOk(const String& body) {
  if (strlen(SHARED_SECRET) == 0) return true;  // verification disabled
  if (!server.hasHeader("X-Nurby-Signature")) return false;
  String got = server.header("X-Nurby-Signature");
  String want = "sha256=" + hmacSha256Hex(String(SHARED_SECRET), body);
  return got.equals(want);
}

void handleAlert() {
  String body = server.arg("plain");
  if (!signatureOk(body)) {
    server.send(401, "text/plain", "bad signature");
    return;
  }
  Serial.println("ALERT: " + body);
  beepPattern();
  server.send(200, "application/json", "{\"ok\":true}");
}

void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Ready. Point your Nurby webhook at http://");
  Serial.print(WiFi.localIP());
  Serial.println("/alert");

  // Capture the signature header so we can verify it.
  const char* headerKeys[] = {"X-Nurby-Signature"};
  server.collectHeaders(headerKeys, 1);

  server.on("/alert", HTTP_POST, handleAlert);
  server.on("/", HTTP_GET, []() {
    server.send(200, "text/plain", "Nurby ESP32 Buzzer Alarm is alive");
  });
  server.begin();
}

void loop() {
  server.handleClient();
}
