"""
RE-BAT AI · Solar → second-life battery digital twin
====================================================

Physics model of a small off-grid solar system whose storage is a *retired EV
Li-ion pack* that has already been measured on the RE-BAT rig.

    Sun ──► PV panel ──► MPPT charge controller ──► second-life pack ──► LED street light
                                     │                       ▲
                                     └──── direct PV→load ───┘

Everything is driven by the *measured* battery parameters (capacity, internal
resistance, cell spread, chemistry), so the twin answers: "given what the rig
measured, how does THIS battery behave as solar storage, and how long will it
last?"

Models used (all simple, documented, deterministic for a given seed):

* Sun position      — declination + hour angle for the site latitude.
* Clear-sky GHI     — Haurwitz model: GHI = 1098·sin(α)·exp(−0.057/sin α).
* Clouds            — Ornstein–Uhlenbeck clear-sky index per weather class.
* Ambient temp      — monthly Chennai min/max, sinusoidal day curve.
* PV panel          — STC rating × G/1000 × (1 + γ(Tcell−25)) × derate,
                      Tcell from NOCT.
* Charge controller — MPPT efficiency, CC/CV with taper, temperature derate,
                      low-voltage disconnect with hysteresis, curtailment.
* Battery           — OCV(SOC) table × series cells + ohmic resistance,
                      coulomb counting, lumped thermal model (exact exponential
                      update, stable for any step size).
* Ageing            — semi-empirical: cycle fade per equivalent full cycle
                      (Arrhenius in T, C-rate stress, knee below 70 % SOH) +
                      calendar fade (Arrhenius in T, SOC stress). Resistance
                      grows with capacity fade.

Ageing coefficients are literature-order-of-magnitude values for aged NMC/LFP,
NOT fitted to this specific pack. Treat lifetime numbers as a projection to be
recalibrated with repeat rig measurements.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Constants & chemistry tables
# --------------------------------------------------------------------------- #
R_GAS = 8.314
T_REF_K = 298.15
GRID_CO2_KG_PER_KWH = 0.71  # India grid emission factor (CEA, approx.)

OCV_SOC = [0.00, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
CHEMISTRY: Dict[str, Dict[str, Any]] = {
    "NMC": {
        "ocv": [3.00, 3.30, 3.45, 3.55, 3.62, 3.67, 3.72, 3.79, 3.87, 3.95, 4.05, 4.18],
        "v_cv_cell": 4.10,      # second-life: stop below 4.2 V to slow ageing
        "v_min_cell": 3.20,     # under-load cut-off
        "wh_per_kg": 200.0,
        "cal_fade_per_year": 0.012,  # at 25 °C, 50 % SOC
        "cyc_fade_per_efc": 0.00018,
    },
    "LFP": {
        "ocv": [2.80, 3.05, 3.18, 3.24, 3.27, 3.29, 3.30, 3.31, 3.32, 3.33, 3.35, 3.55],
        "v_cv_cell": 3.50,
        "v_min_cell": 2.90,
        "wh_per_kg": 150.0,
        "cal_fade_per_year": 0.008,
        "cyc_fade_per_efc": 0.00008,
    },
}

# Chennai climate profile (°C min, °C max) per month — used for ambient temperature
CHENNAI_TEMPS = [(21, 29), (22, 31), (24, 33), (27, 35), (28, 38), (28, 37),
                 (27, 35), (26, 34), (26, 34), (25, 32), (23, 30), (22, 29)]

# Seasonal weather probabilities for "auto" weather (clear, partly, cloudy, monsoon)
SEASON_WEATHER = {
    1: (0.60, 0.30, 0.10, 0.00), 2: (0.65, 0.28, 0.07, 0.00), 3: (0.60, 0.32, 0.08, 0.00),
    4: (0.50, 0.40, 0.10, 0.00), 5: (0.50, 0.40, 0.10, 0.00), 6: (0.30, 0.45, 0.22, 0.03),
    7: (0.15, 0.45, 0.35, 0.05), 8: (0.15, 0.45, 0.35, 0.05), 9: (0.15, 0.45, 0.33, 0.07),
    10: (0.10, 0.35, 0.30, 0.25), 11: (0.08, 0.30, 0.30, 0.32), 12: (0.15, 0.35, 0.30, 0.20),
}
WEATHER_KINDS = ("clear", "partly", "cloudy", "monsoon")
# clear-sky index process: (mean, std, correlation time in s)
CLOUD_PARAMS = {
    "clear": (0.96, 0.03, 1800.0),
    "partly": (0.72, 0.22, 900.0),
    "cloudy": (0.42, 0.14, 1500.0),
    "monsoon": (0.20, 0.09, 2400.0),
}


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class PanelSpec:
    rated_w: float = 100.0           # STC power
    vmp: float = 18.0                # STC max-power voltage (display only)
    temp_coeff: float = -0.0040      # per °C
    noct: float = 45.0
    derate: float = 0.88             # soiling, wiring, mismatch
    poa_factor: float = 1.00         # plane-of-array / GHI (tilt ≈ latitude)


@dataclass
class PackMeasurement:
    """What the RE-BAT rig measured on the retired battery."""
    chemistry: str = "NMC"
    series_cells: int = 4
    nominal_capacity_ah: float = 30.0
    measured_capacity_ah: float = 23.4
    internal_resistance_mohm: float = 48.0   # whole pack, DC pulse
    cell_spread_mv: float = 18.0             # max−min cell voltage at rest
    cycle_count: int = 820                   # from BMS / estimate
    initial_soc: float = 0.55

    @property
    def soh(self) -> float:
        return max(0.05, min(1.2, self.measured_capacity_ah / self.nominal_capacity_ah))


@dataclass
class LoadSpec:
    led_w: float = 12.0          # street light
    on_hour: float = 18.0
    off_hour: float = 6.0
    dim_start: float = 23.0
    dim_end: float = 5.0
    dim_level: float = 0.5
    base_w: float = 0.6          # ESP32 monitoring node, always on


@dataclass
class ControllerSpec:
    mppt_eff: float = 0.96
    charge_c_rate: float = 0.30      # gentle CC for aged cells
    max_charge_a: float = 15.0       # controller hardware limit
    max_discharge_c: float = 0.5
    taper_c: float = 0.03            # CV terminates below this C-rate → "Full"
    v_cv_cell: Optional[float] = None  # None → chemistry default
    soc_lvd: float = 0.10            # low-voltage disconnect
    soc_reconnect: float = 0.25
    t_charge_min: float = 0.0
    t_charge_max: float = 45.0
    t_derate_start: float = 40.0
    t_discharge_max: float = 55.0


@dataclass
class SiteSpec:
    name: str = "Kavaraipettai / Chennai"
    latitude: float = 13.08
    weather: str = "auto"            # auto | clear | partly | cloudy | monsoon
    enclosure_solar_gain_c: float = 8.0  # battery box heating at 1000 W/m²
    start_date: str = "2026-10-14"
    start_hour: float = 6.0


@dataclass
class AgeingSpec:
    eol_soh: float = 0.60            # end of second life
    ea_cyc: float = 31_500.0         # J/mol
    ea_cal: float = 50_000.0
    knee_soh: float = 0.70
    knee_gain: float = 6.0
    r_growth: float = 2.5            # ΔR/R per relative capacity loss


@dataclass
class SystemConfig:
    panel: PanelSpec = field(default_factory=PanelSpec)
    pack: PackMeasurement = field(default_factory=PackMeasurement)
    load: LoadSpec = field(default_factory=LoadSpec)
    ctrl: ControllerSpec = field(default_factory=ControllerSpec)
    site: SiteSpec = field(default_factory=SiteSpec)
    ageing: AgeingSpec = field(default_factory=AgeingSpec)

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> "SystemConfig":
        d = d or {}
        cfg = SystemConfig()
        for key, cls in (("panel", PanelSpec), ("pack", PackMeasurement), ("load", LoadSpec),
                         ("ctrl", ControllerSpec), ("site", SiteSpec), ("ageing", AgeingSpec)):
            if key in d and d[key]:
                allowed = {k: v for k, v in d[key].items() if k in cls.__dataclass_fields__}
                setattr(cfg, key, replace(getattr(cfg, key), **allowed))
        cfg.validate()
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        p = self.pack
        if p.chemistry not in CHEMISTRY:
            raise ValueError(f"chemistry must be one of {list(CHEMISTRY)}")
        if not 1 <= p.series_cells <= 200:
            raise ValueError("series_cells must be 1..200")
        if p.nominal_capacity_ah <= 0 or p.measured_capacity_ah <= 0:
            raise ValueError("capacities must be > 0")
        if p.internal_resistance_mohm <= 0:
            raise ValueError("internal_resistance_mohm must be > 0")
        if not 0 <= p.initial_soc <= 1:
            raise ValueError("initial_soc must be 0..1")
        if self.panel.rated_w < 0 or self.load.led_w < 0:
            raise ValueError("powers must be >= 0")
        if self.site.weather not in ("auto",) + WEATHER_KINDS:
            raise ValueError("unknown weather")


PRESETS: Dict[str, Dict[str, Any]] = {
    "ev_module_streetlight": {
        "label": "Retired EV module (4S NMC 30 Ah) · 100 W panel · 12 W street light",
        "config": SystemConfig().to_dict(),
    },
    "rig_cell_demo": {
        "label": "Rig test cell (1S 18650) · 6 W panel · 0.35 W LED (bench demo)",
        "config": SystemConfig(
            panel=PanelSpec(rated_w=6.0, vmp=6.0),
            pack=PackMeasurement(chemistry="NMC", series_cells=1, nominal_capacity_ah=3.0,
                                 measured_capacity_ah=2.3, internal_resistance_mohm=70.0,
                                 cell_spread_mv=0.0, cycle_count=600, initial_soc=0.5),
            load=LoadSpec(led_w=0.35, base_w=0.08),
            ctrl=ControllerSpec(max_charge_a=1.0),
        ).to_dict(),
    },
    "household_lfp": {
        "label": "Retired LFP pack (8S 50 Ah) · 300 W panel · 40 W household lights + fan",
        "config": SystemConfig(
            panel=PanelSpec(rated_w=300.0, vmp=31.0),
            pack=PackMeasurement(chemistry="LFP", series_cells=8, nominal_capacity_ah=50.0,
                                 measured_capacity_ah=41.0, internal_resistance_mohm=32.0,
                                 cell_spread_mv=25.0, cycle_count=1500, initial_soc=0.6),
            load=LoadSpec(led_w=40.0, on_hour=18.0, off_hour=6.0, dim_start=22.0,
                          dim_end=5.0, dim_level=0.35, base_w=1.0),
            ctrl=ControllerSpec(max_charge_a=25.0),
        ).to_dict(),
    },
}


# --------------------------------------------------------------------------- #
# Environment helpers
# --------------------------------------------------------------------------- #
def interp(x: float, xs: List[float], ys: List[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            f = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + f * (ys[i] - ys[i - 1])
    return ys[-1]


def ocv_cell(soc: float, chem: str) -> float:
    return interp(soc, OCV_SOC, CHEMISTRY[chem]["ocv"])


def soc_from_ocv(v_cell: float, chem: str) -> float:
    return interp(v_cell, CHEMISTRY[chem]["ocv"], OCV_SOC)


def sun_sin_altitude(lat_deg: float, doy: int, hour: float) -> float:
    decl = math.radians(23.45) * math.sin(math.radians(360.0 / 365.0 * (284 + doy)))
    lat = math.radians(lat_deg)
    omega = math.radians(15.0 * (hour - 12.0))
    return math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(omega)


def clear_sky_ghi(sin_alt: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance, W/m²."""
    if sin_alt <= 0.01:
        return 0.0
    return 1098.0 * sin_alt * math.exp(-0.057 / sin_alt)


