// ===== RE-BAT AI 2.0 — ESP32 WebSocket rig configuration =====================
// Edit the four network lines, then flash. Everything else matches the wiring in hardware/README.md.
#pragma once

// ---- network -----------------------------------------------------------------
#define WIFI_SSID        "YOUR_WIFI"            // laptop and ESP32 must be on the SAME Wi-Fi (phone hotspot is easiest)
#define WIFI_PASSWORD    "YOUR_PASSWORD"
#define WS_HOST          "192.168.1.10"         // laptop IP — shown on the dashboard's Live ESP32 page
#define WS_PORT          8000
#define WS_PATH          "/api/v1/hardware/ws"  // add "?key=..." if the server sets REBAT_DEVICE_KEY

// ---- battery under test --------------------------------------------------------
#define BATTERY_ID       "RB-001"
#define SERIES_CELLS     3
#define NOMINAL_AH       2.5f
#define CYCLE_COUNT      -1                     // -1 = unknown
#define CELL_CUTOFF_V    3.00f                  // capacity test ends here (NMC). LFP: 2.60
#define CELL_FULL_V      4.20f                  // NMC. LFP: 3.60
#define LAMP_CUTOFF_V    3.40f                  // street light stops earlier to protect the cells. LFP: 3.00

// ---- pins (ESP32 DevKit V1) ----------------------------------------------------
#define PIN_SDA          21                     // OLED only
#define PIN_SCL          22
#define PIN_VSENSE       36                     // VP  – 0-25 V voltage sensor "S"
#define PIN_ISENSE       39                     // VN  – ACS712 OUT through 10k/20k divider
#define PIN_GAS          34                     // MQ AO through 10k/20k divider
#define PIN_LDR          35                     // LDR module AO (powered from 3.3 V)
#define PIN_TAP_A        32                     // cell 1 (+) through 10k/22k
#define PIN_TAP_B        33                     // cell 2 (+) through 27k/10k
#define PIN_PIR          27
#define PIN_IR           13                     // IR obstacle sensor: LOW = battery in the bay
#define PIN_RELAY_LOAD   25                     // relay CH1 – capacity-test load (or the lamp itself)
#define PIN_RELAY_LAMP   26                     // relay CH2 – 12 V street-light lamp
#define PIN_BUZZER       14
#define PIN_DS18B20      4                      // optional
#define USE_DS18B20      0                      // 1 if a DS18B20 is fitted (4.7k pull-up to 3.3 V)
#define RELAY_ACTIVE_LOW 1                      // blue relay boards switch ON with LOW

// ---- sensor calibration (check with a multimeter) --------------------------------
#define VSENSE_RATIO     5.00f                  // 0-25 V module = 30k/7.5k
#define ISENSE_DIV       1.50f                  // (10k + 20k) / 20k divider on ACS712 OUT
#define ACS712_MV_PER_A  185.0f                 // 5 A = 185, 20 A = 100, 30 A = 66
#define CURRENT_SIGN     1.0f                   // set -1 if discharge shows negative
#define TAP_A_RATIO      ((10.0f + 22.0f) / 22.0f)
#define TAP_B_RATIO      ((27.0f + 10.0f) / 10.0f)
#define USE_CELL_TAPS    1                      // 0 if the tap resistors are not fitted yet
#define LDR_DARK_LEVEL   2500                   // ADC counts; above = dark (flip with LDR_DARK_IS_HIGH)
#define LDR_DARK_IS_HIGH 1
#define GAS_DELTA_V      0.40f                  // alarm when gas rises this much above its start value
#define GAS_DIV          1.50f

// ---- behaviour ------------------------------------------------------------------
#define SAMPLE_MS        1000
#define AUTO_START_ON_INSERT 1                  // start the quick test when the IR sees a battery
#define LAMP_HOLD_MS     60000                  // street light stays on 60 s after the last motion
#define MAX_TEMP_C       55.0f
#define MAX_CURRENT_A    4.5f
