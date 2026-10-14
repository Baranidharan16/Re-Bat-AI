/*
  RE-BAT AI 2.0 — ESP32 WebSocket rig
  -----------------------------------
  Hardware: ESP32 DevKit V1, 0-25 V voltage sensor (GPIO36), ACS712 (GPIO39), 0.96" OLED (I2C 21/22),
  MQ gas sensor (GPIO34), LDR (GPIO35), PIR (GPIO27), IR battery-detect (GPIO13), cell taps (GPIO32/33),
  2-channel relay (GPIO25 load, GPIO26 lamp), buzzer (GPIO14), optional DS18B20 (GPIO4).

  Streams one JSON reading per second to the RE-BAT AI backend over a WebSocket:
      ws://WS_HOST:WS_PORT/api/v1/hardware/ws
  and receives:
      {"type":"verdict", "pathway":"REUSE", "best":"Solar energy storage", "soh":77.0, ...}  -> shown on the OLED
      {"type":"command", "cmd":"lamp_on" | "lamp_off" | "lamp_auto" | "start_test" | "quick_test" | "stop" | "load_on" | "load_off"}

  Test:      REST -> 3 PULSES (internal resistance) -> DISCHARGE (capacity) -> RECOVERY -> DONE (relays open = auto turn-off)
  Lamp:      street light, automatic with LDR (dark) + PIR (motion), stops at LAMP_CUTOFF_V per cell
  Safety:    over-temperature, gas rise, over-current, cell over-voltage -> both relays open, buzzer, SAFETY state
  Also serves GET http://<esp32-ip>/api/data (Battery Lab JSON) so the older HTTP-polling bridge still works.

  Libraries (Arduino Library Manager):
    "WebSockets" by Markus Sattler (links2004), "ArduinoJson" v7 by Benoit Blanchon,
    "Adafruit SSD1306" + "Adafruit GFX", and (only if USE_DS18B20) "OneWire" + "DallasTemperature".
  Board: "ESP32 Dev Module" (esp32 by Espressif).

  SAFETY: software limits are an extra layer. Keep the BMS and a fuse between the cells and everything else.
*/
#include "config.h"
#include <WiFi.h>
#include <WebServer.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#if USE_DS18B20
#include <OneWire.h>
#include <DallasTemperature.h>
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds(&oneWire);
#endif

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
WebSocketsClient ws;
WebServer http(80);

enum State { IDLE, REST1, PULSE, DISCHARGE, REST2, DONE, LAMP, SAFETY };
const char* STATE_NAME[] = {"IDLE", "REST", "PULSE", "DISCHARGE", "RECOVERY", "DONE", "LAMP", "SAFETY"};
State state = IDLE;
enum LampMode { LAMP_AUTO, LAMP_FORCE_ON, LAMP_FORCE_OFF };
LampMode lampMode = LAMP_AUTO;

struct Reading {
  float packV, currentA, tempC, gasV, cell[3], cellMin, cellMax;
  int ldr; bool dark, pir, batteryPresent;
} r;

bool quickMode = false, wsUp = false, loadOn = false, lampOn = false, prevPresent = false;
unsigned long stateStart = 0, testStart = 0, lastSample = 0, lastMotion = 0;
float ah = 0, restV = 0, irSum = 0, gasBase = -1, zeroMv = 0, startTemp = NAN;
int irCount = 0, pulseIdx = 0, lowCount = 0;
bool pulseOn = false, irTaken = false;
String verdictLine = "AI: waiting", verdictLine2 = "", faultReason = "";

// ------------------------------------------------------------------ helpers
float mv(int pin, int n = 32);
void beep(int n, int ms = 120);
void sendReading(const char* phaseOverride);
void sendStatus();
void relay(int pin, bool on) { digitalWrite(pin, (on ^ (bool)RELAY_ACTIVE_LOW) ? HIGH : LOW); }
void setLoad(bool on) { loadOn = on; relay(PIN_RELAY_LOAD, on); }
void setLamp(bool on) { lampOn = on; relay(PIN_RELAY_LAMP, on); }
void allOff() { setLoad(false); setLamp(false); }
void beep(int n, int ms) { for (int i = 0; i < n; i++) { digitalWrite(PIN_BUZZER, HIGH); delay(ms); digitalWrite(PIN_BUZZER, LOW); delay(ms); } }
float mv(int pin, int n) { long s = 0; for (int i = 0; i < n; i++) s += analogReadMilliVolts(pin); return (float)s / n; }
void enter(State s) { state = s; stateStart = millis(); }