def ambient_temp(month: int, hour: float, weather: str) -> float:
    tmin, tmax = CHENNAI_TEMPS[month - 1]
    if weather == "monsoon":
        tmax -= 4.0
    elif weather == "cloudy":
        tmax -= 2.0
    # minimum at 06:00, maximum at 15:00 (asymmetric cosine)
    if 6.0 <= hour <= 15.0:
        f = (1 - math.cos(math.pi * (hour - 6.0) / 9.0)) / 2
    else:
        h = hour - 15.0 if hour > 15.0 else hour + 9.0
        f = (1 + math.cos(math.pi * h / 15.0)) / 2
    return tmin + (tmax - tmin) * f


def load_demand(hour: float, load: LoadSpec) -> float:
    def in_window(h: float, start: float, end: float) -> bool:
        return (start <= h < end) if start <= end else (h >= start or h < end)

    p = load.base_w
    if in_window(hour, load.on_hour, load.off_hour):
        dim = in_window(hour, load.dim_start, load.dim_end)
        p += load.led_w * (load.dim_level if dim else 1.0)
    return p


class CloudProcess:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.k = 0.9

    def step(self, dt: float, weather: str) -> float:
        mean, sd, tau = CLOUD_PARAMS[weather]
        a = math.exp(-dt / tau)
        self.k = mean + (self.k - mean) * a + sd * math.sqrt(max(0.0, 1 - a * a)) * self.rng.gauss(0, 1)
        self.k = min(1.05, max(0.05, self.k))
        return self.k


