"""Model evaluation utilities + CLI.

    python -m app.ml.evaluate_model --features data/demo_dataset/features.csv

Re-evaluates the saved artifacts on the held-out test batteries recorded in the
model card (battery-level split), so the numbers are reproducible.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd


def regression_metrics(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    err = y_pred - y_true
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2)) or 1e-9
    return {"MAE": round(float(np.mean(np.abs(err))), 3),
            "RMSE": round(float(np.sqrt(np.mean(err ** 2))), 3),
            "R2": round(1 - ss_res / ss_tot, 4),
            "n": int(len(y_true))}


def interval_metrics(y_true, lo, hi) -> dict:
    y_true = np.asarray(y_true, float)
    cover = (y_true >= lo) & (y_true <= hi)
    return {"coverage": round(float(cover.mean()), 3), "mean_width": round(float(np.mean(hi - lo)), 3),
            "target_coverage": 0.90}


def ranking_metrics(true_best: list[str], ranked: list[list[str]]) -> dict:
    """Top-1 / Top-3 accuracy for the application router once labelled outcomes exist."""
    top1 = np.mean([r[0] == t for t, r in zip(true_best, ranked)]) if ranked else float("nan")
    top3 = np.mean([t in r[:3] for t, r in zip(true_best, ranked)]) if ranked else float("nan")
    return {"top1": float(top1), "top3": float(top3), "n": len(ranked)}


def main(features_csv: str):
    from app.ml.predict import SOHPredictor
    from app.ml.feature_engineering import MODEL_FEATURES
    pred = SOHPredictor.load()
    card = pred.card
    df = pd.read_csv(features_csv)
    test = df[df.battery_id.isin(card["split"]["test_battery_ids"])]
    out = pred.predict_frame(test[MODEL_FEATURES])
    res = {"xgboost": regression_metrics(test.soh_true, out["soh"]),
           "interval_90": interval_metrics(test.soh_true, out["lo"], out["hi"])}
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    from app.config import DATA_DIR
    ap.add_argument("--features", default=str(DATA_DIR / "demo_dataset" / "features.csv"))
    main(ap.parse_args().features)