void readAll() {
  r.packV = mv(PIN_VSENSE) / 1000.0f * VSENSE_RATIO;
  r.currentA = CURRENT_SIGN * ((mv(PIN_ISENSE, 64) * ISENSE_DIV) - zeroMv) / ACS712_MV_PER_A;
  if (fabs(r.currentA) < 0.03f) r.currentA = 0;                     // ACS712 noise floor
  r.gasV = mv(PIN_GAS, 8) / 1000.0f * GAS_DIV;
#if USE_CELL_TAPS
  float a = mv(PIN_TAP_A) / 1000.0f * TAP_A_RATIO, b = mv(PIN_TAP_B) / 1000.0f * TAP_B_RATIO;
  r.cell[0] = a; r.cell[1] = b - a; r.cell[2] = r.packV - b;
#else
  r.cell[0] = r.cell[1] = r.cell[2] = r.packV / SERIES_CELLS;
#endif
  r.cellMin = min(r.cell[0], min(r.cell[1], r.cell[2]));
  r.cellMax = max(r.cell[0], max(r.cell[1], r.cell[2]));
#if USE_DS18B20
  ds.requestTemperatures(); r.tempC = ds.getTempCByIndex(0); if (r.tempC < -50) r.tempC = NAN;
#else
  r.tempC = NAN;
#endif
  r.ldr = analogRead(PIN_LDR);
  r.dark = LDR_DARK_IS_HIGH ? (r.ldr > LDR_DARK_LEVEL) : (r.ldr < LDR_DARK_LEVEL);
  r.pir = digitalRead(PIN_PIR) == HIGH;
  r.batteryPresent = digitalRead(PIN_IR) == LOW;
  if (r.pir) lastMotion = millis();
}

// ------------------------------------------------------------------ test control
void startTest(bool quick) {
  quickMode = quick; ah = 0; irSum = 0; irCount = 0; pulseIdx = 0; lowCount = 0; pulseOn = false; faultReason = "";
  testStart = millis(); startTemp = r.tempC; allOff(); enter(REST1); beep(1);
}
void finish(const char* why) { allOff(); verdictLine2 = why; enter(DONE); beep(3); sendReading("end"); }
void fault(const String& why) { allOff(); faultReason = why; enter(SAFETY); beep(5, 200); sendReading("end"); }

void safetyCheck() {
  if (state == IDLE || state == DONE || state == SAFETY) return;
  if (!isnan(r.tempC) && r.tempC > MAX_TEMP_C) fault("Over temperature");
  else if (gasBase > 0 && r.gasV > gasBase + GAS_DELTA_V) fault("Gas / venting");
  else if (r.cellMax > CELL_FULL_V + 0.05f) fault("Cell over-voltage");
  else if (fabs(r.currentA) > MAX_CURRENT_A) fault("Over current");
  else if (state != LAMP && !r.batteryPresent && millis() - testStart > 5000) fault("Battery removed");
}

void step() {
  unsigned long el = millis() - stateStart;
  switch (state) {
    case REST1:
      if (el >= (quickMode ? 20000UL : 60000UL)) { restV = r.packV; setLoad(true); pulseOn = true; irTaken = false; pulseIdx = 0; enter(PULSE); }
      break;
    case PULSE:                                                    // 3 load pulses -> DC internal resistance
      if (pulseOn && !irTaken && el >= 2000 && r.currentA > 0.05f) { irSum += (restV - r.packV) / r.currentA; irCount++; irTaken = true; }
      if (pulseOn && el >= 10000) { setLoad(false); pulseOn = false; stateStart = millis(); }
      else if (!pulseOn && el >= 10000) {
        restV = r.packV;
        if (++pulseIdx >= 3) { setLoad(true); enter(DISCHARGE); }
        else { setLoad(true); pulseOn = true; irTaken = false; stateStart = millis(); }
      }
      break;
    case DISCHARGE:                                                // capacity test until the weakest cell reaches cut-off
      lowCount = (r.cellMin <= CELL_CUTOFF_V) ? lowCount + 1 : 0;
      if (lowCount >= 3 || (quickMode && el >= 120000UL) || el >= 6UL * 3600000UL) { setLoad(false); enter(REST2); }
      break;
    case REST2:
      if (el >= (quickMode ? 30000UL : 180000UL)) finish("Test done - load OFF");
      break;
    case LAMP: {                                                   // second-life street light
      bool want = lampMode == LAMP_FORCE_ON || (lampMode == LAMP_AUTO && r.dark && millis() - lastMotion < LAMP_HOLD_MS);
      if (lampMode == LAMP_FORCE_OFF) want = false;
      if (r.cellMin <= LAMP_CUTOFF_V) { finish("Lamp off: battery low"); break; }
      setLamp(want);
      break;
    }
    default: break;
  }
  // outside a test the lamp follows its mode too (manual on/off from the dashboard)
  if (state == IDLE || state == DONE) {
    bool want = lampMode == LAMP_FORCE_ON || (lampMode == LAMP_AUTO && r.dark && millis() - lastMotion < LAMP_HOLD_MS && r.batteryPresent && r.cellMin > LAMP_CUTOFF_V);
    if (lampMode == LAMP_FORCE_OFF) want = false;
    setLamp(want);
  }
}