# --------------------------------------------------------------------------- #
# The twin
# --------------------------------------------------------------------------- #
class SolarBatterySystem:
    """Stateful solar + second-life battery twin. Call `advance(seconds)`."""

    def __init__(self, cfg: SystemConfig, seed: Optional[int] = 7, log_events: bool = True):
        cfg.validate()
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.clouds = CloudProcess(self.rng)
        self.chem = CHEMISTRY[cfg.pack.chemistry]
        p = cfg.pack

        self.t0 = datetime.fromisoformat(cfg.site.start_date) + timedelta(hours=cfg.site.start_hour)
        self.t = 0.0                                   # simulated seconds since t0
        self.soc = p.initial_soc
        self.soh = p.soh
        self.soh0 = p.soh
        self.r0 = p.internal_resistance_mohm / 1000.0
        self.r_pack = self.r0
        self.efc = float(p.cycle_count)
        self.ah_throughput = 0.0
        mass = max(0.045, p.nominal_capacity_ah * 3.7 / self.chem["wh_per_kg"]) * p.series_cells
        self.c_th = mass * 1000.0                      # J/K
        self.h_a = 1.5 * mass ** (2.0 / 3.0)           # W/K (in a vented box)
        self.load_on = True
        self.mode = "Idle"
        self._logged_mode = "Idle"
        self._pending_mode: Optional[str] = None
        self._pending_since = 0.0
        self.log_events = log_events
        self.events: List[Dict[str, Any]] = []
        self.event_seq = 0
        self._last_led_on: Optional[bool] = None
        self._day_weather = self._pick_weather()
        self.t_batt = ambient_temp(self.now.month, self.hour, self._day_weather)
        self.cell_spread_v = p.cell_spread_mv / 1000.0
        v_cv = cfg.ctrl.v_cv_cell or self.chem["v_cv_cell"]
        self.v_cv_cell = v_cv
        self.soc_cv = soc_from_ocv(v_cv, p.chemistry)

        self.totals = {"pv_wh": 0.0, "curtailed_wh": 0.0, "load_wh": 0.0, "unmet_wh": 0.0,
                       "charge_wh": 0.0, "discharge_wh": 0.0, "loss_wh": 0.0}
        self._new_day_counters()
        self.day_summaries: List[Dict[str, Any]] = []
        self._fade_rate_per_day: Optional[float] = None
        self._soh_at_t0 = self.soh
        self.last: Dict[str, Any] = {}
        self._compute_outputs(0.0)

    # ---------------- clock ----------------
    @property
    def now(self) -> datetime:
        return self.t0 + timedelta(seconds=self.t)

    @property
    def hour(self) -> float:
        n = self.now
        return n.hour + n.minute / 60.0 + n.second / 3600.0

    def _pick_weather(self) -> str:
        w = self.cfg.site.weather
        if w != "auto":
            return w
        probs = SEASON_WEATHER[self.now.month]
        r, acc = self.rng.random(), 0.0
        for kind, pr in zip(WEATHER_KINDS, probs):
            acc += pr
            if r <= acc:
                return kind
        return "partly"

    def set_weather(self, weather: str) -> None:
        if weather not in ("auto",) + WEATHER_KINDS:
            raise ValueError("unknown weather")
        self.cfg.site.weather = weather
        self._day_weather = self._pick_weather()

    def _new_day_counters(self) -> None:
        self.day = {"date": self.now.date().isoformat(), "pv_wh": 0.0, "curtailed_wh": 0.0,
                    "load_wh": 0.0, "demand_wh": 0.0, "unmet_wh": 0.0, "soc_min": self.soc,
                    "soc_max": self.soc, "t_batt_max": -99.0, "soh_start": self.soh,
                    "peak_pv_w": 0.0}

    def _event(self, kind: str, msg: str) -> None:
        if self.log_events:
            self.event_seq += 1
            self.events.append({"seq": self.event_seq, "t": self.now.isoformat(timespec="minutes"),
                                "kind": kind, "msg": msg})
            if len(self.events) > 300:
                self.events = self.events[-300:]

    # ---------------- physics ----------------
    def step(self, dt: float) -> None:
        c, p = self.cfg, self.cfg.pack
        ctrl = c.ctrl
        prev_date = self.now.date()
        hour = self.hour
        month = self.now.month
        doy = self.now.timetuple().tm_yday

        # --- environment
        sin_alt = sun_sin_altitude(c.site.latitude, doy, hour)
        k = self.clouds.step(dt, self._day_weather)
        g = clear_sky_ghi(sin_alt) * k * c.panel.poa_factor
        t_amb = ambient_temp(month, hour, self._day_weather)
        t_panel = t_amb + (c.panel.noct - 20.0) / 800.0 * g
        p_pv_avail = max(0.0, c.panel.rated_w * g / 1000.0
                         * (1 + c.panel.temp_coeff * (t_panel - 25.0)) * c.panel.derate)

        # --- battery state
        ns = p.series_cells
        cap_ah = p.nominal_capacity_ah * self.soh
        ocv = ns * ocv_cell(self.soc, p.chemistry)
        r = self.r_pack
        tb = self.t_batt

        # --- load + LVD hysteresis
        p_dem = load_demand(hour, c.load)
        led_on_sched = p_dem > c.load.base_w + 1e-9
        if self.load_on and self.soc <= ctrl.soc_lvd:
            self.load_on = False
            self._event("protect", f"Low-voltage disconnect at SOC {self.soc*100:.0f}% — load shed")
        elif not self.load_on and self.soc >= ctrl.soc_reconnect:
            self.load_on = True
            self._event("protect", f"Load reconnected at SOC {self.soc*100:.0f}%")

        eta = ctrl.mppt_eff
        pv_bus = p_pv_avail * eta
        charge_ok = ctrl.t_charge_min <= tb <= ctrl.t_charge_max

        # --- charge limits (CC / CV / thermal derate)
        i_cc_nom = min(ctrl.charge_c_rate * cap_ah, ctrl.max_charge_a)
        i_cc = i_cc_nom
        if tb > ctrl.t_derate_start:
            i_cc *= max(0.0, (ctrl.t_charge_max - tb) / (ctrl.t_charge_max - ctrl.t_derate_start))
        v_cv = ns * self.v_cv_cell
        i_cv = max(0.0, (v_cv - ocv) / r)
        full = self.soc >= self.soc_cv - 1e-4 or i_cv < ctrl.taper_c * cap_ah
        i_chg_max = 0.0 if (not charge_ok or full) else min(i_cc, i_cv)

        # --- 1) serve the load: PV first, battery covers the deficit
        p_dis = 0.0
        shed = None
        if p_dem <= 0:
            served = 0.0
        elif not self.load_on:
            served, shed = 0.0, "Load shed (LVD)"
        else:
            pv_to_load = min(pv_bus, p_dem)
            deficit = p_dem - pv_to_load
            if deficit <= 1e-9:
                served = p_dem
            elif tb > ctrl.t_discharge_max:
                served, shed = 0.0, "Thermal hold"
            else:
                i_max_dis = ctrl.max_discharge_c * cap_ah
                p_max_dis = max(0.0, (ocv - i_max_dis * r) * i_max_dis)
                e_avail_w = self.soc * cap_ah * ocv * 3600.0 / dt  # don't overdraw in one step
                if min(p_max_dis, e_avail_w, 0.999 * ocv * ocv / (4 * r)) + 1e-9 >= deficit:
                    served, p_dis = p_dem, deficit
                else:
                    served, shed = 0.0, "Load shed (limit)"

        # --- 2) leftover PV charges the battery (MPPT backs off when limited)
        pv_left = pv_bus - (served - p_dis)
        p_chg = 0.0
        if p_dis == 0.0 and pv_left > 1e-9 and i_chg_max > 1e-9:
            p_chg_max = (ocv + i_chg_max * r) * i_chg_max
            p_chg = min(pv_left, p_chg_max)
        p_batt = p_chg - p_dis

        if p_dis > 0:
            mode = "Discharging"
        elif p_chg > 0:
            if p_chg < (ocv + i_chg_max * r) * i_chg_max - 1e-6:
                mode = "MPPT charge"
            elif i_cv <= i_cc:
                mode = "CV charge"
            elif i_cc < i_cc_nom - 1e-6:
                mode = "Charge (thermal derate)"
            else:
                mode = "CC charge"
        elif shed:
            mode = shed
        elif pv_left > 1e-9 and not charge_ok:
            mode = "Thermal hold"
        elif pv_left > 1e-9 and full:
            mode = "Full · float"
        else:
            mode = "Idle"

        pv_used = min(p_pv_avail, (served - p_dis + p_chg) / eta) if eta > 0 else 0.0
        curtailed = max(0.0, p_pv_avail - pv_used)

        # --- solve current from power: R I² + OCV I − P = 0
        disc = ocv * ocv + 4 * r * p_batt
        i = (-ocv + math.sqrt(max(0.0, disc))) / (2 * r) if abs(p_batt) > 1e-12 else 0.0
        v_term = ocv + i * r

        # --- SOC
        coul = 0.995 if i > 0 else 1.0
        soc_before = self.soc
        self.soc += i * coul * dt / 3600.0 / cap_ah
        if i > 0:
            self.soc = min(self.soc, max(self.soc_cv, soc_before))
        self.soc = min(1.0, max(0.0, self.soc))

        # --- thermal (exact exponential update)
        q = i * i * r
        t_env = t_amb + c.site.enclosure_solar_gain_c * min(1.0, g / 1000.0)
        t_eq = t_env + q / self.h_a
        tau = self.c_th / self.h_a
        self.t_batt = t_eq + (tb - t_eq) * math.exp(-dt / tau)

        # --- ageing
        tk = tb + 273.15
        d_ah = abs(i) * dt / 3600.0
        self.ah_throughput += d_ah
        d_efc = d_ah / (2.0 * max(1e-6, cap_ah))
        self.efc += d_efc
        a = c.ageing
        arr_cyc = math.exp(-a.ea_cyc / R_GAS * (1 / tk - 1 / T_REF_K))
        arr_cal = math.exp(-a.ea_cal / R_GAS * (1 / tk - 1 / T_REF_K))
        c_rate = abs(i) / max(1e-6, cap_ah)
        knee = 1.0 + max(0.0, a.knee_soh - self.soh) * a.knee_gain
        d_cyc = self.chem["cyc_fade_per_efc"] * d_efc * arr_cyc * (1 + 0.8 * c_rate) * knee
        soc_stress = (0.4 + 0.9 * self.soc) / 0.85
        d_cal = self.chem["cal_fade_per_year"] / (365.25 * 86400.0) * dt * arr_cal * soc_stress
        self.soh = max(0.0, self.soh - d_cyc - d_cal)
        self.r_pack = self.r0 * (1 + a.r_growth * max(0.0, self.soh0 - self.soh) / self.soh0)

        # --- accounting (Wh)
        h = dt / 3600.0
        e_pv, e_cur = pv_used * h, curtailed * h
        e_load, e_dem = served * h, p_dem * h
        for k_, v_ in (("pv_wh", e_pv), ("curtailed_wh", e_cur), ("load_wh", e_load),
                       ("unmet_wh", e_dem - e_load)):
            self.totals[k_] += v_
        self.totals["charge_wh"] += max(0.0, p_batt) * h
        self.totals["discharge_wh"] += max(0.0, -p_batt) * h
        self.totals["loss_wh"] += (q + pv_used * (1 - eta)) * h
        d = self.day
        d["pv_wh"] += e_pv
        d["curtailed_wh"] += e_cur
        d["load_wh"] += e_load
        d["demand_wh"] += e_dem
        d["unmet_wh"] += e_dem - e_load
        d["soc_min"] = min(d["soc_min"], self.soc)
        d["soc_max"] = max(d["soc_max"], self.soc)
        d["t_batt_max"] = max(d["t_batt_max"], self.t_batt)
        d["peak_pv_w"] = max(d["peak_pv_w"], pv_used)

        # --- events (debounced: a mode must persist 5 sim-minutes before it is logged)
        if mode != self._logged_mode:
            if mode != self._pending_mode:
                self._pending_mode, self._pending_since = mode, self.t
            elif self.t - self._pending_since >= 300.0:
                self._event("mode", f"{self._logged_mode} → {mode}")
                self._logged_mode = mode
        else:
            self._pending_mode = None
        if self._last_led_on is not None and led_on_sched != self._last_led_on:
            self._event("load", "Street light ON" if led_on_sched else "Street light OFF")
        self._last_led_on = led_on_sched
        self.mode = mode

        self.t += dt
        if self.now.date() != prev_date:
            self._close_day()

        # cache instantaneous outputs
        self._inst = dict(ghi=g, clear_index=k, t_amb=t_amb, t_panel=t_panel, sin_alt=sin_alt,
                          p_pv_avail=p_pv_avail, p_pv=pv_used, p_curtailed=curtailed,
                          p_load_demand=p_dem, p_load=served, p_batt=p_batt, i_batt=i,
                          v_batt=v_term, ocv=ocv, led_on=led_on_sched and served > 0)

    def _close_day(self) -> None:
        d = self.day
        fade = d["soh_start"] - self.soh
        self._fade_rate_per_day = fade if self._fade_rate_per_day is None else (
            0.8 * self._fade_rate_per_day + 0.2 * fade)
        d["soh_end"] = self.soh
        d["weather"] = self._day_weather
        d["served_pct"] = 100.0 * d["load_wh"] / d["demand_wh"] if d["demand_wh"] > 0 else 100.0
        self.day_summaries.append({k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()})
        if len(self.day_summaries) > 4000:
            self.day_summaries = self.day_summaries[-4000:]
        self._day_weather = self._pick_weather()
        self._new_day_counters()
        if self.log_events:
            self._event("day", f"New day · weather: {self._day_weather}")

    # ---------------- outputs ----------------
    def _compute_outputs(self, _dt: float) -> None:
        if not hasattr(self, "_inst"):
            ocv = self.cfg.pack.series_cells * ocv_cell(self.soc, self.cfg.pack.chemistry)
            self._inst = dict(ghi=0.0, clear_index=1.0, t_amb=self.t_batt, t_panel=self.t_batt,
                              sin_alt=0.0, p_pv_avail=0.0, p_pv=0.0, p_curtailed=0.0,
                              p_load_demand=0.0, p_load=0.0, p_batt=0.0, i_batt=0.0,
                              v_batt=ocv, ocv=ocv, led_on=False)

    def rul_years(self) -> Optional[float]:
        eol = self.cfg.ageing.eol_soh
        if self.soh <= eol:
            return 0.0
        rate = self._fade_rate_per_day
        if rate is None:
            elapsed_days = self.t / 86400.0
            if elapsed_days < 0.25:
                return None
            rate = (self._soh_at_t0 - self.soh) / elapsed_days
        if rate <= 0:
            return None
        return (self.soh - eol) / rate / 365.25

    def snapshot(self) -> Dict[str, Any]:
        p = self.cfg.pack
        inst = self._inst
        cap_ah = p.nominal_capacity_ah * self.soh
        v_nom = p.series_cells * ocv_cell(0.5, p.chemistry)
        usable_wh = max(0.0, self.soc - self.cfg.ctrl.soc_lvd) * cap_ah * v_nom
        night_w = self.cfg.load.led_w * 0.75 + self.cfg.load.base_w
        spread = self.cell_spread_v * (2.0 if (self.soc < 0.2 or self.soc > 0.9) else 1.0)
        v_cell = inst["v_batt"] / p.series_cells
        rul = self.rul_years()
        return {
            "sim_time": self.now.isoformat(timespec="seconds"),
            "hour": round(self.hour, 4),
            "elapsed_s": round(self.t, 1),
            "weather": self._day_weather,
            "mode": self.mode,
            "load_connected": self.load_on,
            "sun": {"ghi_wm2": round(inst["ghi"], 1), "clear_index": round(inst["clear_index"], 3),
                    "sin_altitude": round(inst["sin_alt"], 4)},
            "temps": {"ambient_c": round(inst["t_amb"], 2), "panel_c": round(inst["t_panel"], 2),
                      "battery_c": round(self.t_batt, 2)},
            "power": {"pv_available_w": round(inst["p_pv_avail"], 3), "pv_w": round(inst["p_pv"], 3),
                      "curtailed_w": round(inst["p_curtailed"], 3),
                      "load_demand_w": round(inst["p_load_demand"], 3), "load_w": round(inst["p_load"], 3),
                      "battery_w": round(inst["p_batt"], 3)},
            "panel": {"v": round(self.cfg.panel.vmp * (1 - 0.0035 * (inst["t_panel"] - 25)), 2) if inst["p_pv"] > 0 else 0.0,
                      "i": round(inst["p_pv"] / max(0.1, self.cfg.panel.vmp * (1 - 0.0035 * (inst["t_panel"] - 25))), 3)
                      if inst["p_pv"] > 0 else 0.0},
            "battery": {"voltage_v": round(inst["v_batt"], 3), "ocv_v": round(inst["ocv"], 3),
                        "current_a": round(inst["i_batt"], 4), "soc": round(self.soc, 5),
                        "soh": round(self.soh, 6), "capacity_ah": round(cap_ah, 4),
                        "resistance_mohm": round(self.r_pack * 1000, 3), "efc": round(self.efc, 3),
                        "usable_wh": round(usable_wh, 2),
                        "autonomy_h": round(usable_wh / night_w, 2) if night_w > 0 else None,
                        "cell_v_min": round(v_cell - spread / 2, 4), "cell_v_max": round(v_cell + spread / 2, 4)},
            "led_on": bool(inst["led_on"]),
            "rul_years": None if rul is None else round(rul, 2),
            "today": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.day.items()},
            "totals": {k: round(v, 3) for k, v in self.totals.items()},
        }

    def canonical_reading(self, battery_id: str = "SOLAR-TWIN-01") -> Dict[str, Any]:
        """Map the current state onto RE-BAT's canonical telemetry schema.

        `current` is charge-positive here; data_ingestion's sign normalisation
        should be checked/adjusted for this source. `capacity` is the twin's
        present full-charge capacity estimate in Ah.
        """
        s = self.snapshot()
        b = s["battery"]
        return {"battery_id": battery_id, "timestamp": s["sim_time"], "voltage": b["voltage_v"],
                "current": b["current_a"], "temperature": s["temps"]["battery_c"],
                "capacity": b["capacity_ah"], "cycle": int(b["efc"]),
                "internal_resistance": b["resistance_mohm"] / 1000.0,
                "cell_v_min": b["cell_v_min"], "cell_v_max": b["cell_v_max"], "source": "SOLAR_TWIN"}

    def advance(self, seconds: float, substep: float = 10.0) -> Dict[str, Any]:
        remaining = seconds
        while remaining > 1e-9:
            dt = min(substep, remaining)
            self.step(dt)
            remaining -= dt
        return self.snapshot()


