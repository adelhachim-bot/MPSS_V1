"""Integration test: SoftPLC Modbus server + MPSS bridge (free stack)."""

from __future__ import annotations

import threading
import time

import pytest

from plc_bridge import ModbusPlcBridge
from simulation import PlantFeedback, SumpPumpStation
from soft_plc import SoftPlcRuntime


@pytest.fixture(scope="module")
def soft_plc_port() -> int:
    return 5503  # avoid colliding with a manually started soft_plc on 5502


@pytest.fixture(scope="module")
def running_soft_plc(soft_plc_port: int):
    runtime = SoftPlcRuntime(host="127.0.0.1", port=soft_plc_port, scan_s=0.05)
    thread = threading.Thread(target=runtime.serve, name="test-soft-plc", daemon=True)
    thread.start()
    # Wait until the Modbus port accepts connections.
    deadline = time.time() + 5.0
    bridge = ModbusPlcBridge(host="127.0.0.1", port=soft_plc_port)
    while time.time() < deadline:
        if bridge.connect():
            bridge.close()
            break
        time.sleep(0.1)
    else:
        pytest.fail("SoftPLC did not start listening in time")
    yield runtime
    runtime._stop.set()  # noqa: SLF001


def test_modbus_normal_start(running_soft_plc, soft_plc_port: int) -> None:
    del running_soft_plc
    plant = SumpPumpStation(startup_delay_s=0.2, pressure_rise_s=0.05)
    bridge = ModbusPlcBridge(host="127.0.0.1", port=soft_plc_port)
    assert bridge.connect()

    bridge.operator_start()
    commands = bridge.step(plant.get_feedback())
    plant.set_commands(commands)
    t0 = time.monotonic()
    fb = plant.tick(now=t0)
    assert plant.is_starting or fb.pump_running

    # Advance through startup delay.
    plant.set_commands(bridge.step(plant.get_feedback()))
    fb = plant.tick(now=t0 + 0.25)
    assert fb.pump_running
    bridge.close()


def test_modbus_start_blocked_when_valve_closed(
    running_soft_plc, soft_plc_port: int
) -> None:
    del running_soft_plc
    plant = SumpPumpStation()
    plant.set_downstream_valve_open(False)
    bridge = ModbusPlcBridge(host="127.0.0.1", port=soft_plc_port)
    assert bridge.connect()

    # Clear any prior latch from other tests.
    bridge.operator_reset()
    bridge.step(plant.get_feedback())
    time.sleep(0.15)

    bridge.operator_start()
    commands = bridge.step(plant.get_feedback())
    assert not commands.pump_start_cmd
    assert bridge.state.start_blocked
    bridge.close()
