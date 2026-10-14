"""Reuse / recycle engine, minerals, forensics and the ESP32 WebSocket connector."""
from fastapi.testclient import TestClient

from app.main import app
from app.services import circular, demo_service

client = TestClient(app)


def test_pathways_for_demo_batteries():
    assert demo_service.analyze("RB-B02")["circular"]["pathway"] == "REUSE"
    assert demo_service.analyze("RB-E05")["circular"]["pathway"] == "RETEST"
    f = demo_service.analyze("RB-F06")
    assert f["circular"]["pathway"] == "RECYCLE"
    assert f["forensics"]["passport_id"].startswith("BP-")
    ids = {o["id"] for o in f["circular"]["reuse"]["options"]}
    assert ids == {"solar_storage", "factory_backup", "household_backup", "street_light"}


def test_minerals_add_up_and_iron_only_where_present():
    m = circular.minerals(3, 2.5, "NMC532", "cylindrical_18650")
    total = sum(x["contained_g"] for x in m["materials"]) + sum(x["contained_g"] for x in m["non_recovered"])
    assert abs(total - m["pack_mass_g"]) <= 0.01 * m["pack_mass_g"]   # 2 % nickel plating of the can is not listed
    syms = {x["symbol"] for x in m["materials"]}
    assert {"Li", "Ni", "Co", "Mn", "Cu", "Al", "C"} <= syms and "P" not in syms
    pouch = circular.minerals(3, 60, "NMC811", "pouch_ev")
    assert "Fe" not in {x["symbol"] for x in pouch["materials"]}          # no steel can, no iron cathode
    lfp = circular.minerals(4, 280, "LFP", "prismatic_lfp_280")
    assert {"Fe", "P"} <= {x["symbol"] for x in lfp["materials"]} and "Co" not in {x["symbol"] for x in lfp["materials"]}


def test_websocket_connector_hello_status_command():
    with client.websocket_connect("/api/v1/hardware/ws") as ws:
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json({"type": "hello", "battery_id": "RB-WS-T", "firmware": "test"})
        assert ws.receive_json()["type"] == "hello_ack"
        ws.send_json({"type": "status", "battery_id": "RB-WS-T", "voltage": 11.5, "dark": True, "pir": False, "lamp_on": False})
        rigs = client.get("/api/v1/hardware/rigs").json()
        assert rigs["connected"] == 1 and rigs["rigs"][0]["battery_id"] == "RB-WS-T"
        assert client.post("/api/v1/hardware/RB-WS-T/command", json={"cmd": "lamp_on"}).json()["sent"]
        cmd = ws.receive_json()
        assert cmd["type"] == "command" and cmd["cmd"] == "lamp_on"
        ws.send_json({"battery_id": "RB-WS-T", "t_s": 1, "voltage": 11.8, "current": 0.4, "lamp_on": True, "phase": "run"})
        ack = ws.receive_json()
        assert ack["type"] == "ack" and ack["ok"]
    assert client.post("/api/v1/hardware/RB-WS-T/command", json={"cmd": "lamp_on"}).status_code == 409
    info = client.get("/api/v1/hardware/connect-info").json()
    assert info["websocket_path"] == "/api/v1/hardware/ws"


