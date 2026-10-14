# RE-BAT AI — Machine Learning Model Card & Technical Architecture

## 1. Executive Summary

**RE-BAT AI** is an intelligent, uncertainty-aware machine learning decision engine engineered for retired electric vehicle (EV) lithium-ion batteries. When EV traction batteries reach their automotive end-of-life (typically 70–80% State of Health [SOH]), significant residual energy and power storage capacity remains. 

RE-BAT AI determines whether a decommissioned pack or module should be:
* **REUSED (Second Life)**: Categorized and matched to specific stationary applications (e.g., Solar Microgrids, Industrial Backup, Commercial Telecom, Rural Streetlighting).
* **RECYCLED (Closed Loop)**: Deconstructed into constituent high-value precursor elements (Lithium, Nickel, Cobalt, Manganese, Graphite, Copper, Aluminum) with mass recovery metrics.
* **RETESTED**: Scheduled for targeted diagnostic probing when uncertainty or Out-of-Distribution (OOD) risk exceeds acceptable bounds.
* **SAFETY HOLD**: Quarantined upon detection of acute degradation signals (abnormal gas venting, internal short risk, severe cell imbalance, runaway thermal rise).

---

## 2. End-to-End Pipeline Architecture

```mermaid
flowchart TD
    subgraph Data_Sources ["Telemetry & Data Ingestion"]
        ESP32["ESP32 IoT Rig (WebSocket/REST)"]
        CSV["Lab CSV Upload"]
        SIM["Equivalent Circuit Simulator"]
    end

    subgraph Preprocessing ["Data Cleaning & Feature Engineering"]
        Clean["Unit Harmonization & Coulomb Counting"]
        FeatFull["22 Normalized Time-Series Features"]
        FeatSpot["6 Fast Spot Screening Features"]
    end

    subgraph Core_ML ["Inference & Uncertainty Engine"]
        XGBPoint["XGBoost Point SOH (reg:squarederror)"]
        XGBQuant["XGBoost Multi-Quantile (5%, 50%, 95%)"]
        ConfCalib["Split-Conformal Calibration (90% Coverage)"]
        OOD["IsolationForest OOD & Missingness Detector"]
        RUL["Power-Law Degradation & Monte-Carlo RUL"]
        TreeSHAP["TreeSHAP Explainability (pred_contribs)"]
    end

    subgraph Decision_Engine ["Suitability & Routing"]
        Fingerprint["11-Dimension Battery Fingerprint"]
        Router["Multi-Criteria Weighted Geometric Router"]
        Forensics["Cryptographic Ledger & Forensics (SHA-256)"]
    end

    Data_Sources --> Clean
    Clean --> FeatFull
    Clean --> FeatSpot
    FeatFull --> XGBPoint
    FeatFull --> XGBQuant
    FeatFull --> OOD
    FeatFull --> TreeSHAP
    XGBQuant --> ConfCalib
    XGBPoint --> RUL
    ConfCalib --> Fingerprint
    RUL --> Fingerprint
    TreeSHAP --> Fingerprint
    OOD --> Fingerprint
    Fingerprint --> Router
    Router --> Forensics
```

---

## 3. Feature Engineering Specification

To ensure universal compatibility across diverse cell geometries (18650, 21700, pouch, prismatic) and pack topologies (single cell, 3S rig, up to 96S automotive modules), all features are **strictly normalized per cell** and **scaled by nominal Ampere-hour (Ah) capacity**. Missing sensor taps are represented as `NaN` rather than imputed with zero, allowing native gradient boosting branch routing and downstream confidence penalties.

### 3.1 Primary Time-Series Features (22 Inputs)

