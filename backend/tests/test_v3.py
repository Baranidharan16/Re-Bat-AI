"""3.0: EV pack models, measured parameters, passport ledger blocks, AI assistant."""
import os

from fastapi.testclient import TestClient

from app.main import app
from app.services import assistant

client = TestClient(app)


def test_ev_models_have_parts_and_minerals():
    ids = {m["id"] for m in client.get("/api/v1/ev-models").json()}
    assert {"rebat_rig", "nissan_leaf_40", "tesla_model3_lr", "tata_nexon_ev_45"} <= ids
    t = client.get("/api/v1/ev-models/tesla_model3_lr").json()
    assert t["minerals"]["n_cells"] == 4416 and len(t["parts"]) == 6
    assert t["visual"]["modules"][0] * t["visual"]["modules"][1] * t["visual"]["cells"][0] * t["visual"]["cells"][1] == 4416
    lfp = client.get("/api/v1/ev-models/tata_nexon_ev_45").json()
    assert "Co" not in lfp["pack_metal_totals_g"] and "Fe" in lfp["pack_metal_totals_g"]


def test_parameters_and_passport_block():
    a = client.get("/api/v1/demo/batteries/RB-C03/analysis").json()
    assert len(a["circular"]["parameters"]) == 10
    pb = a["passport_block"]
    again = client.get("/api/v1/demo/batteries/RB-C03/analysis").json()["passport_block"]
    assert again["idx"] == pb["idx"] and again["existing"]            # one block per evidence hash
    blk = next(b for b in client.get("/api/v1/ledger?limit=100").json() if b["idx"] == pb["idx"])
    assert blk["payload"]["type"] == "passport" and len(blk["payload"]["model_fingerprint"]) == 64
    assert client.get("/api/v1/ledger/verify").json()["valid"]


def test_chat_offline_and_unreachable_key_fallback(monkeypatch):
    ctx = {"battery_id": "RB-X", "soh": 77, "rul_cycles": 1690,
           "circular": {"pathway": "REUSE", "headline": "Reuse — Solar", "reuse_options": []}}
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.post("/api/v1/chat", json={"message": "what is the SOH?", "context": ctx}).json()
    assert "77" in r["answer"] and not r["online"]
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(assistant.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    r = client.post("/api/v1/chat", json={"message": "remaining life?", "context": ctx}).json()
    assert "1690" in r["answer"] and "unavailable" in r["note"]


def test_chat_gemini_response_is_parsed(monkeypatch):
    import io, json as _j
    seen = {}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=0):
        seen["url"], seen["key"] = req.full_url, req.headers.get("X-goog-api-key")
        seen["body"] = _j.loads(req.data)
        return R(_j.dumps({"candidates": [{"content": {"parts": [{"text": "SOH is 77% — good for solar."}]}}]}).encode())

    monkeypatch.setenv("GEMINI_API_KEY", "k123")
    monkeypatch.setattr(assistant.urllib.request, "urlopen", fake)
    r = client.post("/api/v1/chat", json={"message": "good for solar?", "history": [{"role": "assistant", "text": "hi"}],
                                          "context": {"battery_id": "RB-X", "soh": 77}}).json()
    assert r["online"] and r["answer"].startswith("SOH is 77%")
    assert ":generateContent" in seen["url"] and seen["key"] == "k123"
    assert seen["body"]["contents"][0]["role"] == "model" and "RB-X" in seen["body"]["systemInstruction"]["parts"][0]["text"]
