/*
 * RE-BAT AI — ESP32 battery test rig firmware
 * --------------------------------------------
 * Measures pack voltage/current (INA226), temperature (DS18B20), optional per-cell
 * voltages (ADS1115 on balance taps), runs a test protocol
 *   REST -> PULSE -> PULSE_REST -> DISCHARGE -> END_REST -> END
 * and streams readings as JSON to the RE-BAT AI backend:
 *   POST {API_BASE}/api/v1/hardware/ingest   {"readings":[ {...}, ... ]}
 * It polls  GET {API_BASE}/api/v1/hardware/{BATTERY_ID}/commands  for AI-requested
 * diagnostic tests (PULSE, DISCHARGE, THERMAL, REST, CELL_SCAN, CYCLE).
 *
 * SAFETY: the firmware opens the load + contactor on any limit violation, but it is
 * NOT a substitute for a BMS, fuse and thermal cut-off. Never bypass pack protection.
 *
 * Libraries (Arduino Library Manager): ArduinoJson (v7), INA226 (Rob Tillaart),
 * OneWire, DallasTemperature, Adafruit ADS1X15.
 */
#include "config.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <INA226.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#if USE_CELL_TAPS
#include <Adafruit_ADS1X15.h>
#endif

INA226 ina(INA226_ADDR);
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature temps(&oneWire);
#if USE_CELL_TAPS
Adafruit_ADS1115 ads;
bool adsOk = false;
#endif

enum Phase { IDLE, REST, PULSE, PULSE_REST, DISCHARGE, END_REST, DONE, FAULT };
const char* phaseName[] = {"rest", "rest", "pulse", "rest", "run", "rest", "end", "end"};

struct Protocol {
  bool doPulse = true;
  float socEndFraction = 0.0f;   // stop after this fraction of nominal Ah is removed (0 = to cutoff)
  uint32_t maxDischargeS = 4 * 3600;
  uint32_t endRestS = END_REST_S;
  int commandId = -1;            // server command being executed
  String testId = "standard_discharge";
} proto;

Phase phase = IDLE;
uint32_t phaseStartMs = 0, testStartMs = 0, lastSampleMs = 0, lastPollMs = 0;
double ahDischarged = 0;
float lastIR = NAN, vBeforePulse = NAN, iBeforePulse = 0;
float lastTemp = NAN; uint32_t lastTempMs = 0;
JsonDocument batch;
bool irDone = false;
void startTest();
int batchCount = 0;

// ------------------------------------------------------------------ helpers
void loads(bool mainOn, bool pulseOn) {
  digitalWrite(PIN_LOAD_MAIN, mainOn ? HIGH : LOW);
  digitalWrite(PIN_LOAD_PULSE, pulseOn ? HIGH : LOW);
}
void safeStop(const char* why) {
  loads(false, false);
  digitalWrite(PIN_CONTACTOR, LOW);
  phase = FAULT;
  Serial.printf("[SAFETY] %s -> load off, contactor open. Inspect battery.\n", why);
}
void setPhase(Phase p) { phase = p; phaseStartMs = millis(); }
uint32_t inPhaseS() { return (millis() - phaseStartMs) / 1000; }

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  Serial.printf("WiFi %s  IP %s\n", WiFi.status() == WL_CONNECTED ? "OK" : "FAILED", WiFi.localIP().toString().c_str());
}

bool httpPost(const String& path, const String& body) {
  connectWiFi();
  HTTPClient http;
  http.begin(String(API_BASE) + path);
  http.addHeader("Content-Type", "application/json");
  if (strlen(DEVICE_KEY)) http.addHeader("X-Device-Key", DEVICE_KEY);
  int code = http.POST(body);
  http.end();
  return code >= 200 && code < 300;
}

void flushBatch() {
  if (!batchCount) return;
  String body; serializeJson(batch, body);
  if (!httpPost("/api/v1/hardware/ingest", body)) Serial.println("upload failed (will continue)");
  batch.clear(); batchCount = 0;
}

// ------------------------------------------------------------------ measurement
struct Sample { float v, i, t, cmin, cmax; };

