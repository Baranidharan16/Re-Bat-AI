/* RE-BAT AI · Solar → second-life battery twin (browser engine).
   Line-for-line port of backend/app/services/solar_sim.py so the dashboard can
   run on its own; the Python service is the reference implementation. */
(function (root) {
  "use strict";
  const R_GAS = 8.314, T_REF_K = 298.15, GRID_CO2 = 0.71;
  const OCV_SOC = [0, .05, .10, .20, .30, .40, .50, .60, .70, .80, .90, 1.0];
  const CHEM = {
    NMC: { ocv: [3.00, 3.30, 3.45, 3.55, 3.62, 3.67, 3.72, 3.79, 3.87, 3.95, 4.05, 4.18],
           v_cv_cell: 4.10, v_min_cell: 3.20, wh_per_kg: 200, cal_fade_per_year: 0.012, cyc_fade_per_efc: 0.00018 },
    LFP: { ocv: [2.80, 3.05, 3.18, 3.24, 3.27, 3.29, 3.30, 3.31, 3.32, 3.33, 3.35, 3.55],
           v_cv_cell: 3.50, v_min_cell: 2.90, wh_per_kg: 150, cal_fade_per_year: 0.008, cyc_fade_per_efc: 0.00008 },
  };
  const TEMPS = [[21, 29], [22, 31], [24, 33], [27, 35], [28, 38], [28, 37], [27, 35], [26, 34], [26, 34], [25, 32], [23, 30], [22, 29]];
  const SEASON = { 1: [.60, .30, .10, 0], 2: [.65, .28, .07, 0], 3: [.60, .32, .08, 0], 4: [.50, .40, .10, 0], 5: [.50, .40, .10, 0],
    6: [.30, .45, .22, .03], 7: [.15, .45, .35, .05], 8: [.15, .45, .35, .05], 9: [.15, .45, .33, .07], 10: [.10, .35, .30, .25],
    11: [.08, .30, .30, .32], 12: [.15, .35, .30, .20] };
  const KINDS = ["clear", "partly", "cloudy", "monsoon"];
  const CLOUD = { clear: [.96, .03, 1800], partly: [.72, .22, 900], cloudy: [.42, .14, 1500], monsoon: [.20, .09, 2400] };

  function defaults() {
    return {
      panel: { rated_w: 100, vmp: 18, temp_coeff: -0.004, noct: 45, derate: 0.88, poa_factor: 1.0 },
      pack: { chemistry: "NMC", series_cells: 4, nominal_capacity_ah: 30, measured_capacity_ah: 23.4,
              internal_resistance_mohm: 48, cell_spread_mv: 18, cycle_count: 820, initial_soc: 0.55 },
      load: { led_w: 12, on_hour: 18, off_hour: 6, dim_start: 23, dim_end: 5, dim_level: 0.5, base_w: 0.6 },
      ctrl: { mppt_eff: 0.96, charge_c_rate: 0.30, max_charge_a: 15, max_discharge_c: 0.5, taper_c: 0.03, v_cv_cell: null,
              soc_lvd: 0.10, soc_reconnect: 0.25, t_charge_min: 0, t_charge_max: 45, t_derate_start: 40, t_discharge_max: 55 },
      site: { name: "Kavaraipettai / Chennai", latitude: 13.08, weather: "auto", enclosure_solar_gain_c: 8,
              start_date: "2026-10-14", start_hour: 6 },
      ageing: { eol_soh: 0.60, ea_cyc: 31500, ea_cal: 50000, knee_soh: 0.70, knee_gain: 6, r_growth: 2.5 },
    };
  }
  function merge(over) {
    const c = defaults();
    for (const k in over || {}) if (c[k] && over[k]) Object.assign(c[k], over[k]);
    return c;
  }
  const PRESETS = {
    ev_module_streetlight: { label: "Retired EV module · 4S NMC 30 Ah · 100 W panel · 12 W street light", config: {} },
    rig_cell_demo: { label: "Rig test cell · 1S 18650 · 6 W panel · 0.35 W LED (bench demo)", config: {
      panel: { rated_w: 6, vmp: 6 },
      pack: { chemistry: "NMC", series_cells: 1, nominal_capacity_ah: 3.0, measured_capacity_ah: 2.3, internal_resistance_mohm: 70,
              cell_spread_mv: 0, cycle_count: 600, initial_soc: 0.5 },
      load: { led_w: 0.35, base_w: 0.08 }, ctrl: { max_charge_a: 1.0 } } },
    household_lfp: { label: "Retired LFP pack · 8S 50 Ah · 300 W panel · 40 W household lights + fan", config: {
      panel: { rated_w: 300, vmp: 31 },
      pack: { chemistry: "LFP", series_cells: 8, nominal_capacity_ah: 50, measured_capacity_ah: 41, internal_resistance_mohm: 32,
              cell_spread_mv: 25, cycle_count: 1500, initial_soc: 0.6 },
      load: { led_w: 40, on_hour: 18, off_hour: 6, dim_start: 22, dim_end: 5, dim_level: 0.35, base_w: 1.0 },
      ctrl: { max_charge_a: 25 } } },
  };

  function validate(c) {
    const p = c.pack;
    if (!CHEM[p.chemistry]) throw new Error("Chemistry must be NMC or LFP.");
    if (!(p.series_cells >= 1 && p.series_cells <= 200)) throw new Error("Series cells must be between 1 and 200.");
    if (!(p.nominal_capacity_ah > 0 && p.measured_capacity_ah > 0)) throw new Error("Capacities must be greater than 0 Ah.");
    if (!(p.internal_resistance_mohm > 0)) throw new Error("Internal resistance must be greater than 0 mΩ.");
    if (!(p.initial_soc >= 0 && p.initial_soc <= 1)) throw new Error("Start SOC must be between 0 and 100 %.");
    if (c.panel.rated_w < 0 || c.load.led_w < 0) throw new Error("Powers cannot be negative.");
  }

  function interp(x, xs, ys) {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
    for (let i = 1; i < xs.length; i++) if (x <= xs[i]) {
      const f = (x - xs[i - 1]) / (xs[i] - xs[i - 1]); return ys[i - 1] + f * (ys[i] - ys[i - 1]);
    }
    return ys[ys.length - 1];
  }
  const ocvCell = (soc, chem) => interp(soc, OCV_SOC, CHEM[chem].ocv);
  const socFromOcv = (v, chem) => interp(v, CHEM[chem].ocv, OCV_SOC);
  const rad = (d) => d * Math.PI / 180;
  function decl(doy) { return rad(23.45) * Math.sin(rad(360 / 365 * (284 + doy))); }
  function sunSinAlt(lat, doy, hour) {
    const d = decl(doy), la = rad(lat), w = rad(15 * (hour - 12));
    return Math.sin(la) * Math.sin(d) + Math.cos(la) * Math.cos(d) * Math.cos(w);
  }
  function sunTimes(lat, doy) {
    const x = -Math.tan(rad(lat)) * Math.tan(decl(doy));
    const w0 = Math.acos(Math.max(-1, Math.min(1, x))) * 180 / Math.PI / 15;
    return [12 - w0, 12 + w0];
  }
  const clearSky = (s) => s <= 0.01 ? 0 : 1098 * s * Math.exp(-0.057 / s);
  function ambient(month, hour, weather) {
    let [tmin, tmax] = TEMPS[month - 1];
    if (weather === "monsoon") tmax -= 4; else if (weather === "cloudy") tmax -= 2;
    let f;
    if (hour >= 6 && hour <= 15) f = (1 - Math.cos(Math.PI * (hour - 6) / 9)) / 2;
    else { const h = hour > 15 ? hour - 15 : hour + 9; f = (1 + Math.cos(Math.PI * h / 15)) / 2; }
    return tmin + (tmax - tmin) * f;
  }
  function inWin(h, s, e) { return s <= e ? (h >= s && h < e) : (h >= s || h < e); }
  function loadDemand(hour, L) {
    let p = L.base_w;
    if (inWin(hour, L.on_hour, L.off_hour)) p += L.led_w * (inWin(hour, L.dim_start, L.dim_end) ? L.dim_level : 1);
    return p;
  }
  function rng(seed) {
    let a = (seed >>> 0) || 1, spare = null;
    const u = () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    u.gauss = () => { if (spare !== null) { const s = spare; spare = null; return s; }
      let x, y, r; do { x = 2 * u() - 1; y = 2 * u() - 1; r = x * x + y * y; } while (r >= 1 || r === 0);
      const m = Math.sqrt(-2 * Math.log(r) / r); spare = y * m; return x * m; };
    return u;
  }
  const r2 = (v, n) => { const f = Math.pow(10, n); return Math.round(v * f) / f; };

  class Twin {
    constructor(cfgIn, seed = 7, logEvents = true) {
      const cfg = merge(JSON.parse(JSON.stringify(cfgIn || {})));
      validate(cfg);
      this.cfg = cfg; this.rand = rng(seed); this.k = 0.9; this.chem = CHEM[cfg.pack.chemistry];
      const p = cfg.pack;
      const [y, m, d] = cfg.site.start_date.split("-").map(Number);
      this.date0 = Date.UTC(y, m - 1, d);
      this.t = 0;
      this.soc = p.initial_soc; this.soh = this.soh0 = Math.max(0.05, Math.min(1.2, p.measured_capacity_ah / p.nominal_capacity_ah));
      this.r0 = this.r_pack = p.internal_resistance_mohm / 1000;
      this.efc = p.cycle_count; this.ah = 0;
      const mass = Math.max(0.045, p.nominal_capacity_ah * 3.7 / this.chem.wh_per_kg) * p.series_cells;
      this.c_th = mass * 1000; this.h_a = 1.5 * Math.pow(mass, 2 / 3);
      this.load_on = true; this.mode = "Idle"; this.loggedMode = "Idle"; this.pendMode = null; this.pendSince = 0;
      this.logEvents = logEvents; this.events = []; this.seq = 0; this.lastLed = null;
      this._dayCache = -1; this._updDate();
      this.dayWeather = this.pickWeather();
      this.t_batt = ambient(this.month, this.hour, this.dayWeather);
      this.spread = p.cell_spread_mv / 1000;
      this.v_cv_cell = cfg.ctrl.v_cv_cell || this.chem.v_cv_cell;
      this.soc_cv = socFromOcv(this.v_cv_cell, p.chemistry);
      this.totals = { pv_wh: 0, curtailed_wh: 0, load_wh: 0, unmet_wh: 0, charge_wh: 0, discharge_wh: 0, loss_wh: 0 };
      this.days = []; this.fade = null; this.soh_t0 = this.soh;
      this.newDay();
      const ocv = p.series_cells * ocvCell(this.soc, p.chemistry);
      this.inst = { ghi: 0, k: 1, t_amb: this.t_batt, t_panel: this.t_batt, sin_alt: 0, pv_avail: 0, pv: 0, cur: 0,
                    dem: 0, served: 0, pb: 0, i: 0, v: ocv, ocv, led: false };
    }
    get hour() { return ((this.cfg.site.start_hour + this.t / 3600) % 24 + 24) % 24; }
    get dayIndex() { return Math.floor((this.cfg.site.start_hour + this.t / 3600) / 24); }
    _updDate() {
      const di = this.dayIndex; if (di === this._dayCache) return; this._dayCache = di;
      const dt = new Date(this.date0 + di * 86400000);
      this.month = dt.getUTCMonth() + 1;
      this.doy = Math.floor((Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate()) - Date.UTC(dt.getUTCFullYear(), 0, 1)) / 86400000) + 1;
      this.dateStr = dt.toISOString().slice(0, 10);
    }
    nowIso() {
      const h = this.hour, hh = Math.floor(h), mm = Math.floor((h - hh) * 60), ss = Math.floor(((h - hh) * 60 - mm) * 60);
      return `${this.dateStr}T${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
    }
    pickWeather() {
      const w = this.cfg.site.weather; if (w !== "auto") return w;
      const pr = SEASON[this.month]; const r = this.rand(); let acc = 0;
      for (let i = 0; i < 4; i++) { acc += pr[i]; if (r <= acc) return KINDS[i]; }
      return "partly";
    }
    setWeather(w) { this.cfg.site.weather = w; this.dayWeather = this.pickWeather(); this.ev("day", `Weather set to ${w}`); }
    newDay() { this.day = { date: this.dateStr, pv_wh: 0, curtailed_wh: 0, load_wh: 0, demand_wh: 0, unmet_wh: 0,
                            soc_min: this.soc, soc_max: this.soc, t_batt_max: -99, soh_start: this.soh, peak_pv_w: 0 }; }
    ev(kind, msg) {
      if (!this.logEvents) return;
      this.seq++; this.events.push({ seq: this.seq, t: this.nowIso().slice(0, 16), kind, msg });
      if (this.events.length > 300) this.events = this.events.slice(-300);
    }
    step(dt) {
      const c = this.cfg, p = c.pack, ctrl = c.ctrl;
      const prevDay = this.dayIndex, hour = this.hour;
      // environment
      const sinAlt = sunSinAlt(c.site.latitude, this.doy, hour);
      const [mean, sd, tau] = CLOUD[this.dayWeather]; const a = Math.exp(-dt / tau);
      this.k = mean + (this.k - mean) * a + sd * Math.sqrt(Math.max(0, 1 - a * a)) * this.rand.gauss();
      this.k = Math.min(1.05, Math.max(0.05, this.k));
      const g = clearSky(sinAlt) * this.k * c.panel.poa_factor;
      const tAmb = ambient(this.month, hour, this.dayWeather);
      const tPanel = tAmb + (c.panel.noct - 20) / 800 * g;
      const pvAvail = Math.max(0, c.panel.rated_w * g / 1000 * (1 + c.panel.temp_coeff * (tPanel - 25)) * c.panel.derate);
      // battery
      const ns = p.series_cells, capAh = p.nominal_capacity_ah * this.soh;
      const ocv = ns * ocvCell(this.soc, p.chemistry), r = this.r_pack, tb = this.t_batt;
      // load & LVD
      const dem = loadDemand(hour, c.load), ledSched = dem > c.load.base_w + 1e-9;
      if (this.load_on && this.soc <= ctrl.soc_lvd) { this.load_on = false; this.ev("protect", `Low-voltage disconnect at SOC ${(this.soc * 100).toFixed(0)}% — load shed`); }
      else if (!this.load_on && this.soc >= ctrl.soc_reconnect) { this.load_on = true; this.ev("protect", `Load reconnected at SOC ${(this.soc * 100).toFixed(0)}%`); }
      const eta = ctrl.mppt_eff, pvBus = pvAvail * eta;
      const chargeOk = tb >= ctrl.t_charge_min && tb <= ctrl.t_charge_max;
      const iccNom = Math.min(ctrl.charge_c_rate * capAh, ctrl.max_charge_a);
      let icc = iccNom;
      if (tb > ctrl.t_derate_start) icc *= Math.max(0, (ctrl.t_charge_max - tb) / (ctrl.t_charge_max - ctrl.t_derate_start));
      const icv = Math.max(0, (ns * this.v_cv_cell - ocv) / r);
      const full = this.soc >= this.soc_cv - 1e-4 || icv < ctrl.taper_c * capAh;
      const ichgMax = (!chargeOk || full) ? 0 : Math.min(icc, icv);
      // 1) load
      let pdis = 0, shed = null, served;
      if (dem <= 0) served = 0;
      else if (!this.load_on) { served = 0; shed = "Load shed (LVD)"; }
      else {
        const pvToLoad = Math.min(pvBus, dem), deficit = dem - pvToLoad;
        if (deficit <= 1e-9) served = dem;
        else if (tb > ctrl.t_discharge_max) { served = 0; shed = "Thermal hold"; }
        else {
          const imd = ctrl.max_discharge_c * capAh, pmd = Math.max(0, (ocv - imd * r) * imd);
          const eav = this.soc * capAh * ocv * 3600 / dt;
          if (Math.min(pmd, eav, 0.999 * ocv * ocv / (4 * r)) + 1e-9 >= deficit) { served = dem; pdis = deficit; }
          else { served = 0; shed = "Load shed (limit)"; }
        }
      }
      // 2) charge
      const pvLeft = pvBus - (served - pdis);
      let pchg = 0;
      const pchgMax = (ocv + ichgMax * r) * ichgMax;
      if (pdis === 0 && pvLeft > 1e-9 && ichgMax > 1e-9) pchg = Math.min(pvLeft, pchgMax);
      const pb = pchg - pdis;
      let mode;
      if (pdis > 0) mode = "Discharging";
      else if (pchg > 0) {
        if (pchg < pchgMax - 1e-6) mode = "MPPT charge";
        else if (icv <= icc) mode = "CV charge";
        else if (icc < iccNom - 1e-6) mode = "Charge (thermal derate)";
        else mode = "CC charge";
      } else if (shed) mode = shed;
      else if (pvLeft > 1e-9 && !chargeOk) mode = "Thermal hold";
      else if (pvLeft > 1e-9 && full) mode = "Full · float";
      else mode = "Idle";
      const pvUsed = eta > 0 ? Math.min(pvAvail, (served - pdis + pchg) / eta) : 0;
      const cur = Math.max(0, pvAvail - pvUsed);
      // current
      const disc = ocv * ocv + 4 * r * pb;
      const i = Math.abs(pb) > 1e-12 ? (-ocv + Math.sqrt(Math.max(0, disc))) / (2 * r) : 0;
      const v = ocv + i * r;
      const before = this.soc;
      this.soc += i * (i > 0 ? 0.995 : 1) * dt / 3600 / capAh;
      if (i > 0) this.soc = Math.min(this.soc, Math.max(this.soc_cv, before));
      this.soc = Math.min(1, Math.max(0, this.soc));
      // thermal
      const q = i * i * r;
      const tEnv = tAmb + c.site.enclosure_solar_gain_c * Math.min(1, g / 1000);
      const tEq = tEnv + q / this.h_a;
      this.t_batt = tEq + (tb - tEq) * Math.exp(-dt / (this.c_th / this.h_a));
      // ageing
      const A = c.ageing, tk = tb + 273.15, dAh = Math.abs(i) * dt / 3600;
      this.ah += dAh; const dEfc = dAh / (2 * Math.max(1e-6, capAh)); this.efc += dEfc;
      const arrCyc = Math.exp(-A.ea_cyc / R_GAS * (1 / tk - 1 / T_REF_K));
      const arrCal = Math.exp(-A.ea_cal / R_GAS * (1 / tk - 1 / T_REF_K));
      const crate = Math.abs(i) / Math.max(1e-6, capAh);
      const knee = 1 + Math.max(0, A.knee_soh - this.soh) * A.knee_gain;
      const dCyc = this.chem.cyc_fade_per_efc * dEfc * arrCyc * (1 + 0.8 * crate) * knee;
      const dCal = this.chem.cal_fade_per_year / (365.25 * 86400) * dt * arrCal * ((0.4 + 0.9 * this.soc) / 0.85);
      this.soh = Math.max(0, this.soh - dCyc - dCal);
      this.r_pack = this.r0 * (1 + A.r_growth * Math.max(0, this.soh0 - this.soh) / this.soh0);
      // accounting
      const h = dt / 3600, T = this.totals, D = this.day;
      T.pv_wh += pvUsed * h; T.curtailed_wh += cur * h; T.load_wh += served * h; T.unmet_wh += (dem - served) * h;
      T.charge_wh += Math.max(0, pb) * h; T.discharge_wh += Math.max(0, -pb) * h; T.loss_wh += (q + pvUsed * (1 - eta)) * h;
      D.pv_wh += pvUsed * h; D.curtailed_wh += cur * h; D.load_wh += served * h; D.demand_wh += dem * h; D.unmet_wh += (dem - served) * h;
      D.soc_min = Math.min(D.soc_min, this.soc); D.soc_max = Math.max(D.soc_max, this.soc);
      D.t_batt_max = Math.max(D.t_batt_max, this.t_batt); D.peak_pv_w = Math.max(D.peak_pv_w, pvUsed);
      // events (debounced 5 sim-minutes)
      if (mode !== this.loggedMode) {
        if (mode !== this.pendMode) { this.pendMode = mode; this.pendSince = this.t; }
        else if (this.t - this.pendSince >= 300) { this.ev("mode", `${this.loggedMode} → ${mode}`); this.loggedMode = mode; }
      } else this.pendMode = null;
      if (this.lastLed !== null && ledSched !== this.lastLed) this.ev("load", ledSched ? "Street light ON" : "Street light OFF");
      this.lastLed = ledSched; this.mode = mode;
      this.t += dt;
      if (this.dayIndex !== prevDay) { this._updDate(); this.closeDay(); }
      this.inst = { ghi: g, k: this.k, t_amb: tAmb, t_panel: tPanel, sin_alt: sinAlt, pv_avail: pvAvail, pv: pvUsed, cur,
                    dem, served, pb, i, v, ocv, led: ledSched && served > 0 };
    }
    closeDay() {
      const d = this.day, f = d.soh_start - this.soh;
      this.fade = this.fade === null ? f : 0.8 * this.fade + 0.2 * f;
      d.soh_end = this.soh; d.weather = this.dayWeather;
      d.served_pct = d.demand_wh > 0 ? 100 * d.load_wh / d.demand_wh : 100;
      this.days.push(d); if (this.days.length > 4000) this.days = this.days.slice(-4000);
      this.dayWeather = this.pickWeather(); this.newDay();
      this.ev("day", `New day · weather: ${this.dayWeather}`);
    }
    rulYears() {
      const eol = this.cfg.ageing.eol_soh; if (this.soh <= eol) return 0;
      let rate = this.fade;
      if (rate === null) { const ed = this.t / 86400; if (ed < 0.25) return null; rate = (this.soh_t0 - this.soh) / ed; }
      return rate > 0 ? (this.soh - eol) / rate / 365.25 : null;
    }
    advance(sec, sub = 10) { let rem = sec; while (rem > 1e-9) { const dt = Math.min(sub, rem); this.step(dt); rem -= dt; } return this.snapshot(); }
    snapshot() {
      const p = this.cfg.pack, I = this.inst, cap = p.nominal_capacity_ah * this.soh;
      const vNom = p.series_cells * ocvCell(0.5, p.chemistry);
      const usable = Math.max(0, this.soc - this.cfg.ctrl.soc_lvd) * cap * vNom;
      const nightW = this.cfg.load.led_w * 0.75 + this.cfg.load.base_w;
      const spread = this.spread * ((this.soc < 0.2 || this.soc > 0.9) ? 2 : 1);
      const vCell = I.v / p.series_cells, rul = this.rulYears();
      const vmpT = this.cfg.panel.vmp * (1 - 0.0035 * (I.t_panel - 25));
      return {
        sim_time: this.nowIso(), hour: this.hour, elapsed_s: this.t, weather: this.dayWeather, mode: this.mode,
        load_connected: this.load_on,
        sun: { ghi_wm2: I.ghi, clear_index: I.k, sin_altitude: I.sin_alt, rise_set: sunTimes(this.cfg.site.latitude, this.doy) },
        temps: { ambient_c: I.t_amb, panel_c: I.t_panel, battery_c: this.t_batt },
        power: { pv_available_w: I.pv_avail, pv_w: I.pv, curtailed_w: I.cur, load_demand_w: I.dem, load_w: I.served, battery_w: I.pb },
        panel: { v: I.pv > 0 ? vmpT : 0, i: I.pv > 0 ? I.pv / Math.max(0.1, vmpT) : 0 },
        battery: { voltage_v: I.v, ocv_v: I.ocv, current_a: I.i, soc: this.soc, soh: this.soh, capacity_ah: cap,
                   resistance_mohm: this.r_pack * 1000, efc: this.efc, usable_wh: usable,
                   autonomy_h: nightW > 0 ? usable / nightW : null, cell_v_min: vCell - spread / 2, cell_v_max: vCell + spread / 2 },
        led_on: I.led, rul_years: rul, today: Object.assign({}, this.day), totals: Object.assign({}, this.totals),
      };
    }
    canonical(id = "SOLAR-TWIN-01") {
      const s = this.snapshot(), b = s.battery;
      return { battery_id: id, timestamp: s.sim_time, voltage: r2(b.voltage_v, 3), current: r2(b.current_a, 4),
               temperature: r2(s.temps.battery_c, 2), capacity: r2(b.capacity_ah, 4), cycle: Math.floor(b.efc),
               internal_resistance: r2(b.resistance_mohm / 1000, 5), cell_v_min: r2(b.cell_v_min, 4),
               cell_v_max: r2(b.cell_v_max, 4), source: "SOLAR_TWIN" };
    }
  }

  // ---- lifetime projection (chunked so the page stays responsive) ----
  function lifetimeRunner(cfgIn, maxYears = 15, stepS = 900, seed = 11) {
    const tw = new Twin(cfgIn, seed, false);
    const eol = tw.cfg.ageing.eol_soh, total = Math.floor(maxYears * 365.25);
    const weekly = []; let day = 0, eolDay = null;
    function result() {
      const ds = tw.days, full = ds.filter(d => d.unmet_wh < 0.01 * Math.max(1e-9, d.demand_wh)).length;
      const kwh = tw.totals.load_wh / 1000;
      return { eol_soh: eol, start_soh: tw.soh0, years_simulated: ds.length / 365.25, reached_eol: eolDay !== null,
        years_to_eol: eolDay ? eolDay / 365.25 : null, final_soh: tw.soh, final_resistance_mohm: tw.r_pack * 1000,
        efc_added: tw.efc - tw.cfg.pack.cycle_count, energy_delivered_kwh: kwh, pv_harvested_kwh: tw.totals.pv_wh / 1000,
        curtailed_kwh: tw.totals.curtailed_wh / 1000, unmet_kwh: tw.totals.unmet_wh / 1000,
        nights_fully_served_pct: 100 * full / Math.max(1, ds.length), co2_avoided_kg: kwh * GRID_CO2, weekly,
        v_cv_cell: tw.v_cv_cell };
    }
    return {
      run(days) {
        for (let n = 0; n < days && day < total && eolDay === null; n++, day++) {
          tw.advance(86400, stepS);
          if (day % 7 === 0) { const s = tw.days[tw.days.length - 1] || {};
            weekly.push({ day, soh: tw.soh, resistance_mohm: tw.r_pack * 1000, efc: tw.efc, served_pct: s.served_pct ?? 100 }); }
          if (tw.soh <= eol) { eolDay = day + 1; weekly.push({ day: day + 1, soh: tw.soh, resistance_mohm: tw.r_pack * 1000, efc: tw.efc, served_pct: 100 }); }
        }
        return day >= total || eolDay !== null;
      },
      progress() { return Math.min(1, day / Math.max(1, Math.min(total, 365.25 * 8))); },
      result,
    };
  }
  function gentleCfg(cfgIn) {
    const c = merge(JSON.parse(JSON.stringify(cfgIn || {})));
    const base = c.ctrl.v_cv_cell || CHEM[c.pack.chemistry].v_cv_cell;
    const target = Math.max(0.5, socFromOcv(base, c.pack.chemistry) - 0.10);
    c.ctrl.v_cv_cell = Math.round(ocvCell(target, c.pack.chemistry) * 1000) / 1000;
    return c;
  }
  function scenarios(cfgIn) {
    const std = merge(JSON.parse(JSON.stringify(cfgIn || {})));
    const gentle = gentleCfg(cfgIn);
    const shaded = gentleCfg(cfgIn); shaded.site.enclosure_solar_gain_c = Math.min(2, std.site.enclosure_solar_gain_c);
    const sv = std.ctrl.v_cv_cell || CHEM[std.pack.chemistry].v_cv_cell;
    return [
      { key: "standard", label: `Standard charge (${sv.toFixed(2)} V/cell)`, cfg: std },
      { key: "gentle", label: `Gentle charge (${gentle.ctrl.v_cv_cell.toFixed(2)} V/cell)`, cfg: gentle },
      { key: "shaded_gentle", label: "Gentle charge + shaded battery box", cfg: shaded },
    ];
  }

  root.SolarTwin = { Twin, PRESETS, CHEM, defaults, merge, validate, lifetimeRunner, scenarios, ocvCell, socFromOcv, sunTimes, GRID_CO2 };
  if (typeof module !== "undefined") module.exports = root.SolarTwin;
})(typeof window !== "undefined" ? window : globalThis);
