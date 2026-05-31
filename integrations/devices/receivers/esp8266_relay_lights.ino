/*
 * Nurby ESP8266 Relay Lights
 * --------------------------
 * Switches a relay on for HOLD_MS when Nurby POSTs an alert to /alert.
 * Use it to flash a lamp, strobe, or siren. Optional HMAC verification.
 *
 * Hardware:
 *   Relay IN  -> GPIO 5 (D1 on a Wemos D1 mini / NodeMCU)
 *   Relay VCC -> 5V
 *   Relay GND -> GND
 *   Switch your lamp/siren through the relay COM and NO terminals.
 *
 * SAFETY: mains voltage is dangerous. Use a pre-built, enclosed relay
 * module and keep all high-voltage wiring inside a proper enclosure. If
 * you are not confident with mains wiring, drive a low-voltage siren
 * instead.
 *
 * Libraries: ESP8266WiFi, ESP8266WebServer (both in the ESP8266 core),
 * Hash (bundled, provides sha256/hmac helpers via BearSSL).
 */

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <bearssl/bearssl_hmac.h>

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SHARED_SECRET = "";  // empty = skip signature check

const int RELAY_PIN = 5;       // D1
const unsigned long HOLD_MS = 4000;  // how long the light stays on
const bool RELAY_ACTIVE_HIGH = true; // flip if your relay is active-low

ESP8266WebServer server(80);

String hmacSha256Hex(const String& key, const String& msg) {
  br_hmac_key_context kc;
  br_hmac_context hc;
  br_hmac_key_init(&kc, &br_sha256_vtable, key.c_str(), key.length());
  br_hmac_init(&hc, &kc, 0);
  br_hmac_update(&hc, msg.c_str(), msg.length());
  unsigned char out[32];
  br_hmac_out(&hc, out);
  String hex = "";
  for (int i = 0; i < 32; i++) {
    char buf[3];
    sprintf(buf, "%02x", out[i]);
    hex += buf;
  }
  return hex;
}

bool signatureOk(const String& body) {
  if (strlen(SHARED_SECRET) == 0) return true;
  if (!server.hasHeader("X-Nurby-Signature")) return false;
  String want = "sha256=" + hmacSha256Hex(String(SHARED_SECRET), body);
  return server.header("X-Nurby-Signature").equals(want);
}

void relayOn()  { digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? HIGH : LOW); }
void relayOff() { digitalWrite(RELAY_PIN, RELAY_ACTIVE_HIGH ? LOW : HIGH); }

void handleAlert() {
  String body = server.arg("plain");
  if (!signatureOk(body)) {
    server.send(401, "text/plain", "bad signature");
    return;
  }
  Serial.println("ALERT: " + body);
  relayOn();
  delay(HOLD_MS);
  relayOff();
  server.send(200, "application/json", "{\"ok\":true}");
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  relayOff();

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.println();
  Serial.print("Ready. Point your Nurby webhook at http://");
  Serial.print(WiFi.localIP());
  Serial.println("/alert");

  const char* headerKeys[] = {"X-Nurby-Signature"};
  server.collectHeaders(headerKeys, 1);
  server.on("/alert", HTTP_POST, handleAlert);
  server.on("/", HTTP_GET, []() {
    server.send(200, "text/plain", "Nurby ESP8266 Relay Lights is alive");
  });
  server.begin();
}

void loop() {
  server.handleClient();
}
