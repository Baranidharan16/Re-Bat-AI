"""RE-BAT AI battery assistant.

Answers questions about ONE battery (the one open in the dashboard) or an example EV pack.
Online: Google Gemini (key in backend/.env -> GEMINI_API_KEY). Offline / no key / no internet:
a built-in answerer that reads the same battery data, so the demo never goes silent.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

from app.config import BACKEND_DIR

log = logging.getLogger("rebat.assistant")
MODELS = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash") if m]
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _load_env():
    p = BACKEND_DIR / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def status() -> dict:
    return {"provider": "Google Gemini" if api_key() else "offline", "key_configured": bool(api_key()), "models": MODELS}


SYSTEM = """You are the RE-BAT AI assistant inside a battery second-life dashboard built by engineering students in India.
You answer questions about ONE specific battery whose data is given below as JSON (measured on an ESP32 rig or simulated
for the demo), and about EV batteries, second-life reuse and recycling in general.
Rules:
- Use the battery data for anything about this battery. Quote numbers with units. If a value is missing, say it was not measured
  and which test or sensor would measure it.
- The second-life decision is REUSE (solar storage, factory backup, household backup, rural street light), RECYCLE (mineral
  recovery into new EV cells), RETEST (low confidence) or HOLD (safety). Explain it with SOH, RUL, resistance, temperature,
  imbalance, efficiency and the application scores.
- Mineral figures are typical-composition estimates (±20 %). Do not invent gold or silver amounts; BMS electronics go to e-waste.
- The demo model is trained on simulated data; say so if asked about accuracy. Never claim certification or guaranteed safety;
  final reuse needs validated electrical, thermal and safety testing.
- Ledger: every analysis is sealed as a SHA-256 hash-chained block that includes a fingerprint of the model's hyperparameters.
- Be concise (under 180 words unless asked for detail), friendly, plain English; use short bullet points when listing."""


def _compact(ctx: dict) -> str:
    s = json.dumps(ctx, default=str, separators=(",", ":"))
    return s[:14000]


def ask(message: str, history: list[dict], context: dict) -> dict:
    key = api_key()
    if key:
        contents = []
        for h in history[-8:]:
            role = "model" if h.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": str(h.get("text", ""))[:2000]}]})
        contents.append({"role": "user", "parts": [{"text": message[:2000]}]})
        body = {"systemInstruction": {"parts": [{"text": SYSTEM + "\n\nBATTERY DATA (JSON):\n" + _compact(context)}]},
                "contents": contents, "generationConfig": {"temperature": 0.3, "maxOutputTokens": 900}}
        last_err = None
        for model in MODELS:
            try:
                req = urllib.request.Request(API.format(model=model), data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json", "x-goog-api-key": key})
                with urllib.request.urlopen(req, timeout=25) as r:
                    out = json.loads(r.read())
                parts = out["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    return {"answer": text, "provider": f"Gemini · {model}", "online": True}
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.read()[:200]!r}"
                if e.code in (400, 401, 403):
                    break                     # bad key — other models will fail the same way
            except Exception as e:            # no internet, timeout, unexpected shape
                last_err = f"{type(e).__name__}: {e}"
                break
        log.warning("Gemini unavailable (%s) — answering offline", last_err)
        ans = offline_answer(message, context)
        ans["note"] = f"Online AI unavailable ({last_err}); answered from the battery data."
        return ans
    return offline_answer(message, context)


# ---------------------------------------------------------------------------- offline answerer
def _g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


def offline_answer(q: str, c: dict) -> dict:
    ql = q.lower()
    bid = c.get("battery_id", "this battery")
    soh, rul = _g(c, "soh"), _g(c, "rul_cycles")
    circ = c.get("circular") or {}
    pw, head, reason = circ.get("pathway"), circ.get("headline"), circ.get("reason")
    opts = circ.get("reuse_options") or []
    params = c.get("parameters") or []
    mins = c.get("minerals") or []
    lines: list[str] = []

    def has(*w):
        return any(re.search(r"\b" + x, ql) for x in w)

    if has("soh", "health", "state of health", "good", "condition"):
        lines.append(f"{bid} has SOH {soh}% (90% band {c.get('soh_lo')}–{c.get('soh_hi')}%), AI confidence {c.get('confidence')}%.")
    if has("rul", "life", "years", "how long", "cycles"):
        lines.append(f"Remaining useful life ≈ {rul} cycles to 60% SOH — about {round((rul or 0) / 365, 1)} years at one cycle a day.")
    if has("reuse", "solar", "factory", "household", "home", "street", "light", "recommend", "best", "use", "second"):
        lines.append(f"Decision: {head}. {reason or ''}".strip())
        for o in opts[:4]:
            lines.append(f"• {o.get('name')}: score {o.get('score')}/100 ({o.get('status')})")
    if has("recycl", "mineral", "lithium", "nickel", "cobalt", "manganese", "graphite", "copper", "alumin", "china", "import", "metal"):
        if mins:
            lines.append("Recoverable minerals in this pack (typical composition, ±20%):")
            for m in mins[:8]:
                lines.append(f"• {m.get('name')} ({m.get('symbol')}): {m.get('recoverable_g')} g of {m.get('contained_g')} g — {m.get('part')}")
        lines.append("Li, Ni, Co and Mn are recovered by hydrometallurgy as battery-grade salts and go back into new EV cathodes.")
    if has("resist", "temperature", "heat", "thermal", "gas", "safe", "imbalance", "voltage", "current", "efficien", "parameter", "measure", "sensor"):
        for p in params:
            lines.append(f"• {p.get('name')}: {p.get('value')} {p.get('unit')} — {p.get('grade')}")
    if has("ledger", "blockchain", "hash", "sha", "passport", "tamper", "block"):
        pb = c.get("passport_block") or {}
        lines.append(f"Passport {c.get('passport_id')} is sealed in block #{pb.get('idx')} (hash {str(pb.get('block_hash', ''))[:16]}…). "
                     "Each block stores the SOH, RUL, pathway, evidence hash and a SHA-256 fingerprint of the model's hyperparameters, "
                     "chained to the previous block — any edit breaks the chain.")
    if has("why", "cause", "aged", "degrad", "forensic", "damage"):
        lines.append(c.get("forensic_verdict") or "No forensic verdict available.")
    if has("cell", "chemistry", "nmc", "lfp", "inside", "layer", "bms", "cool", "busbar", "module"):
        lines.append(f"Chemistry: {c.get('chemistry_label', 'NMC')}. A pack has a top cover, cooling plate, busbars, modules of cells, "
                     "the BMS and a base frame. Each cell: cathode (Li + metal oxide or FePO4), separator, graphite anode on copper foil, electrolyte.")
    if not lines:
        lines = [f"{bid}: SOH {soh}%, RUL {rul} cycles, decision — {head}.",
                 "Ask me about its health, remaining life, reuse options (solar / factory / household / street light), "
                 "recyclable minerals, the measured parameters, why it aged, or its ledger passport."]
    return {"answer": "\n".join(lines), "provider": "RE-BAT offline assistant", "online": False}