# --------------------------------------------------------------------------- #
# Lifetime projection
# --------------------------------------------------------------------------- #
def project_lifetime(cfg: SystemConfig, max_years: float = 15.0, step_s: float = 900.0,
                     seed: int = 11) -> Dict[str, Any]:
    """Run the twin day after day until end of second life (or max_years)."""
    sysm = SolarBatterySystem(SystemConfig.from_dict(cfg.to_dict()), seed=seed, log_events=False)
    weekly: List[Dict[str, Any]] = []
    eol = cfg.ageing.eol_soh
    days_total = int(max_years * 365.25)
    eol_day = None
    for day in range(days_total):
        sysm.advance(86400.0, substep=step_s)
        if day % 7 == 0:
            s = sysm.day_summaries[-1] if sysm.day_summaries else {}
            weekly.append({"day": day, "date": sysm.now.date().isoformat(), "soh": round(sysm.soh, 5),
                           "resistance_mohm": round(sysm.r_pack * 1000, 2), "efc": round(sysm.efc, 1),
                           "served_pct": round(s.get("served_pct", 100.0), 2),
                           "t_batt_max": round(s.get("t_batt_max", 0.0), 2)})
        if sysm.soh <= eol:
            eol_day = day + 1
            break
    ds = sysm.day_summaries
    nights_full = sum(1 for d in ds if d["unmet_wh"] < 0.01 * max(1e-9, d["demand_wh"]))
    load_kwh = sysm.totals["load_wh"] / 1000.0
    return {
        "eol_soh": eol,
        "start_soh": round(cfg.pack.soh, 4),
        "years_simulated": round(len(ds) / 365.25, 2),
        "reached_eol": eol_day is not None,
        "years_to_eol": round(eol_day / 365.25, 2) if eol_day else None,
        "eol_date": sysm.now.date().isoformat() if eol_day else None,
        "final_soh": round(sysm.soh, 4),
        "final_resistance_mohm": round(sysm.r_pack * 1000, 2),
        "efc_added": round(sysm.efc - cfg.pack.cycle_count, 1),
        "energy_delivered_kwh": round(load_kwh, 2),
        "pv_harvested_kwh": round(sysm.totals["pv_wh"] / 1000.0, 2),
        "curtailed_kwh": round(sysm.totals["curtailed_wh"] / 1000.0, 2),
        "unmet_kwh": round(sysm.totals["unmet_wh"] / 1000.0, 2),
        "nights_fully_served_pct": round(100.0 * nights_full / max(1, len(ds)), 2),
        "co2_avoided_kg": round(load_kwh * GRID_CO2_KG_PER_KWH, 1),
        "weekly": weekly,
        "note": "Ageing coefficients are literature-order values, not fitted to this pack; "
                "re-measure on the rig every few months and update the twin.",
    }