| # | Feature Name | Unit | Engineering Description | Physical Significance |
|---|---|---|---|---|
| 1 | `v_cell_mean` | V | Mean per-cell terminal voltage across discharge window | Operating voltage plateau |
| 2 | `v_cell_min` | V | Minimum cell voltage recorded | Deep discharge / sag boundary |
| 3 | `v_cell_max` | V | Maximum initial cell voltage | Starting potential |
| 4 | `v_cell_std` | V | Standard deviation of terminal voltage over time | Discharge slope characteristics |
| 5 | `c_rate` | $h^{-1}$ | Average discharge current divided by nominal Ah | Rate of discharge stress |
| 6 | `t_mean` | °C | Mean temperature across all cell thermal probes | Thermal operating condition |
| 7 | `t_rise` | °C | Net temperature change ($\Delta T = T_{end} - T_{start}$) | Joule heating & entropic heat |
| 8 | `t_rise_rate` | °C/s | Maximum differential temperature increase rate ($dT/dt$) | Thermal dissipation kinetics |
| 9 | `thermal_response` | °C/(C²·h) | Temperature rise normalized by squared C-rate and test duration | Internal heat generation coefficient |
| 10 | `dv_dq` | V/Ah | Derivative of voltage with respect to discharged charge (middle 60% window) | Differential Voltage Analysis (DVA) phase transition |
| 11 | `dv_dt` | V/s | Time-rate of voltage decline during steady discharge | Electrochemical polarization |
| 12 | `discharge_duration_s` | s | Total elapsed discharge time | Operational window length |
| 13 | `ah_norm` | Ah/Ah_nom | Discharged Ah normalized by factory rated capacity | Delivered capacity fraction |
| 14 | `energy_norm` | Wh/Wh_nom | Discharged energy normalized by nominal energy rating | Delivered energy efficiency |
| 15 | `ir_cell_mohm` | $m\Omega$ | Direct-Current Internal Resistance per cell (via current pulse step $\Delta V / \Delta I$) | Ohmic and solid-electrolyte interphase (SEI) impedance |
| 16 | `v_recovery_cell_mv` | mV | Voltage rebound magnitude after current interruption (120 s rest) | Charge transfer & diffusion relaxation |
| 17 | `soc_start_est` | % | Initial State of Charge estimated via relaxed Open Circuit Voltage (OCV) curve | Initial battery state |
| 18 | `soc_end_est` | % | Final State of Charge estimated via final relaxed OCV | End battery state |
| 19 | `soc_window` | % | Total SOC span traversed ($\Delta SOC = SOC_{start} - SOC_{end}$) | Depth of Discharge (DOD) coverage |
| 20 | `capacity_est_norm` | - | Normalized capacity inferred from $Ah_{discharged} / \Delta SOC$ | Coulombic/OCV capacity estimate |
| 21 | `cycle` | count | Total equivalent automotive cycles logged | Cumulative degradation history |
| 22 | `cell_imbalance_mv` | mV | Peak delta between maximum and minimum cell voltages during discharge | Pack series cell mismatch / degradation variance |

### 3.2 Fast Spot Screening Features (6 Inputs)
For scenarios where continuous telemetry is unavailable and only single-point or manual test measurements are supplied:
1. `c_rate`: Applied discharge rate.
2. `t_mean`: Average cell temperature.
3. `t_rise`: Net temperature rise during test.
4. `ir_cell_mohm`: Single-pulse internal resistance measurement.
5. `capacity_est_norm`: Approximate normalized capacity.
6. `cycle`: Operational cycle count.

---

## 4. Model Architectures & Training Methodology

### 4.1 XGBoost SOH Point & Quantile Regressors
* **Framework**: XGBoost 3.4+ / Scikit-Learn 1.9+
* **Point Estimator Objective**: `reg:squarederror`
* **Quantile Estimator Objective**: Multi-quantile regression with pinball loss (`reg:quantileerror` at quantiles $\tau \in \{0.05, 0.50, 0.95\}$).
* **Early Stopping**: Monitored on validation loss with a patience of 100 rounds.

### 4.2 Split-Conformal Calibration
Standard quantile regressors frequently suffer from empirical undercoverage when evaluated out-of-sample. RE-BAT AI implements inductive split-conformal prediction:
1. Computes non-conformity scores on the held-out validation set $\mathcal{D}_{val}$:
   $$s_i = \max(y_i - \hat{q}_{0.95}(x_i), \hat{q}_{0.05}(x_i) - y_i)$$
