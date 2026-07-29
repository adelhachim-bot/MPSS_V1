"""Modbus TCP client bridge: MPSS <-> SoftPLC.

MPSS is the client; soft_plc.py is the Modbus TCP server running the real
control logic. This is the only PLC integration path for the pilot.

Everything in this file is deliberately "dumb" — it has no idea what a
pump, a valve, or a permissive is. It only knows how to push some numbers
into Modbus registers and pull some bits back out of Modbus coils. All the
actual decision-making happens on the other end of the network connection
(soft_plc.py + plc_logic.py). That split is the whole point: this same
class would work unmodified against a real PLC, because Modbus TCP looks
the same whether the server is a Python script or a physical controller.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient

from io_map import (
    COIL_PUMP_START_CMD,
    COIL_START_BLOCKED,
    DEFAULT_HOST,
    DEFAULT_PORT,
    HR_PUMP_RUNNING,
)
from simulation import PlantCommands, PlantFeedback

# The SoftPLC only updates its outputs once per scan (default 50 ms). If we
# wrote our inputs and read the outputs back instantly, we could easily read
# a stale value from *before* the PLC noticed our write. Sleeping here for
# longer than one scan guarantees the PLC has had a chance to react.
SETTLE_S = 0.1


@dataclass
class BridgeState:
    """Small bit of status the UI reads to show link/alarm state."""

    start_blocked: bool = False
    last_message: str = "Not connected to SoftPLC"
    connected: bool = False


class ModbusPlcBridge:
    """HMI/plant side of the Modbus link (client).

    "Client" here has a specific Modbus meaning: the client is the side that
    initiates every request (read this / write that); the server (SoftPLC)
    only ever responds. MPSS is always the one asking questions.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.state = BridgeState()
        self._client = ModbusTcpClient(host=host, port=port, timeout=0.5)
        # Buttons on the HMI don't talk to the PLC instantly — they just
        # flip one of these flags. The next call to step() is what actually
        # sends it over Modbus. This little buffer is what lets operator_*()
        # be instant/non-blocking while step() does the (slower) network IO.
        self._pending_op = {"start": False, "stop": False, "reset": False}

    def close(self) -> None:
        self._client.close()
        self.state.connected = False

    def connect(self) -> bool:
        ok = bool(self._client.connect())
        self.state.connected = ok
        if ok:
            self.state.last_message = f"Connected to SoftPLC at {self.host}:{self.port}"
        else:
            self.state.last_message = (
                f"Cannot reach SoftPLC at {self.host}:{self.port} — "
                "start soft_plc.py first"
            )
        return ok

    def ensure_connected(self) -> bool:
        """Reconnect lazily if the link dropped, instead of failing forever."""
        if self._client.connected:
            self.state.connected = True
            return True
        return self.connect()

    def reset_logic(self) -> None:
        """Forget any queued-but-not-yet-sent button press (used by Reset Sim)."""
        self._pending_op = {"start": False, "stop": False, "reset": False}

    def operator_start(self, feedback: PlantFeedback | None = None) -> None:
        # feedback is accepted for API symmetry but unused: this bridge
        # doesn't decide whether a start is allowed — the SoftPLC does. We
        # just queue the button press and let the PLC's permissive logic
        # (plc_logic.py) accept or reject it.
        del feedback  # permissives live in the SoftPLC
        self._pending_op["start"] = True
        self.state.last_message = "Start command sent to SoftPLC"

    def operator_stop(self) -> None:
        self._pending_op["stop"] = True
        self.state.last_message = "Stop command sent to SoftPLC"

    def operator_reset(self) -> None:
        self._pending_op["reset"] = True
        self.state.last_message = "Reset sent to SoftPLC"

    def step(self, feedback: PlantFeedback) -> PlantCommands:
        """One IO cycle: write plant inputs (+ any pending HMI pulse), wait one
        SoftPLC scan, read back PLC command coils, then clear the HMI pulse.

        This is the only method that actually talks to the network. Called
        once per Streamlit rerun from app.py, it plays the same role a real
        Modbus master/HMI polling loop would: write the world's current
        state in, give the controller a moment to react, read its decision
        back out.
        """
        if not self.ensure_connected():
            # No PLC reachable — return "do nothing" rather than raising, so
            # the UI can keep rendering (just showing a disconnected state).
            return PlantCommands()

        try:
            had_ops = any(self._pending_op.values())
            self._write_inputs(feedback, include_ops=True)
            time.sleep(SETTLE_S)  # give the SoftPLC at least one scan to react
            commands = self._read_commands()
            self.state.start_blocked = self._read_coil(COIL_START_BLOCKED)
            if self.state.start_blocked:
                self.state.last_message = (
                    "Start blocked — downstream valve not open (permissive fail)"
                )

            if had_ops:
                # We just sent a button press as a "1". If we left it there,
                # the SoftPLC would keep seeing op_start=1 on every future
                # scan and (depending on timing) could re-trigger edge
                # detection. So we immediately write it back to 0 — from the
                # PLC's point of view this looks like a normal brief button
                # press, exactly like a person releasing a physical button.
                self._pending_op = {"start": False, "stop": False, "reset": False}
                self._write_inputs(feedback, include_ops=True)

            self.state.connected = True
            return commands
        except Exception as exc:  # noqa: BLE001 — surface link errors in UI
            # Any Modbus/network failure lands here — e.g. soft_plc.py isn't
            # running, or it crashed mid-request. We drop the connection and
            # let the UI show "disconnected" instead of crashing the app.
            self.state.connected = False
            self.state.last_message = f"Modbus error: {exc}"
            self._client.close()
            return PlantCommands()

    def _write_inputs(self, feedback: PlantFeedback, *, include_ops: bool) -> None:
        """Push the plant's sensor values + HMI buttons into the PLC's inputs.

        These 7 values are written in one Modbus "write multiple holding
        registers" request rather than 7 separate ones, because io_map.py
        deliberately placed them at contiguous addresses starting at
        HR_PUMP_RUNNING — see io_map.py for why that ordering was chosen.
        """
        values = [
            1 if feedback.pump_running else 0,
            1 if feedback.pump_fault else 0,
            1 if feedback.disch_pressure_ok else 0,
            1 if feedback.downstream_valve_open else 0,
            1 if (include_ops and self._pending_op["start"]) else 0,
            1 if (include_ops and self._pending_op["stop"]) else 0,
            1 if (include_ops and self._pending_op["reset"]) else 0,
        ]
        result = self._client.write_registers(HR_PUMP_RUNNING, values)
        if result.isError():
            raise RuntimeError(f"write_registers failed: {result}")

    def _read_commands(self) -> PlantCommands:
        """Read the PLC's 3 command coils back in a single Modbus request."""
        result = self._client.read_coils(COIL_PUMP_START_CMD, count=3)
        if result.isError():
            raise RuntimeError(f"read_coils failed: {result}")
        bits = list(result.bits[:3])
        return PlantCommands(
            pump_start_cmd=bool(bits[0]),
            pump_stop_cmd=bool(bits[1]),
            pump_reset_cmd=bool(bits[2]),
        )

    def _read_coil(self, address: int) -> bool:
        """Read a single coil — used for START_BLOCKED, which isn't part of
        PlantCommands (it's an alarm for the HMI, not a plant command)."""
        result = self._client.read_coils(address, count=1)
        if result.isError():
            raise RuntimeError(f"read_coil({address}) failed: {result}")
        return bool(result.bits[0])
