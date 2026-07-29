"""Unit tests for the sump pump plant model (no Streamlit / PLC required)."""

from __future__ import annotations

from simulation import PlantCommands, SumpPumpStation


def test_normal_start_sequence() -> None:
    plant = SumpPumpStation(startup_delay_s=4.0, pressure_rise_s=1.0)
    t = 100.0

    plant.set_commands(PlantCommands(pump_start_cmd=True))
    fb = plant.tick(now=t)
    assert plant.is_starting
    assert not fb.pump_running

    # Hold start low after edge; still starting during delay.
    plant.set_commands(PlantCommands())
    fb = plant.tick(now=t + 2.0)
    assert plant.is_starting
    assert not fb.pump_running

    fb = plant.tick(now=t + 4.0)
    assert fb.pump_running
    assert not fb.disch_pressure_ok

    fb = plant.tick(now=t + 5.0)
    assert fb.pump_running
    assert fb.disch_pressure_ok


def test_stop_cancels_start() -> None:
    plant = SumpPumpStation(startup_delay_s=4.0)
    t = 0.0
    plant.set_commands(PlantCommands(pump_start_cmd=True))
    plant.tick(now=t)
    assert plant.is_starting

    plant.set_commands(PlantCommands(pump_stop_cmd=True))
    fb = plant.tick(now=t + 1.0)
    assert not plant.is_starting
    assert not fb.pump_running


def test_fault_injection_and_reset() -> None:
    plant = SumpPumpStation(startup_delay_s=1.0, pressure_rise_s=0.0)
    t = 0.0
    plant.set_commands(PlantCommands(pump_start_cmd=True))
    plant.tick(now=t)
    plant.set_commands(PlantCommands())
    fb = plant.tick(now=t + 1.0)
    assert fb.pump_running

    plant.inject_pump_fault()
    fb = plant.get_feedback()
    assert fb.pump_fault
    assert not fb.pump_running

    # Start ignored while faulted.
    plant.set_commands(PlantCommands(pump_start_cmd=True))
    fb = plant.tick(now=t + 2.0)
    assert not fb.pump_running
    assert not plant.is_starting

    plant.set_commands(PlantCommands(pump_reset_cmd=True))
    fb = plant.tick(now=t + 3.0)
    assert not fb.pump_fault


def test_valve_is_independent_plant_signal() -> None:
    plant = SumpPumpStation()
    assert plant.get_feedback().downstream_valve_open
    plant.set_downstream_valve_open(False)
    assert not plant.get_feedback().downstream_valve_open


def test_initial_state_matches_fds() -> None:
    fb = SumpPumpStation().get_feedback()
    assert not fb.pump_running
    assert not fb.pump_fault
    assert not fb.disch_pressure_ok
    assert fb.downstream_valve_open