2. Finds the empirical $(1-\alpha)$-quantile correction $\hat{q}$ ($\approx 0.596$ SOH points).
3. Produces rigorously calibrated 90% prediction intervals on unseen packs:
   $$\mathcal{C}_{0.90}(x) = [\hat{q}_{0.05}(x) - \hat{q}, \;\; \hat{q}_{0.95}(x) + \hat{q}]$$

### 4.3 Out-of-Distribution (OOD) Detector
* **Algorithm**: `IsolationForest` (contamination=0.03, $n_{estimators}=200$) trained on standard operating distributions in the feature space.
* **Missingness Gating**: In addition to isolation tree score thresholds (cutoff: $-0.588$), packs missing critical parameters (e.g., missing temperature rise and missing internal resistance) trigger an OOD penalty that lowers confidence and routes the battery to targeted diagnostic testing (`RETEST`).

### 4.4 Remaining Useful Life (RUL) Modeling
* **Degradation Kinematics**: Power-law empirical fade model $SOH(k) = SOH_0 - a \cdot k^b$.
* **Monte-Carlo Trajectory Sampling**: When historical trend data is sparse, population priors are fitted with 300–400 Monte Carlo trajectories varying knee-point onset parameters to yield 10th, 50th, and 90th percentile RUL cycles remaining before crossing the 60% SOH end-of-life retirement threshold.

### 4.5 TreeSHAP Explainability
* Predictions are decomposed using TreeSHAP via XGBoost's native `pred_contribs=True`.
* Local feature attributions explain the exact contribution (positive or negative SOH points) of each sensor feature relative to the population base value, surfaced directly on the dashboard's **Why / XAI** screen.

---

## 5. Empirical Performance & Benchmarks

All metrics below are evaluated on strictly held-out test batteries (**GroupShuffleSplit** 70/15/15 across 84 battery modules, ensuring that no cycle or telemetry from a test battery appears in the training or validation splits).

### 5.1 Model Comparison on Held-Out Test Set (390 Records across 13 Packs)

| Model Name | Input Features | MAE (SOH pts) | RMSE (SOH pts) | $R^2$ Score | 90% Interval Coverage | Mean Interval Width |
|---|---|---|---|---|---|---|
| **XGBoost Full (Time-Series)** | 22 features | **1.132** | **1.616** | **0.9835** | **86.2%** | **5.87 pts** |
| **Baseline Ridge Regression** | 22 features | 2.623 | 3.511 | 0.9221 | N/A | N/A |
| **XGBoost Spot (Fast Screen)** | 6 features | 3.334 | 4.832 | 0.8524 | 86.2% | 16.20 pts |

### 5.2 Performance Across Battery Degradation Archetypes

| Degradation Archetype | Key Failure Mode Characteristics | Test Samples ($n$) | MAE (SOH pts) | RMSE | $R^2$ |
|---|---|---|---|---|---|
| **Normal Linear Fade** | Uniform capacity degradation, nominal impedance | 180 | **0.847** | **1.116** | **0.9874** |
| **Thermal Accelerated** | High $T_{rise}$, elevated internal entropy, heat dissipation lag | 90 | **1.162** | **1.757** | **0.9596** |
| **Early Knee Failure** | Abrupt capacity drop, rapid phase transition, SEI growth | 30 | **1.198** | **1.736** | **0.9933** |
| **High Internal Resistance** | Severely elevated $IR_{cell}$, high voltage recovery sag | 60 | **1.647** | **2.163** | **0.5993** |
| **Fast Fade** | Accelerated chemical consumption, rapid Ah loss | 30 | **1.656** | **2.201** | **0.9731** |

---

## 6. Second-Life Suitability Engine

Rather than relying on black-box classification for second-life applications, RE-BAT AI computes an objective, physics-informed **Weighted Geometric Mean** over normalized criteria fits:

$$\text{Fit}_i(x_i) = \max\left(0.02, \; \text{smoothstep}\left(\frac{x_i - \text{poor}_i}{\text{good}_i - \text{poor}_i}\right)\right)$$

$$\text{Score}_a = 100 \times \exp\left( \frac{\sum_i w_i \ln \text{Fit}_i}{\sum_i w_i} \right) \times V_{\text{tier}}$$

