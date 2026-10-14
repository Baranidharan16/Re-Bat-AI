"""Make sure a usable model exists on this machine.

    python -m app.ml.bootstrap

Loads the shipped artifacts; if they are missing or were saved with a different
xgboost / scikit-learn version than the one installed, regenerates the simulated
dataset (if needed) and retrains (~1–2 min). Real-data models are never overwritten
automatically — retrain those explicitly.
"""
from __future__ import annotations

import json
import sys

import sklearn
import xgboost

from app.config import DATA_DIR, MODEL_DIR


def needs_training() -> str | None:
    card_p = MODEL_DIR / "model_card.json"
    if not card_p.exists():
        return "no trained model found"
    card = json.loads(card_p.read_text())
    v = card.get("library_versions", {})
    if v.get("xgboost") != xgboost.__version__ or v.get("scikit-learn") != sklearn.__version__:
        if card.get("data_source") != "SIMULATED":
            print("WARNING: model was trained with different library versions; retrain it on your data.")
            return None
        return f"library versions differ (model {v}, installed xgboost {xgboost.__version__}, sklearn {sklearn.__version__})"
    try:
        from app.ml.predict import SOHPredictor
        SOHPredictor.load()
    except Exception as e:   # noqa: BLE001
        return f"model failed to load: {e}"
    return None


def main():
    why = needs_training()
    if not why:
        print("Model OK.")
        return
    print(f"Training demo model: {why}")
    from app.ml import generate_dataset, train_model
    feats = DATA_DIR / "demo_dataset" / "features.csv"
    if not feats.exists():
        generate_dataset.build()
    card = train_model.train(str(feats), "RE-BAT simulated population (84 modules)", "SIMULATED")
    print("Done:", card["status"], card["metrics_test"]["xgboost"])


if __name__ == "__main__":
    sys.exit(main())
