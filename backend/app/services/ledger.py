"""Tamper-evident battery passport ledger (blockchain-style, single node).

Each forecast of real-time data creates one block:
  leaf_i      = SHA-256(canonical JSON of reading i)
  merkle_root = Merkle root of all leaves in the forecast window
  payload     = forecast summary (SOH, interval, confidence, RUL, routing, model version) + merkle_root
  block_hash  = SHA-256(idx | created_at | prev_hash | merkle_root | payload_hash | nonce)
with a light proof-of-work (block_hash starts with DIFFICULTY zeros).

`verify()` recomputes every hash from the stored readings and forecasts, so any
edit to a reading, a forecast or a block is detected. To anchor on a public chain
later, publish the latest block_hash (e.g. Polygon/Ethereum tx or OpenTimestamps)
— the data model already supports it.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app import db

GENESIS_PREV = "0" * 64
DIFFICULTY = 3   # leading hex zeros


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def reading_leaf(r: dict) -> str:
    keys = ("battery_id", "session_id", "t_s", "voltage", "current", "temperature", "capacity",
            "cycle_count", "internal_resistance", "cell_v_min", "cell_v_max", "device_ts")
    # round, and add 0.0 so -0.0 and 0.0 hash identically after a SQLite round trip
    d = {k: (round(r[k], 6) + 0.0 if isinstance(r.get(k), float) else r.get(k)) for k in keys}
    if r.get("gas_v") is not None:          # added later: only hashed when present, so older blocks still verify
        d["gas_v"] = round(float(r["gas_v"]), 6) + 0.0
    return sha(db.dumps(d))


def merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return sha("")
    level = leaves[:]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def _block_hash(idx, created_at, prev, root, payload_hash, nonce):
    return sha(f"{idx}|{created_at}|{prev}|{root}|{payload_hash}|{nonce}")


def _mine(idx, created_at, prev, root, payload_hash):
    nonce = 0
    while True:
        h = _block_hash(idx, created_at, prev, root, payload_hash, nonce)
        if h.startswith("0" * DIFFICULTY):
            return nonce, h
        nonce += 1


def append_block(con, payload: dict, leaves: list[str]) -> dict:
    """Must be called inside db.tx() so the block commits atomically with its data."""
    last = con.execute("SELECT idx, block_hash FROM ledger_blocks ORDER BY idx DESC LIMIT 1").fetchone()
    idx = 0 if last is None else last["idx"] + 1
    prev = GENESIS_PREV if last is None else last["block_hash"]
    root = merkle_root(leaves)
    payload = dict(payload, merkle_root=root, n_leaves=len(leaves))
    pj = db.dumps(payload)
    ph = sha(pj)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nonce, bh = _mine(idx, created, prev, root, ph)
    con.execute("INSERT INTO ledger_blocks(idx, created_at, prev_hash, merkle_root, payload_hash, payload_json, nonce, block_hash)"
                " VALUES (?,?,?,?,?,?,?,?)", (idx, created, prev, root, ph, pj, nonce, bh))
    return {"idx": idx, "block_hash": bh, "prev_hash": prev, "merkle_root": root, "nonce": nonce, "created_at": created}


def list_blocks(limit: int = 50, battery_id: str | None = None) -> list[dict]:
    rows = db.query("SELECT * FROM ledger_blocks ORDER BY idx DESC LIMIT ?", (limit * 5 if battery_id else limit,))
    out = []
    import json
    for r in rows:
        r["payload"] = json.loads(r.pop("payload_json"))
        if battery_id and r["payload"].get("battery_id") != battery_id:
            continue
        out.append(r)
    return out[:limit]


def verify() -> dict:
    import json
    blocks = db.query("SELECT * FROM ledger_blocks ORDER BY idx ASC")
    prev = GENESIS_PREV
    results, ok_all = [], True
    for b in blocks:
        problems = []
        if b["prev_hash"] != prev:
            problems.append("prev_hash does not match previous block")
        if sha(b["payload_json"]) != b["payload_hash"]:
            problems.append("payload modified")
        if _block_hash(b["idx"], b["created_at"], b["prev_hash"], b["merkle_root"], b["payload_hash"], b["nonce"]) != b["block_hash"]:
            problems.append("block hash invalid")
        if not b["block_hash"].startswith("0" * DIFFICULTY):
            problems.append("proof-of-work invalid")
        payload = json.loads(b["payload_json"])
        fid = payload.get("forecast_id")
        if fid is not None:
            rows = db.query("SELECT * FROM readings WHERE forecast_id=? ORDER BY id", (fid,))
            leaves = [reading_leaf(r) for r in rows]
            if merkle_root(leaves) != b["merkle_root"]:
                problems.append("stored readings do not match merkle root")
            f = db.query("SELECT soh, confidence, decision FROM forecasts WHERE id=?", (fid,))
            if not f:
                problems.append("forecast row missing")
            elif abs((f[0]["soh"] or 0) - (payload.get("soh") or 0)) > 1e-6 or f[0]["decision"] != payload.get("decision"):
                problems.append("forecast row modified")
        ok = not problems
        ok_all &= ok
        results.append({"idx": b["idx"], "ok": ok, "problems": problems, "block_hash": b["block_hash"]})
        prev = b["block_hash"]
    return {"valid": ok_all, "n_blocks": len(blocks), "difficulty": DIFFICULTY,
            "head": blocks[-1]["block_hash"] if blocks else None, "blocks": results[-100:]}


# ---------------------------------------------------------------------------- battery passport blocks
_MODEL_FP: dict | None = None


def model_fingerprint() -> dict:
    """SHA-256 over the SOH model's hyperparameters, feature list, training metadata and weights file.
    Stored in every passport block, so each verdict is tied to the exact model that produced it."""
    global _MODEL_FP
    if _MODEL_FP is None:
        import json
        from app.config import MODEL_DIR
        card = json.loads((MODEL_DIR / "model_card.json").read_text())
        hyper = {"n_estimators": 1200, "learning_rate": 0.03, "max_depth": 5, "subsample": 0.85,
                 "colsample_bytree": 0.85, "min_child_weight": 3, "reg_lambda": 1.0, "early_stopping_rounds": 60,
                 "best_iteration": card.get("best_iteration"), "quantiles": card.get("quantiles"),
                 "conformal_q": card.get("conformal_q")}
        weights = hashlib.sha256((MODEL_DIR / "soh_xgb_point.json").read_bytes()).hexdigest()
        meta = {"model": card["model_name"], "version": card["version"], "trained_at": card.get("trained_at"),
                "features": card.get("features"), "hyperparameters": hyper, "weights_sha256": weights}
        _MODEL_FP = {"hash": sha(db.dumps(meta)), "weights_sha256": weights, "hyperparameters": hyper,
                     "model": f"{card['model_name']} {card['version']}", "trained_at": card.get("trained_at")}
    return _MODEL_FP


def seal_passport(result: dict) -> dict:
    """Seal an analysis (demo / CSV / manual) as a battery-passport block. One block per unique evidence hash."""
    ev = (result.get("forensics") or {}).get("evidence_hash")
    if ev:
        for b in list_blocks(limit=400):
            if b["payload"].get("evidence_hash") == ev:
                return {"idx": b["idx"], "block_hash": b["block_hash"], "prev_hash": b["prev_hash"],
                        "merkle_root": b["merkle_root"], "created_at": b["created_at"], "existing": True}
    circ = result.get("circular") or {}
    rec = circ.get("recycle") or {}
    best = (circ.get("reuse") or {}).get("best")
    params = {p["id"]: p["value"] for p in circ.get("parameters", [])}
    leaves = [sha(db.dumps({"parameter": k, "value": v})) for k, v in sorted(params.items())]
    mf = model_fingerprint()
    payload = {"type": "passport", "battery_id": result["battery_id"], "source": result["source"],
               "passport_id": (result.get("forensics") or {}).get("passport_id"),
               "soh": result["soh"]["soh"], "soh_interval": [result["soh"]["lo"], result["soh"]["hi"]],
               "rul_cycles": result["rul"]["rul_cycles"], "confidence": result["confidence"]["value"],
               "decision": result["router"]["decision"]["id"], "pathway": circ.get("pathway"), "best_reuse": best,
               "critical_minerals_g": (rec.get("totals") or {}).get("critical_recoverable_g"),
               "chemistry": rec.get("chemistry"), "evidence_hash": ev, "safety": result["safety"]["status"],
               "model": mf["model"], "model_fingerprint": mf["hash"], "model_weights_sha256": mf["weights_sha256"]}
    with db.tx() as con:
        blk = append_block(con, payload, leaves)
    return {**blk, "existing": False}
