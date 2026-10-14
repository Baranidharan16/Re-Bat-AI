"""Example EV battery packs for the 3D explorer: layers, cells and the minerals inside each part."""
from __future__ import annotations

from app.config import load_json
from app.services import circular


def cfg() -> dict:
    return load_json("ev_models.json")


def catalog() -> list[dict]:
    c = cfg()
    return [{"id": k, "name": v["name"], "vehicle": v["vehicle"], "chemistry": v["chemistry"], "cell_shape": v["cell_shape"],
             "pack_kwh": v["pack_kwh"], "cells": v["cells"]} for k, v in c["models"].items()]


def report(model_id: str) -> dict:
    c = cfg()
    m = c["models"][model_id]                      # KeyError -> 404
    fmt = circular.cfg()["cell_formats"][m["cell_format"]]
    if m.get("cells"):
        cell_mass_total = m["cells"] * fmt["cell_mass_g"]
    else:
        cell_mass_total = m["pack_kwh"] * 1000 / m["cell_mass_from_energy_wh_per_kg"] * 1000
    if m.get("cell_mass_from_energy_wh_per_kg") and m.get("cells"):
        # energy-based estimate is more reliable than a generic cell-format mass for big EV cells
        cell_mass_total = m["pack_kwh"] * 1000 / m["cell_mass_from_energy_wh_per_kg"] * 1000
    mins = circular.minerals(1, 1, m["chemistry"], m["cell_format"],
                             total_cell_mass_g=cell_mass_total, n_cells_override=m.get("cells"))
    ratio = c["cell_to_pack_mass_ratio"] if model_id != "rebat_rig" else 0.85
    pack_mass = cell_mass_total / ratio
    rest = pack_mass - cell_mass_total
    parts = []
    for pid, p in c["pack_parts"].items():
        if pid == "_note":
            continue
        parts.append({"id": pid, "name": p["name"], "role": p["role"], "material": p["material"],
                      "material_name": p["material_name"], "mass_g": round(rest * p["share"], 1)})
    cell_part = {"id": "modules", "name": "Battery modules (cells)", "mass_g": round(cell_mass_total, 1),
                 "role": "Store the energy. Each cell has a cathode (Li + metal oxide or iron phosphate), a graphite anode, "
                         "a separator and electrolyte inside a can or pouch.", "material": "cells",
                 "material_name": mins["chemistry_label"]}
    totals_by_metal = {r["symbol"]: r["contained_g"] for r in mins["materials"]}
    for p in parts:                                  # pack hardware adds aluminium and copper
        if p["material"] in ("Al", "Cu"):
            totals_by_metal[p["material"]] = totals_by_metal.get(p["material"], 0) + p["mass_g"]
    return {"id": model_id, **{k: m[k] for k in ("name", "vehicle", "chemistry", "cell_format", "cell_shape", "pack_kwh",
                                                 "nominal_v", "cells", "config", "modules", "visual", "source", "mass_note")},
            "cell_mass_g": round(cell_mass_total, 1), "pack_mass_g": round(pack_mass, 1),
            "parts": [cell_part] + parts, "minerals": mins,
            "pack_metal_totals_g": {k: round(v, 1) for k, v in sorted(totals_by_metal.items(), key=lambda kv: -kv[1])},
            "note": "Pack hardware masses are typical shares of a liquid-cooled EV pack; cell minerals from chemistry and cell format (±20 %)."}
