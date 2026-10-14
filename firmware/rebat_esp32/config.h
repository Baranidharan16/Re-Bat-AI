// ===== RE-BAT AI test rig configuration =====================================
#pragma once

// ---- network -----------------------------------------------------------------
#define WIFI_SSID        "YOUR_WIFI"
#define WIFI_PASSWORD    "YOUR_PASSWORD"
// Laptop running the backend on the same Wi-Fi (find its IP with ipconfig / ifconfig)
#define API_BASE         "http://192.168.1.50:8000"
#define DEVICE_KEY       ""            // set if the server has REBAT_DEVICE_KEY

// ---- battery under test --------------------------------------------------------
#define BATTERY_ID       "RB-001"
#define SERIES_CELLS     3
#define NOMINAL_AH       2.5f
#define CYCLE_COUNT      -1            // -1 = unknown (sent as null)

// ---- pins (ESP32 DevKit v1) ----------------------------------------------------
#define PIN_SDA          21
#define PIN_SCL          22
#define PIN_ONEWIRE      4             // DS18B20 data (4.7k pull-up to 3V3)
#define PIN_LOAD_MAIN    25            // gate driver -> MOSFET -> main load resistor
#define PIN_LOAD_PULSE   26            // gate driver -> MOSFET -> pulse load resistor
#define PIN_CONTACTOR    27            // relay/contactor enable (pack connected when HIGH)
#define PIN_LED          2

// ---- sensors -------------------------------------------------------------------
#define INA226_ADDR      0x40
#define SHUNT_OHM        0.010f        // 10 mΩ shunt
#define MAX_CURRENT_A    8.0f
#define ADS1115_ADDR     0x48          // optional cell taps (comment out to disable)
#define USE_CELL_TAPS    1
// divider ratios for tap1 (cell1), tap2 (cell1+2), tap3 (cell1+2+3) into ADS1115 A0..A2
static const float TAP_DIVIDER[3] = {2.0f, 4.0f, 6.0f};

// ---- test protocol (defaults; server commands override) ------------------------
#define SAMPLE_MS        1000          // 1 Hz sampling
#define UPLOAD_EVERY     10            // readings per HTTP batch
#define REST_START_S     60
#define PULSE_S          20
#define PULSE_REST_S     30
#define END_REST_S       180

// ---- software safety limits (hardware BMS / fuse must ALSO protect) ------------
#define CELL_V_CUTOFF    3.00f         // stop discharge
#define CELL_V_ABS_MIN   2.50f         // alarm
#define CELL_V_ABS_MAX   4.25f
#define TEMP_STOP_C      55.0f
#define DTDT_STOP_C_MIN  2.0f
