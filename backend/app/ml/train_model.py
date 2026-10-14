"""Phases 4 + 5 — Baseline and XGBoost SOH models.

    python -m app.ml.train_model                       # uses data/demo_dataset/features.csv
    python -m app.ml.train_model --features my.csv --dataset-name "NASA PCoE + lab"

Design decisions
* Battery-level split (GroupShuffleSplit) -> no test of a battery seen in training.
* Baseline: Ridge regression on imputed/standardised features (Phase 4).
* Main: XGBoost point model (used for SHAP) + XGBoost multi-quantile model
  (5 / 50 / 95 %) for heteroscedastic uncertainty (Phase 5).
* Split-conformal calibration (CQR) on the validation batteries so the 90 %
  interval has measured coverage on held-out test batteries.
* IsolationForest out-of-distribution detector on the training feature space.
Metrics written to the model card are computed here — never typed in by hand.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.config import DATA_DIR, MODEL_DIR
from app.ml.evaluate_model import regression_metrics, interval_metrics
from app.ml.feature_engineering import MODEL_FEATURES, SPOT_FEATURES

QUANTILES = [0.05, 0.5, 0.95]
ALPHA = 0.10  # target miscoverage for the conformal interval (90 % PI)


def battery_split(df: pd.DataFrame, seed: int = 42):
    g = df["battery_id"].to_numpy()
    s1 = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=seed)
    tr, rest = next(s1.split(df, groups=g))
    rest_df = df.iloc[rest]
    s2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=seed)
    va, te = next(s2.split(rest_df, groups=rest_df["battery_id"]))
    return df.iloc[tr], rest_df.iloc[va], rest_df.iloc[te]


def train(features_csv: str, dataset_name: str, source: str) -> dict:
    df = pd.read_csv(features_csv)
    df = df.dropna(subset=["soh_true"])
    train_df, val_df, test_df = battery_split(df)
    for a, b in [(train_df, val_df), (train_df, test_df), (val_df, test_df)]:
        assert not set(a.battery_id) & set(b.battery_id), "battery leakage between splits"

    Xtr, ytr = train_df[MODEL_FEATURES].astype(float), train_df["soh_true"].to_numpy()
    Xva, yva = val_df[MODEL_FEATURES].astype(float), val_df["soh_true"].to_numpy()
    Xte, yte = test_df[MODEL_FEATURES].astype(float), test_df["soh_true"].to_numpy()

    # ---------- Phase 4: baseline -------------------------------------------
    baseline = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))
    baseline.fit(Xtr, ytr)
    base_metrics = regression_metrics(yte, baseline.predict(Xte))

    # ---------- Phase 5: XGBoost point model ----------------------------------
    params = dict(n_estimators=1200, learning_rate=0.03, max_depth=5, subsample=0.85,
                  colsample_bytree=0.85, min_child_weight=3, reg_lambda=1.0,
                  early_stopping_rounds=60, eval_metric="mae")
    point = xgb.XGBRegressor(objective="reg:squarederror", **params)
    point.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    xgb_metrics = regression_metrics(yte, point.predict(Xte))

    # ---------- quantile model ----------------------------------------------
    qmodel = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=np.array(QUANTILES),
                              **{**params, "eval_metric": None})
    qmodel.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    qva = qmodel.predict(Xva)
    # conformalised quantile regression (Romano et al. 2019)
    scores = np.maximum(qva[:, 0] - yva, yva - qva[:, 2])
    n = len(scores)
    q_hat = float(np.quantile(scores, min(1.0, np.ceil((n + 1) * (1 - ALPHA)) / n)))
    qte = qmodel.predict(Xte)
    lo, hi = qte[:, 0] - q_hat, qte[:, 2] + q_hat
    int_metrics = interval_metrics(yte, lo, hi)

    # ---------- OOD detector ---------------------------------------------------
    imputer = SimpleImputer(strategy="median").fit(Xtr)
    scaler = StandardScaler().fit(imputer.transform(Xtr))
    iso = IsolationForest(n_estimators=300, contamination="auto", random_state=0)
    Ztr = scaler.transform(imputer.transform(Xtr))
    iso.fit(Ztr)
    ood_threshold = float(np.quantile(iso.score_samples(Ztr), 0.02))

    # ---------- spot-measurement variant (MANUAL input mode) -------------------------
    # Manual entry provides a handful of scalar measurements, not a time series, so it
    # gets its own model trained on just those features (with random masking so it
    # learns to widen its interval when some are omitted).
    rng = np.random.default_rng(0)
    def masked(X, reps=3, p=0.3):
        Xs = pd.concat([X] * reps, ignore_index=True)
        mask = rng.random(Xs.shape) < p
        mask[:, SPOT_FEATURES.index("capacity_est_norm")] &= rng.random(len(Xs)) < 0.5
        return Xs.mask(mask)
    Str, Sva, Ste = Xtr[SPOT_FEATURES], Xva[SPOT_FEATURES], Xte[SPOT_FEATURES]
    Str_m = masked(Str); ytr_m = np.tile(ytr, 3)
    s_point = xgb.XGBRegressor(objective="reg:squarederror", **params)
    s_point.fit(Str_m, ytr_m, eval_set=[(Sva, yva)], verbose=False)
    s_q = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=np.array(QUANTILES), **{**params, "eval_metric": None})
    s_q.fit(Str_m, ytr_m, eval_set=[(Sva, yva)], verbose=False)
    Sva_m = masked(Sva, reps=1, p=0.2)
    sq = s_q.predict(Sva_m)
    sc = np.maximum(sq[:, 0] - yva, yva - sq[:, 2])
    s_qhat = float(np.quantile(sc, min(1.0, np.ceil((len(sc) + 1) * (1 - ALPHA)) / len(sc))))
    ste_q = s_q.predict(Ste)
    s_point.save_model(MODEL_DIR / "soh_spot_point.json")
    s_q.save_model(MODEL_DIR / "soh_spot_quantile.json")
    spot_card = {"features": SPOT_FEATURES, "conformal_q": s_qhat,
                 "metrics_test": {"xgboost": regression_metrics(yte, s_point.predict(Ste)),
                                  "interval_90": interval_metrics(yte, ste_q[:, 0] - s_qhat, ste_q[:, 2] + s_qhat)}}

    # ---------- per-archetype error (diagnostic) --------------------------------
    per_group = {}
    if "archetype" in test_df:
        pred = point.predict(Xte)
        for g, idx in test_df.reset_index(drop=True).groupby("archetype").groups.items():
            per_group[g] = regression_metrics(yte[idx], pred[idx])

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    point.save_model(MODEL_DIR / "soh_xgb_point.json")
    qmodel.save_model(MODEL_DIR / "soh_xgb_quantile.json")
    joblib.dump(baseline, MODEL_DIR / "soh_baseline_ridge.joblib")
    joblib.dump({"imputer": imputer, "scaler": scaler, "iso": iso, "threshold": ood_threshold},
                MODEL_DIR / "ood_detector.joblib")
    # population ageing curves for the RUL prior (from training labels only)
    pop = train_df[["battery_id", "cycle_true", "soh_true"]].dropna() if "cycle_true" in train_df else None
    if pop is not None:
        pop.to_csv(MODEL_DIR / "population_curves.csv", index=False)

    # reference distribution (training batteries only) used by the fingerprint to
    # express measurements as percentiles of the reference population
    ref = {}
    for col in ["thermal_response", "t_rise_rate", "ir_cell_mohm", "cell_imbalance_mv", "dv_dq", "v_recovery_cell_mv"]:
        vals = train_df[col].dropna().to_numpy(float)
        if len(vals):
            ref[col] = np.quantile(vals, np.linspace(0, 1, 101)).round(5).tolist()
    with open(MODEL_DIR / "feature_reference.json", "w") as f:
        json.dump(ref, f)

    is_sim = source.upper() == "SIMULATED"
    card = {
        "model_name": "XGBoost SOH Estimator",
        "version": "v0.1",
        "status": "DEMO MODEL — trained on simulated data" if is_sim else "Prototype — trained on supplied data",
        "training_status": "Prototype",
        "data_source": source,
        "dataset": dataset_name,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "library_versions": {"xgboost": xgb.__version__, "scikit-learn": __import__("sklearn").__version__},
        "features": MODEL_FEATURES,
        "split": {"method": "battery-level GroupShuffleSplit 70/15/15",
                  "n_batteries": {"train": int(train_df.battery_id.nunique()),
                                  "val": int(val_df.battery_id.nunique()),
                                  "test": int(test_df.battery_id.nunique())},
                  "n_samples": {"train": len(train_df), "val": len(val_df), "test": len(test_df)},
                  "test_battery_ids": sorted(test_df.battery_id.unique().tolist())},
        "metrics_test": {"xgboost": xgb_metrics, "baseline_ridge": base_metrics,
                         "interval_90": int_metrics, "per_archetype": per_group},
        "best_iteration": int(point.best_iteration),
        "conformal_q": q_hat,
        "quantiles": QUANTILES,
        "ood_threshold": ood_threshold,
        "spot_variant": spot_card,
        "caveat": ("Metrics are measured on held-out SIMULATED batteries. They show the pipeline works; "
                   "they are NOT evidence of accuracy on real retired EV batteries." if is_sim else
                   "Metrics measured on held-out batteries of the supplied dataset."),
    }
    with open(MODEL_DIR / "model_card.json", "w") as f:
        json.dump(card, f, indent=2)
    return card


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=str(DATA_DIR / "demo_dataset" / "features.csv"))
    ap.add_argument("--dataset-name", default="RE-BAT simulated population (84 modules)")
    ap.add_argument("--source", default="SIMULATED")
    a = ap.parse_args()
    card = train(a.features, a.dataset_name, a.source)
    m = card["metrics_test"]
    print(f"[{card['status']}]")
    print("Baseline Ridge :", m["baseline_ridge"])
    print("XGBoost        :", m["xgboost"])
    print("90% interval   :", m["interval_90"])
    print("Spot (manual)  :", card["spot_variant"]["metrics_test"])
