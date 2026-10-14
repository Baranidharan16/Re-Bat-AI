"""WebSocket hub for ESP32 rigs that push their data.

    ESP32 ──ws://<laptop>:8000/api/v1/hardware/ws──►  FastAPI
      hello      {"type":"hello","battery_id":"RB-001","firmware":"rebat-ws 2.0","ip":"192.168.1.23"}
      telemetry  {"battery_id":"RB-001","voltage":11.4,"current":0.42,...,"ldr":2900,"pir":1,"battery_present":1,"lamp_on":1}
    ◄── ack      {"type":"ack","ok":true,"buffer":57}
    ◄── verdict  {"type":"verdict","pathway":"REUSE","best":"Solar energy storage","soh":77.0,...}   (after each AI forecast)
    ◄── command  {"type":"command","cmd":"lamp_on"}                                                (from the dashboard)

The hub keeps one entry per connected rig so the dashboard can show who is online
and send commands back to the right board.
"""
from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field

COMMANDS = {
    "start_test": "Start the full capacity test (REST → PULSE → DISCHARGE → RECOVERY)",
    "quick_test": "Start the 2-minute quick test (pulse + short discharge)",
    "stop": "Stop everything — both relays open",
    "lamp_on": "Street light ON (manual)",
    "lamp_off": "Street light OFF (manual)",
    "lamp_auto": "Street light automatic (LDR + PIR)",
    "load_on": "Test load ON",
    "load_off": "Test load OFF",
}


@dataclass
class RigConnection:
    ws: object
    battery_id: str
    remote: str
    connected_at: float = field(default_factory=time.time)
    last_msg_at: float = field(default_factory=time.time)
    messages: int = 0
    firmware: str | None = None
    device_ip: str | None = None
    aux: dict = field(default_factory=dict)
    last_verdict_id: int | None = None
    commands_sent: int = 0

    def summary(self) -> dict:
        return {"battery_id": self.battery_id, "remote": self.remote, "device_ip": self.device_ip,
                "firmware": self.firmware, "connected_for_s": round(time.time() - self.connected_at),
                "last_message_s_ago": round(time.time() - self.last_msg_at, 1), "messages": self.messages,
                "aux": self.aux, "commands_sent": self.commands_sent}


class ESP32Hub:
    def __init__(self):
        self.rigs: dict[int, RigConnection] = {}

    def add(self, ws, remote: str) -> RigConnection:
        c = RigConnection(ws=ws, battery_id="RB-001", remote=remote)
        self.rigs[id(ws)] = c
        return c

    def remove(self, ws):
        self.rigs.pop(id(ws), None)

    def for_battery(self, battery_id: str) -> RigConnection | None:
        live = [c for c in self.rigs.values() if c.battery_id == battery_id]
        return max(live, key=lambda c: c.last_msg_at) if live else None

    def status(self) -> dict:
        return {"connected": len(self.rigs), "rigs": [c.summary() for c in self.rigs.values()]}

    async def send(self, battery_id: str, msg: dict) -> bool:
        c = self.for_battery(battery_id)
        if c is None:
            return False
        await c.ws.send_text(json.dumps(msg))
        if msg.get("type") == "command":
            c.commands_sent += 1
        return True


def lan_ips() -> list[str]:
    """This computer's addresses on the local network (what the ESP32 must connect to)."""
    ips = []
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                sk.connect((probe, 1))          # no packet is sent; picks the outgoing interface
                ip = sk.getsockname()[0]
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
        except OSError:
            pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def verdict_message(result: dict) -> dict:
    """Short AI result for the ESP32's OLED."""
    c = result.get("circular") or {}
    best = next((o for o in (c.get("reuse") or {}).get("options", []) if o["id"] == (c.get("reuse") or {}).get("best")), None)
    if c.get("pathway") not in ("REUSE", "RETEST"):
        best = None
    return {"type": "verdict", "pathway": c.get("pathway"), "headline": c.get("headline"),
            "best": best["name"] if best else None, "best_id": best["id"] if best else None,
            "soh": result["soh"]["soh"], "soh_lo": result["soh"]["lo"], "soh_hi": result["soh"]["hi"],
            "rul_cycles": result["rul"]["rul_cycles"], "confidence": result["confidence"]["value"],
            "safety": result["safety"]["status"],
            "block": (result.get("ledger") or {}).get("idx"),
            "lamp_allowed": c.get("pathway") in ("REUSE", "RETEST") and result["safety"]["status"] != "ALARM"}


hub = ESP32Hub()
