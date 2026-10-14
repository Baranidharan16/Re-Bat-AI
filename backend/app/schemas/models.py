"""Pydantic request/response schemas (public API contract, incl. the ESP32 payload)."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class TelemetryReading(BaseModel):
    """One sample from the ESP32 rig (or the simulator — identical format)."""
    battery_id: str = Field(..., min_length=1, max_length=64, examples=["RB-001"])
    timestamp: Optional[Union[str, float, int]] = Field(None, description="ISO-8601 or epoch seconds/ms")
    t_s: Optional[float] = Field(None, description="Seconds since test start (preferred when device clock is unsynced)")
    voltage: float = Field(..., gt=0, lt=1000, description="Pack voltage [V]")
    current: float = Field(..., gt=-500, lt=500, description="Current [A], + = discharge")
    temperature: Optional[float] = Field(None, gt=-40, lt=150)
    capacity: Optional[float] = Field(None, description="Cumulative Ah discharged in this test (coulomb counter)")
    internal_resistance: Optional[float] = Field(None, ge=0, description="Ohm (last pulse measurement)")
    cycle_count: Optional[int] = Field(None, ge=0)
    cell_v_min: Optional[float] = None
    cell_v_max: Optional[float] = None
    series_cells: Optional[int] = Field(None, ge=1, le=400)
    nominal_capacity_ah: Optional[float] = Field(None, gt=0)
    phase: Optional[Literal["rest", "pulse", "run", "charge", "end"]] = None
    gas_v: Optional[float] = Field(None, ge=0, lt=10, description="Gas sensor output voltage (e.g. MQ-5), uncalibrated")
    gas_baseline_v: Optional[float] = Field(None, ge=0, lt=10)
    # second-life output sensors on the rig (not used by the SOH model; shown live and sent back to the board)
    ldr: Optional[float] = Field(None, ge=0, le=4095, description="LDR raw ADC (0–4095)")
    dark: Optional[bool] = Field(None, description="LDR says it is dark (street-light mode)")
    pir: Optional[bool] = Field(None, description="PIR motion detected")
    battery_present: Optional[bool] = Field(None, description="IR sensor sees a battery in the bay")
    lamp_on: Optional[bool] = Field(None, description="Lamp relay closed")
    load_on: Optional[bool] = Field(None, description="Test-load relay closed")
    rig_state: Optional[str] = Field(None, max_length=24, description="Firmware state, e.g. IDLE, REST, PULSE, DISCHARGE, LAMP, SAFETY")

    @field_validator("battery_id")
    @classmethod
    def _id(cls, v):
        if not all(c.isalnum() or c in "-_." for c in v):
            raise ValueError("battery_id may contain letters, digits, '-', '_' and '.' only")
        return v


class TelemetryBatch(BaseModel):
    readings: list[TelemetryReading] = Field(..., min_length=1, max_length=500)


class ManualInput(BaseModel):
    battery_id: str = Field("MANUAL-001", max_length=64)
    series_cells: int = Field(3, ge=1, le=400)
    nominal_capacity_ah: float = Field(2.5, gt=0)
    nominal_voltage: Optional[float] = None
    measured_voltage: Optional[float] = Field(None, gt=0)
    current: Optional[float] = None
    temperature: Optional[float] = Field(None, gt=-40, lt=150)
    temperature_rise: Optional[float] = Field(None, ge=0, lt=100)
    capacity_ah: Optional[float] = Field(None, gt=0, description="Measured full-discharge capacity")
    internal_resistance_mohm: Optional[float] = Field(None, gt=0, description="Pack DC resistance [mOhm]")
    cycle_count: Optional[int] = Field(None, ge=0)


class TestRequest(BaseModel):
    battery_id: str
    test_id: str
    context: Literal["demo", "live"] = "demo"
    reason: Optional[str] = None


class SimStart(BaseModel):
    profile_id: str = "RB-B02"
    test_id: Optional[str] = None
    speed_hz: float = Field(8.0, gt=0.5, le=50)