Sample measure() {
  Sample s;
  s.v = ina.getBusVoltage();
  s.i = ina.getCurrent();                         // + = discharge (shunt orientation)
  if (millis() - lastTempMs > 750) {              // DS18B20 conversion time
    temps.requestTemperatures();
    float t = temps.getTempCByIndex(0);
    lastTemp = (t > -50 && t < 125) ? t : NAN;
    lastTempMs = millis();
  }
  s.t = lastTemp; s.cmin = NAN; s.cmax = NAN;
#if USE_CELL_TAPS
  if (adsOk) {
    float tap[3];
    for (int k = 0; k < 3; k++) tap[k] = ads.computeVolts(ads.readADC_SingleEnded(k)) * TAP_DIVIDER[k];
    float c[3] = {tap[0], tap[1] - tap[0], tap[2] - tap[1]};
    s.cmin = min(c[0], min(c[1], c[2])); s.cmax = max(c[0], max(c[1], c[2]));
  }
#endif
  return s;
}

void enqueue(const Sample& s, bool last) {
  JsonArray arr = batch["readings"].is<JsonArray>() ? batch["readings"].as<JsonArray>() : batch["readings"].to<JsonArray>();
  JsonObject r = arr.add<JsonObject>();
  r["battery_id"] = BATTERY_ID;
  r["t_s"] = (millis() - testStartMs) / 1000.0;
  r["voltage"] = s.v;
  r["current"] = s.i;
  if (!isnan(s.t)) r["temperature"] = s.t; else r["temperature"] = nullptr;
  r["capacity"] = ahDischarged;
  if (!isnan(lastIR)) r["internal_resistance"] = lastIR;
  if (CYCLE_COUNT >= 0) r["cycle_count"] = CYCLE_COUNT;
  if (!isnan(s.cmin)) { r["cell_v_min"] = s.cmin; r["cell_v_max"] = s.cmax; }
  r["series_cells"] = SERIES_CELLS;
  r["nominal_capacity_ah"] = NOMINAL_AH;
  r["phase"] = last ? "end" : phaseName[phase];
  if (++batchCount >= UPLOAD_EVERY || last) flushBatch();
}

// ------------------------------------------------------------------ safety
float prevTemp = NAN; uint32_t prevTempMs = 0;
bool checkSafety(const Sample& s) {
  float vc = s.v / SERIES_CELLS;
  if (vc < CELL_V_ABS_MIN || vc > CELL_V_ABS_MAX) { safeStop("pack voltage out of range"); return false; }
  if (!isnan(s.cmin) && (s.cmin < CELL_V_ABS_MIN || s.cmax > CELL_V_ABS_MAX)) { safeStop("cell voltage out of range"); return false; }
  if (fabs(s.i) > MAX_CURRENT_A) { safeStop("over-current"); return false; }
  if (!isnan(s.t) && s.t > TEMP_STOP_C) { safeStop("over-temperature"); return false; }
  if (!isnan(s.t)) {
    if (!isnan(prevTemp) && millis() - prevTempMs >= 60000) {
      float rate = (s.t - prevTemp) / ((millis() - prevTempMs) / 60000.0f);
      if (rate > DTDT_STOP_C_MIN) { safeStop("temperature rising too fast"); return false; }
      prevTemp = s.t; prevTempMs = millis();
    } else if (isnan(prevTemp)) { prevTemp = s.t; prevTempMs = millis(); }
  }
  return true;
}

// ------------------------------------------------------------------ commands from the AI
void pollCommands() {
  connectWiFi();
  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/hardware/" + BATTERY_ID + "/commands");
  if (strlen(DEVICE_KEY)) http.addHeader("X-Device-Key", DEVICE_KEY);
  if (http.GET() == 200) {
    JsonDocument doc;
    if (!deserializeJson(doc, http.getString())) {
      JsonArray cmds = doc["commands"].as<JsonArray>();
      if (cmds.size()) {
        JsonObject c = cmds[0];
        String cmd = c["cmd"] | "";
        proto = Protocol();
        proto.commandId = c["id"] | -1;
        proto.testId = c["test_id"] | "requested";
        if (cmd == "PULSE")        { proto.doPulse = true;  proto.socEndFraction = 0.08f; proto.endRestS = 120; }
        else if (cmd == "DISCHARGE"){ proto.doPulse = true;  proto.socEndFraction = 0.0f;  proto.endRestS = 300; }
        else if (cmd == "THERMAL") { proto.doPulse = false; proto.maxDischargeS = c["duration_s"] | 2700; proto.endRestS = 60; }
        else if (cmd == "REST")    { proto.doPulse = false; proto.socEndFraction = 0.3f;  proto.endRestS = c["rest_s"] | 1200; }
        else if (cmd == "CELL_SCAN"){ proto.doPulse = false; proto.socEndFraction = 0.15f; proto.endRestS = 60; }
        else                       { proto.doPulse = true; }   // CYCLE: needs charger relay — discharge part only here
        Serial.printf("Command %d: %s (%s)\n", proto.commandId, cmd.c_str(), proto.testId.c_str());
        startTest();
      }
    }
  }
  http.end();
}