// ------------------------------------------------------------------ network
const char* phaseFor() {
  switch (state) { case PULSE: return "pulse"; case DISCHARGE: case LAMP: return "run"; default: return "rest"; }
}

void sendReading(const char* phaseOverride) {
  JsonDocument d;
  d["battery_id"] = BATTERY_ID;
  d["t_s"] = millis() / 1000.0;                                   // monotonic since boot
  d["voltage"] = r.packV;
  d["current"] = r.currentA;
  if (!isnan(r.tempC)) d["temperature"] = r.tempC;
  d["capacity"] = ah;
  if (CYCLE_COUNT >= 0) d["cycle_count"] = CYCLE_COUNT;
  if (irCount) d["internal_resistance"] = irSum / irCount;        // ohm, pack
#if USE_CELL_TAPS
  d["cell_v_min"] = r.cellMin; d["cell_v_max"] = r.cellMax;
#endif
  d["series_cells"] = SERIES_CELLS;
  d["nominal_capacity_ah"] = NOMINAL_AH;
  d["gas_v"] = r.gasV;
  if (gasBase > 0) d["gas_baseline_v"] = gasBase;
  d["phase"] = phaseOverride ? phaseOverride : phaseFor();
  d["ldr"] = r.ldr; d["dark"] = r.dark; d["pir"] = r.pir; d["battery_present"] = r.batteryPresent;
  d["lamp_on"] = lampOn; d["load_on"] = loadOn; d["rig_state"] = STATE_NAME[state];
  String s; serializeJson(d, s);
  if (wsUp) ws.sendTXT(s);
  Serial.println(s);
}

void sendStatus() {
  JsonDocument d;
  d["type"] = "status"; d["battery_id"] = BATTERY_ID; d["voltage"] = r.packV; d["current"] = r.currentA;
  d["ldr"] = r.ldr; d["dark"] = r.dark; d["pir"] = r.pir; d["battery_present"] = r.batteryPresent;
  d["lamp_on"] = lampOn; d["load_on"] = loadOn; d["rig_state"] = STATE_NAME[state];
  String s; serializeJson(d, s); ws.sendTXT(s);
}

void handleCommand(const String& cmd) {
  if (cmd == "start_test") startTest(false);
  else if (cmd == "quick_test") startTest(true);
  else if (cmd == "stop") { allOff(); enter(IDLE); }
  else if (cmd == "lamp_on") { lampMode = LAMP_FORCE_ON; if (state == IDLE || state == DONE) { testStart = millis(); enter(LAMP); } }
  else if (cmd == "lamp_off") { lampMode = LAMP_FORCE_OFF; setLamp(false); }
  else if (cmd == "lamp_auto") { lampMode = LAMP_AUTO; if (state == IDLE || state == DONE) { testStart = millis(); enter(LAMP); } }
  else if (cmd == "load_on" && state != SAFETY) setLoad(true);
  else if (cmd == "load_off") setLoad(false);
  beep(1, 60);
}

void onWs(WStype_t type, uint8_t* payload, size_t len) {
  if (type == WStype_CONNECTED) {
    wsUp = true;
    JsonDocument h; h["type"] = "hello"; h["battery_id"] = BATTERY_ID; h["firmware"] = "rebat-ws 2.0"; h["ip"] = WiFi.localIP().toString();
    String s; serializeJson(h, s); ws.sendTXT(s);
  } else if (type == WStype_DISCONNECTED) {
    wsUp = false;
  } else if (type == WStype_TEXT) {
    JsonDocument d;
    if (deserializeJson(d, payload, len)) return;
    String t = d["type"] | "";
    if (t == "command") handleCommand(d["cmd"] | "");
    else if (t == "verdict") {
      String p = d["pathway"] | "?";
      verdictLine = "AI: " + p + " " + String((float)(d["soh"] | 0.0f), 0) + "%";
      String best = d["best"] | "";
      verdictLine2 = p == "RECYCLE" ? "Recover minerals" : best.substring(0, 21);
    }
  }
}

