"""SOH inference (Layer 1) with calibrated intervals, OOD score and TreeSHAP.

    python -m app.ml.predict path/to/test.csv --cells 3 --nominal-ah 2.5
"""
from __future__ import annotations

import json
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from app.config import MODEL_DIR
from app.ml.feature_engineering import MODEL_FEATURES, SPOT_FEATURES

MAX_MISSING_FRACTION = 0.35   # more missing than this = outside what the model was trained for


class ModelNotTrainedError(RuntimeError):
    pass


class SOHPredictor:
    def __init__(self, point, qmodel, baseline, ood, card, spot=None):
        self.point, self.qmodel, self.baseline, self.ood, self.card = point, qmodel, baseline, ood, card
        self.spot = spot   # (point, quantile) for manual spot measurements

    def _models(self, variant):
        if variant == "spot":
            if not self.spot:
                raise ModelNotTrainedError("Spot-measurement model missing — retrain with python -m app.ml.train_model")
            return self.spot[0], self.spot[1], SPOT_FEATURES, self.card["spot_variant"]["conformal_q"]
        return self.point, self.qmodel, MODEL_FEATURES, self.card["conformal_q"]

    @classmethod
    def load(cls) -> "SOHPredictor":
        need = ["soh_xgb_point.json", "soh_xgb_quantile.json", "model_card.json", "ood_detector.joblib"]
        if not all((MODEL_DIR / f).exists() for f in need):
            raise ModelNotTrainedError("No trained model found. Run: python -m app.ml.generate_dataset && python -m app.ml.train_model")
        point = xgb.XGBRegressor(); point.load_model(MODEL_DIR / "soh_xgb_point.json")
        q = xgb.XGBRegressor(); q.load_model(MODEL_DIR / "soh_xgb_quantile.json")
        base = joblib.load(MODEL_DIR / "soh_baseline_ridge.joblib")
        ood = joblib.load(MODEL_DIR / "ood_detector.joblib")
        card = json.loads((MODEL_DIR / "model_card.json").read_text())
        spot = None
        if (MODEL_DIR / "soh_spot_point.json").exists():
            sp = xgb.XGBRegressor(); sp.load_model(MODEL_DIR / "soh_spot_point.json")
            sq = xgb.XGBRegressor(); sq.load_model(MODEL_DIR / "soh_spot_quantile.json")
            spot = (sp, sq)
        return cls(point, q, base, ood, card, spot)

    def predict_frame(self, X: pd.DataFrame, variant: str = "full") -> dict:
        point, qmodel, feats, qh = self._models(variant)
        X = X[feats].astype(float)
        qp = qmodel.predict(X)
        lo, med, hi = qp[:, 0] - qh, qp[:, 1], qp[:, 2] + qh
        pt = point.predict(X)
        lo = np.minimum(lo, pt); hi = np.maximum(hi, pt)
        return {"soh": np.clip(pt, 0, 105), "lo": np.clip(lo, 0, 105), "hi": np.clip(hi, 0, 105), "median": med}

    def ood_score(self, X: pd.DataFrame, variant: str = "full") -> tuple[float, bool, float]:
        """Returns (isolation score, is_ood, missing fraction). Too many missing inputs
        also counts as out-of-distribution (imputation would otherwise hide it)."""
        feats = SPOT_FEATURES if variant == "spot" else MODEL_FEATURES
        miss = float(X[feats].astype(float).isna().mean(axis=1).iloc[0])
        if variant == "spot":
            return float("nan"), miss > 0.5, miss
        Z = self.ood["scaler"].transform(self.ood["imputer"].transform(X[MODEL_FEATURES].astype(float)))
        s = float(self.ood["iso"].score_samples(Z)[0])
        return s, (s < self.ood["threshold"]) or miss > MAX_MISSING_FRACTION, miss

    def shap(self, X: pd.DataFrame, variant: str = "full") -> tuple[dict, float]:
        """Exact TreeSHAP contributions from XGBoost (pred_contribs)."""
        point, _, feats, _ = self._models(variant)
        dm = xgb.DMatrix(X[feats].astype(float), feature_names=feats)
        contrib = point.get_booster().predict(dm, pred_contribs=True)[0]
        return {f: float(c) for f, c in zip(feats, contrib[:-1])}, float(contrib[-1])

    def baseline_predict(self, X: pd.DataFrame) -> float:
        return float(self.baseline.predict(X[MODEL_FEATURES].astype(float))[0])

    def global_importance(self) -> dict:
        imp = self.point.get_booster().get_score(importance_type="gain")
        tot = sum(imp.values()) or 1
        return {k: v / tot for k, v in sorted(imp.items(), key=lambda kv: -kv[1])}


@lru_cache(maxsize=1)
def get_predictor() -> SOHPredictor:
    return SOHPredictor.load()


def reload_predictor():
    get_predictor.cache_clear()
    return get_predictor()


if __name__ == "__main__":
    import argparse
    from app.ml.data_ingestion import validate_and_clean
    from app.ml.feature_engineering import Meta, extract_features
    ap = argparse.ArgumentParser()
    ap.add_argument("csv"); ap.add_argument("--cells", type=int, default=3); ap.add_argument("--nominal-ah", type=float, default=2.5)
    a = ap.parse_args()
    df, rep = validate_and_clean(pd.read_csv(a.csv), a.cells)
    f = extract_features(df, Meta(a.cells, a.nominal_ah))["features"]
    p = get_predictor()
    out = p.predict_frame(pd.DataFrame([f]))
    print(f"SOH {out['soh'][0]:.1f}%  (90% PI {out['lo'][0]:.1f}–{out['hi'][0]:.1f})  [{p.card['status']}]")
