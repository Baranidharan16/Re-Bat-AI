"""Generate the DEMO / SIMULATED training dataset.

    python -m app.ml.generate_dataset --batteries 84 --tests 30

Output: data/demo_dataset/features.csv  (one row per test, label = soh_true)
        data/demo_dataset/raw/<battery>_<cycle>.csv  (a few raw examples)
Every row carries source=SIMULATED. Replace with real data via
app.ml.data_ingestion loaders + app.ml.train_model --features <your csv>.
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from app.config import DATA_DIR
from app.ml.feature_engineering import Meta, extract_features
from app.simulation.battery_sim import BatterySimulator, random_battery, random_test_config


def build(n_batteries: int = 84, tests_per_battery: int = 30, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out_dir = DATA_DIR / "demo_dataset"
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for b in range(n_batteries):
        p = random_battery(b, rng)
        sim = BatterySimulator(p)
        max_cycle = int(rng.uniform(1500, 3200))
        cycles = np.sort(rng.integers(0, max_cycle, tests_per_battery))
        for c in cycles:
            cfg = random_test_config(rng, p.nominal_capacity_ah)
            df = sim.run_test(cfg, cycle=int(c))
            if not rng.random() < 0.85:   # some logs lack cycle count (unknown history)
                df["cycle"] = np.nan
            res = extract_features(df, Meta(p.series_cells, p.nominal_capacity_ah))
            row = dict(res["features"])
            row.update(battery_id=p.battery_id, archetype=p.archetype, soh_true=100 * p.soh(int(c)),
                       cycle_true=int(c), nominal_capacity_ah=p.nominal_capacity_ah,
                       r_cell_true_mohm=1000 * p.r_cell(int(c)), source="SIMULATED")
            rows.append(row)
            if b < 3 and len(rows) % 10 == 0:
                df.to_csv(raw_dir / f"{p.battery_id}_c{int(c)}.csv", index=False)
    data = pd.DataFrame(rows)
    data.to_csv(out_dir / "features.csv", index=False)
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batteries", type=int, default=84)
    ap.add_argument("--tests", type=int, default=30)
    a = ap.parse_args()
    t0 = time.time()
    d = build(a.batteries, a.tests)
    print(f"[SIMULATED] {len(d)} test records from {d.battery_id.nunique()} batteries in {time.time()-t0:.1f}s")
    print(d[["soh_true", "ir_cell_mohm", "dv_dq", "capacity_est_norm", "t_rise"]].describe().round(3))