void ackCommand(const char* status) {
  if (proto.commandId < 0) return;
  httpPost("/api/v1/hardware/" + String(BATTERY_ID) + "/commands/" + String(proto.commandId) + "/ack?status=" + status, "{}");
}

void startTest() {
  ahDischarged = 0; lastIR = NAN;
  testStartMs = millis();
  digitalWrite(PIN_CONTACTOR, HIGH);
  loads(false, false);
  setPhase(REST);
}

// ------------------------------------------------------------------ setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_LOAD_MAIN, OUTPUT); pinMode(PIN_LOAD_PULSE, OUTPUT);
  pinMode(PIN_CONTACTOR, OUTPUT); pinMode(PIN_LED, OUTPUT);
  loads(false, false); digitalWrite(PIN_CONTACTOR, LOW);
  Wire.begin(PIN_SDA, PIN_SCL);
  if (!ina.begin()) Serial.println("INA226 not found!");
  ina.setMaxCurrentShunt(MAX_CURRENT_A, SHUNT_OHM);
  ina.setAverage(INA226_16_SAMPLES);
  temps.begin();
#if USE_CELL_TAPS
  adsOk = ads.begin(ADS1115_ADDR);
  ads.setGain(GAIN_ONE);
#endif
  connectWiFi();
  Serial.println("RE-BAT rig ready. Send 's' on serial to start a standard test, or queue a test from the dashboard.");
}

void loop() {
  if (Serial.available() && Serial.read() == 's' && (phase == IDLE || phase == DONE)) { proto = Protocol(); startTest(); }
  if ((phase == IDLE || phase == DONE) && millis() - lastPollMs > 10000) { lastPollMs = millis(); pollCommands(); }
  if (phase == IDLE || phase == DONE || phase == FAULT) { digitalWrite(PIN_LED, phase == FAULT ? (millis() / 200) % 2 : LOW); return; }
  if (millis() - lastSampleMs < SAMPLE_MS) return;
  float dt = (millis() - lastSampleMs) / 1000.0f;
  lastSampleMs = millis();
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));

  Sample s = measure();
  if (!checkSafety(s)) { enqueue(s, true); ackCommand("refused_by_safety"); return; }
  if (s.i > 0) ahDischarged += s.i * dt / 3600.0;
  float vc = s.v / SERIES_CELLS;
  bool last = false;

  switch (phase) {
    case REST:
      if (inPhaseS() >= REST_START_S) {
        vBeforePulse = s.v; iBeforePulse = s.i;
        if (proto.doPulse) { loads(false, true); irDone = false; setPhase(PULSE); } else { loads(true, false); setPhase(DISCHARGE); }
      }
      break;
    case PULSE:
      if (!irDone && s.i - iBeforePulse > 0.2f) { lastIR = (vBeforePulse - s.v) / (s.i - iBeforePulse); irDone = true; }  // DC IR, first loaded sample
      if (inPhaseS() >= PULSE_S) { loads(false, false); setPhase(PULSE_REST); }
      break;
    case PULSE_REST:
      if (inPhaseS() >= PULSE_REST_S) { loads(true, false); setPhase(DISCHARGE); }
      break;
    case DISCHARGE: {
      bool cutoff = vc <= CELL_V_CUTOFF || (!isnan(s.cmin) && s.cmin <= CELL_V_CUTOFF);
      bool enough = proto.socEndFraction > 0 && ahDischarged >= proto.socEndFraction * NOMINAL_AH;
      if (cutoff || enough || inPhaseS() >= proto.maxDischargeS) { loads(false, false); setPhase(END_REST); }
      break; }
    case END_REST:
      if (inPhaseS() >= proto.endRestS) { last = true; setPhase(DONE); digitalWrite(PIN_CONTACTOR, LOW); }
      break;
    default: break;
  }
  enqueue(s, last);
  if (last) { ackCommand("done"); Serial.println("Test complete — forecast produced on the server."); }
}