Where:
* $V_{\text{tier}}$ scales according to economic value and duty-cycle demands (Tier 1: 0.80, Tier 2: 0.93, Tier 3: 1.00).
* **Hard Safety Gates**: If thermal risk is categorized as `HIGH` (or `MEDIUM` for enclosed residential/telecom duty), the application score is capped at $\le 15$ ("Excluded").
* **Decision Rules**:
  - `REUSE`: Granted if top reuse application score exceeds recycling value threshold.
  - `RECYCLE`: Triggered when SOH is below terminal limit (<65–70%), internal resistance is critically elevated, or mineral recovery economics dominate.
  - `RETEST`: Triggered when uncertainty width is high ($\Delta SOH > 10\%$) or OOD score flags anomalous operating state.
  - `SAFETY HOLD`: Activated when volatile gas detection ($\Delta V_{gas} > +0.8\text{V}$), extreme thermal slope ($dT/dt$), or major cell imbalance ($\Delta V > 100\text{ mV}$) is detected.

---

## 7. CLI Usage & Reproducibility Guide

All ML modules can be audited, executed, or retrained from the `backend/` directory:

### 7.1 Verify & Bootstrap Model
Verifies artifacts, checks library compatibility (XGBoost/scikit-learn versions), and automatically retrains if artifacts are missing:
```bash
python -m app.ml.bootstrap
```

### 7.2 Synthesize Training Population
Generates electrochemically simulated multi-cycle battery populations across 84 packs (Normal, Early Knee, Fast Fade, High IR, Thermal):
```bash
python -m app.ml.generate_dataset
```

### 7.3 Retrain Full Model Suite
Trains baseline ridge regression, full XGBoost point & quantile estimators, spot models, isolation forest OOD, and generates conformal calibration constants:
```bash
python -m app.ml.train_model
```

### 7.4 Execute Comprehensive Test Suite
Executes unit and integration tests across data ingestion, feature extraction, predictions, conformal intervals, and suitability routing:
```bash
python -m pytest -q
```

---

## 8. Artifact Catalog (`backend/artifacts/`)

| Artifact File | Size | Format | Description |
|---|---|---|---|
| `model_card.json` | 3 KB | JSON | Full model metadata, training timestamp, parameters, and benchmark scores |
| `feature_reference.json` | 6 KB | JSON | Feature names, bounds, medians, and distribution percentiles |
| `soh_xgb_point.json` | 3.6 MB | JSON | Serialized XGBoost point estimator model weights |
| `soh_xgb_quantile.json` | 8.8 MB | JSON | Serialized multi-quantile XGBoost model ($\tau = [0.05, 0.50, 0.95]$) |
| `soh_spot_point.json` | 450 KB | JSON | Fast screening point model weights |
| `soh_spot_quantile.json` | 5.0 MB | JSON | Fast screening quantile model weights |
| `ood_detector.joblib` | 3.4 MB | Joblib | Fitted Isolation Forest model for out-of-distribution detection |
| `soh_baseline_ridge.joblib` | 2.7 KB | Joblib | Fitted baseline Ridge regression model |
| `population_curves.csv` | 52 KB | CSV | Reference degradation trajectories across simulated archetypes |

---

## 9. Assumptions, Limitations & Real-World Calibration

1. **Simulated Training Data**: The default shipped model is trained on electrochemically calibrated synthetic degradation data (equivalent circuit + lumped thermal + kinetic aging model). While physics-grounded, production deployment requires fine-tuning on real laboratory cycling data (e.g., NASA PCoE, CALCE, Oxford, or custom test bench data).
2. **Hardware Constraints**: The laboratory ESP32 rig utilizes an ACS712 current transducer and voltage dividers. Where pulse-load switching relays or individual cell voltage tap wires are absent, internal resistance and cell imbalance are reported as "not measured", prompting the AI to request a pulse-test sequence.
3. **Safety Verification**: Model outputs are decision-support aids. Repurposed packs must undergo mandatory physical, thermal, and dielectric isolation tests before live deployment in commercial or residential energy storage systems.
