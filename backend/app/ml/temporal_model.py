"""Layer 2 — Temporal battery model (1D CNN) + late fusion with XGBoost.

Status: ARCHITECTURE READY, NOT TRAINED in the shipped prototype (PyTorch is an
optional dependency). The tabular XGBoost model is the active SOH model; when a
trained CNN checkpoint exists at artifacts/temporal_cnn.pt the API reports it and
`fuse()` combines both by inverse-variance weighting.

Input tensor: 3 channels × 256 samples resampled over the main discharge
  ch0 = cell voltage, ch1 = current / Qnom (C-rate), ch2 = temperature − start temp
Output: SOH mean and log-variance (heteroscedastic Gaussian head).

Train:  python -m app.ml.temporal_model --train   (needs `pip install torch`)
"""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd

from app.config import MODEL_DIR

SEQ_LEN = 256
CKPT = MODEL_DIR / "temporal_cnn.pt"

try:
    import torch
    import torch.nn as nn
    TORCH = True
except Exception:   # pragma: no cover
    TORCH = False


def to_tensor(df: pd.DataFrame, series_cells: int, nominal_ah: float) -> np.ndarray:
    """Resample the loaded portion of a canonical test to (3, SEQ_LEN)."""
    loaded = df[df["current"] > 0.05]
    if len(loaded) < 8:
        raise ValueError("not enough discharge samples for the temporal model")
    t = loaded["timestamp"].to_numpy(float)
    grid = np.linspace(t[0], t[-1], SEQ_LEN)
    v = np.interp(grid, t, loaded["voltage"].to_numpy(float) / series_cells)
    c = np.interp(grid, t, loaded["current"].to_numpy(float) / nominal_ah)
    T = loaded["temperature"].to_numpy(float)
    dT = np.interp(grid, t, np.nan_to_num(T - (T[np.isfinite(T)][0] if np.isfinite(T).any() else 0.0)))
    return np.stack([(v - 3.6) / 0.4, c, dT / 10.0]).astype(np.float32)


if TORCH:
    class TemporalCNN(nn.Module):
        def __init__(self, ch: int = 3, width: int = 32):
            super().__init__()
            def block(i, o, k, d):
                return nn.Sequential(nn.Conv1d(i, o, k, padding=d * (k // 2), dilation=d), nn.BatchNorm1d(o), nn.GELU())
            self.net = nn.Sequential(block(ch, width, 7, 1), block(width, width, 5, 2), nn.MaxPool1d(2),
                                     block(width, 2 * width, 5, 2), block(2 * width, 2 * width, 3, 4), nn.MaxPool1d(2),
                                     block(2 * width, 2 * width, 3, 8), nn.AdaptiveAvgPool1d(1), nn.Flatten())
            self.head = nn.Sequential(nn.Linear(2 * width, 64), nn.GELU(), nn.Dropout(0.1), nn.Linear(64, 2))

        def forward(self, x):
            out = self.head(self.net(x))
            return out[:, 0] * 10 + 80, out[:, 1]      # mean SOH %, log-variance


def status() -> dict:
    return {"name": "Temporal 1D-CNN", "version": "v0.1-arch", "torch_available": TORCH,
            "trained": CKPT.exists(), "input": f"3×{SEQ_LEN} (V/cell, C-rate, ΔT)",
            "fusion": "inverse-variance late fusion with XGBoost when trained",
            "status": "Trained" if CKPT.exists() else "Architecture ready — not trained (no PyTorch in this build)"}


def fuse(xgb_mean: float, xgb_sigma: float, cnn_mean: float, cnn_sigma: float) -> tuple[float, float]:
    w1, w2 = 1 / xgb_sigma ** 2, 1 / cnn_sigma ** 2
    return (w1 * xgb_mean + w2 * cnn_mean) / (w1 + w2), math.sqrt(1 / (w1 + w2))


def train(epochs: int = 40):
    if not TORCH:
        raise SystemExit("PyTorch not installed: pip install torch")
    from app.simulation.battery_sim import BatterySimulator, random_battery, random_test_config
    from app.ml.data_ingestion import validate_and_clean
    rng = np.random.default_rng(3)
    X, y, g = [], [], []
    for b in range(60):
        p = random_battery(b, rng)
        sim = BatterySimulator(p)
        for c in rng.integers(0, 3000, 20):
            df, _ = validate_and_clean(sim.run_test(random_test_config(rng, p.nominal_capacity_ah), int(c)))
            X.append(to_tensor(df, p.series_cells, p.nominal_capacity_ah)); y.append(100 * p.soh(int(c))); g.append(b)
    X, y, g = torch.tensor(np.array(X)), torch.tensor(np.array(y), dtype=torch.float32), np.array(g)
    tr = torch.tensor(g < 48)
    model = TemporalCNN()
    opt = torch.optim.AdamW(model.parameters(), 2e-3, weight_decay=1e-4)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(int(tr.sum()))
        Xt, yt = X[tr][perm], y[tr][perm]
        for i in range(0, len(Xt), 64):
            mu, lv = model(Xt[i:i + 64])
            loss = (0.5 * torch.exp(-lv) * (mu - yt[i:i + 64]) ** 2 + 0.5 * lv).mean()
            opt.zero_grad(); loss.backward(); opt.step()
        model.eval()
        with torch.no_grad():
            mu, _ = model(X[~tr])
            print(f"epoch {ep:02d}  held-out-battery MAE {float((mu - y[~tr]).abs().mean()):.2f}")
    torch.save(model.state_dict(), CKPT)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--train", action="store_true"); ap.add_argument("--epochs", type=int, default=40)
    a = ap.parse_args()
    print(status()) if not a.train else train(a.epochs)
