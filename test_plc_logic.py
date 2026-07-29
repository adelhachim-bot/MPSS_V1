"""Unit tests for SoftPLC permissive logic (no Modbus required)."""

from __future__ import annotations

from plc_logic import PlcInputs, SumpPumpPlcLogic


def test_normal_start_pulse() -> None:
    plc = SumpPumpPlcLogic(pulse_scans=3)
    out = plc.scan(
        PlcInputs(downstream_valve_open=True, op_start=True)
    )
    assert out.pump_start_cmd
    assert not out.start_blocked
    assert "Start command" in out.message

    # Held for remaining scans while op_start stays high (no new edge).
    out = plc.scan(PlcInputs(downstream_valve_open=True, op_start=True))
    assert out.pump_start_cmd
    out = plc.scan(PlcInputs(downstream_valve_open=True, op_start=True))
    assert out.pump_start_cmd
    out = plc.scan(PlcInputs(downstream_valve_open=True, op_start=True))
    assert not out.pump_start_cmd


def test_valve_closed_latches_start_blocked() -> None:
    plc = SumpPumpPlcLogic()
    out = plc.scan(PlcInputs(downstream_valve_open=False, op_start=True))
    assert not out.pump_start_cmd
    assert out.start_blocked

    # Further starts rejected until reset.
    out = plc.scan(PlcInputs(downstream_valve_open=True, op_start=False))
    out = plc.scan(PlcInputs(downstream_valve_open=True, op_start=True))
    assert not out.pump_start_cmd
    assert out.start_blocked
    assert "rejected" in out.message.lower() or "clear" in out.message.lower()


def test_reset_clears_alarm_and_allows_start() -> None:
    plc = SumpPumpPlcLogic(pulse_scans=2)
    plc.scan(PlcInputs(downstream_valve_open=False, op_start=True))
    assert plc.state.start_blocked

    out = plc.scan(PlcInputs(downstream_valve_open=True, op_reset=True))
    assert out.pump_reset_cmd
    assert not out.start_blocked

    out = plc.scan(PlcInputs(downstream_valve_open=True, op_reset=False))
    out = plc.scan(PlcInputs(downstream_valve_open=True, op_start=True))
    assert out.pump_start_cmd


def test_stop_pulse() -> None:
    plc = SumpPumpPlcLogic(pulse_scans=2)
    out = plc.scan(PlcInputs(op_stop=True))
    assert out.pump_stop_cmd