def gentle_variant(cfg: SystemConfig) -> SystemConfig:
    """Same system, but charge stops ~10 % SOC earlier (lower CV voltage)."""
    c2 = SystemConfig.from_dict(cfg.to_dict())
    chem = CHEMISTRY[c2.pack.chemistry]
    base = c2.ctrl.v_cv_cell or chem["v_cv_cell"]
    target_soc = max(0.5, soc_from_ocv(base, c2.pack.chemistry) - 0.10)
    c2.ctrl.v_cv_cell = round(ocv_cell(target_soc, c2.pack.chemistry), 3)
    return c2


def compare_lifetime(cfg: SystemConfig, max_years: float = 15.0) -> Dict[str, Any]:
    """Three what-if scenarios for the same measured battery."""
    gentle = gentle_variant(cfg)
    shaded = gentle_variant(cfg)
    shaded.site.enclosure_solar_gain_c = min(2.0, cfg.site.enclosure_solar_gain_c)
    std_v = cfg.ctrl.v_cv_cell or CHEMISTRY[cfg.pack.chemistry]["v_cv_cell"]
    return {
        "standard": {"label": f"Standard charge ({std_v:.2f} V/cell)", "v_cv_cell": std_v,
                     **project_lifetime(cfg, max_years)},
        "gentle": {"label": f"Gentle charge ({gentle.ctrl.v_cv_cell:.2f} V/cell)",
                   "v_cv_cell": gentle.ctrl.v_cv_cell, **project_lifetime(gentle, max_years)},
        "shaded_gentle": {"label": "Gentle charge + shaded battery box", "v_cv_cell": shaded.ctrl.v_cv_cell,
                          **project_lifetime(shaded, max_years)},
    }