void handleApiData() {                                             // Battery Lab format for the HTTP-polling bridge
  JsonDocument d;
  d["battery_v"] = r.packV; d["current_a"] = r.currentA; d["temperature_c"] = isnan(r.tempC) ? 0 : r.tempC;
  d["gas_v"] = r.gasV; d["capacity_mah"] = ah * 1000; d["elapsed_s"] = (millis() - testStart) / 1000;
  d["ldr"] = r.ldr; d["dark"] = r.dark; d["pir"] = r.pir; d["battery_present"] = r.batteryPresent;
  d["lamp_on"] = lampOn; d["load_on"] = loadOn; d["rig_state"] = STATE_NAME[state];
  d["ip"] = WiFi.localIP().toString(); d["rssi"] = WiFi.RSSI();
  String s; serializeJson(d, s);
  http.sendHeader("Access-Control-Allow-Origin", "*");
  http.send(200, "application/json", s);
}

// ------------------------------------------------------------------ display
void draw() {
  oled.clearDisplay(); oled.setTextSize(1); oled.setTextColor(SSD1306_WHITE); oled.setCursor(0, 0);
  oled.printf("%s%s %s\n", STATE_NAME[state], quickMode && state != LAMP ? "(q)" : "", wsUp ? "WS" : "--");
  oled.printf("%.2fV %.2fA %.1fW\n", r.packV, r.currentA, r.packV * r.currentA);
  oled.printf("Ah %.3f IR %s\n", ah, irCount ? String(irSum / irCount * 1000, 0).c_str() : "--");
  oled.printf("Cell %.2f-%.2f\n", r.cellMin, r.cellMax);
  oled.printf("%s %s %s L%s\n", r.dark ? "Dark" : "Day", r.pir ? "PIR" : "---", r.batteryPresent ? "BAT" : "---", lampOn ? "ON" : "off");
  if (state == SAFETY) oled.printf("STOP %s\n", faultReason.c_str());
  else oled.println(verdictLine);
  oled.println(verdictLine2);
  oled.display();
}

// ------------------------------------------------------------------ setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELAY_LOAD, OUTPUT); pinMode(PIN_RELAY_LAMP, OUTPUT); allOff();   // relays open from the start
  pinMode(PIN_BUZZER, OUTPUT); pinMode(PIN_PIR, INPUT); pinMode(PIN_IR, INPUT_PULLUP);
  analogSetAttenuation(ADC_11db);
  Wire.begin(PIN_SDA, PIN_SCL);
  oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
#if USE_DS18B20
  ds.begin(); ds.setResolution(10);
#endif
  oled.clearDisplay(); oled.setTextColor(SSD1306_WHITE); oled.setCursor(0, 0);
  oled.println("RE-BAT AI 2.0"); oled.println("Calibrating..."); oled.display();
  zeroMv = mv(PIN_ISENSE, 400) * ISENSE_DIV;                      // ACS712 zero with both relays open
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  ws.begin(WS_HOST, WS_PORT, WS_PATH);
  ws.onEvent(onWs);
  ws.setReconnectInterval(3000);
  ws.enableHeartbeat(15000, 3000, 2);
  http.on("/api/data", handleApiData);
  http.begin();
  testStart = millis();
  Serial.printf("IP %s  ->  ws://%s:%d%s\n", WiFi.localIP().toString().c_str(), WS_HOST, WS_PORT, WS_PATH);
  beep(1);
}

void loop() {
  ws.loop();
  http.handleClient();
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 's') startTest(false); else if (c == 'q') startTest(true); else if (c == 'x') { allOff(); enter(IDLE); }
    else if (c == 'l') handleCommand("lamp_auto");
  }
  if (millis() - lastSample < SAMPLE_MS) return;
  float dtH = (millis() - lastSample) / 3600000.0f;
  lastSample = millis();
  readAll();
  if (gasBase < 0 && millis() > 60000) gasBase = r.gasV;          // MQ baseline after 1 min warm-up
  if (state != IDLE && state != DONE && state != SAFETY && r.currentA > 0) ah += r.currentA * dtH;
  if (AUTO_START_ON_INSERT && r.batteryPresent && !prevPresent && (state == IDLE || state == DONE)) startTest(true);
  prevPresent = r.batteryPresent;
  safetyCheck();
  step();
  draw();
  if (state != IDLE && state != DONE && state != SAFETY) sendReading(nullptr);   // test or lamp: real telemetry
  else if (wsUp) sendStatus();                                                     // idle: sensors only, no test window
}
