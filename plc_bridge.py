"""Modbus TCP client: MPSS writes plant/HMI into the SoftPLC and reads commands.

This module is deliberately dumb — no pump, valve, or permissive knowledge.
The SoftPLC (soft_plc.py + plc_logic.py) makes the decisions. The same client
would talk to a real PLC the same way.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pymodbus.client import ModbusTcpClient

from io_map import (
    DEFAULT_HOST,
    DEFAULT_LOGIX_TAGS,
    DEFAULT_PORT,
    DRIVER_LOGIX,
    DRIVER_MODBUS,
    HR_BASE,
    INPUT_SIGNALS,
    OUTPUT_SIGNALS,
)
from simulation import PlantCommands, PlantFeedback

# SoftPLC scan is 50 ms; wait longer so we never read outputs from the previous scan.
SETTLE_S = 0.1
# Keep HMI Start/Stop/Reset TRUE long enough for a typical Logix periodic task.
OP_HOLD_S = 0.5
# After a failed Logix open/tag-upload, wait before trying again (avoids freezing the UI).
CONNECT_BACKOFF_S = 3.0
# Extra wait after a Logix write so a 100–200 ms task can produce command bits.
LOGIX_SETTLE_S = 0.2

_HR_NAMES = list(INPUT_SIGNALS)
_COIL_NAMES = list(OUTPUT_SIGNALS)


@dataclass
class BridgeState:
    """Link status plus the raw register/coil snapshot shown in the live IO panel."""

    start_blocked: bool = False
    last_message: str = "Not connected to SoftPLC"
    connected: bool = False
    last_io_at: float = 0.0
    holding_registers: list[tuple[str, str, int]] = field(default_factory=list)
    coils: list[tuple[str, str, int]] = field(default_factory=list)


class HmiPulseMixin:
    """Momentary HMI buttons held for OP_HOLD_S so a slow PLC scan cannot miss them."""

    def _init_hmi_pulse(self) -> None:
        self._pending_op = {"start": False, "stop": False, "reset": False}
        self._op_until = {"start": 0.0, "stop": 0.0, "reset": 0.0}

    def reset_logic(self) -> None:
        self._init_hmi_pulse()

    def _arm_op(self, name: str, message: str) -> None:
        self._pending_op[name] = True
        self._op_until[name] = time.monotonic() + OP_HOLD_S
        self.state.last_message = message

    def operator_start(self) -> None:
        self._arm_op("start", "Start command sent to PLC")

    def operator_stop(self) -> None:
        self._arm_op("stop", "Stop command sent to PLC")

    def operator_reset(self) -> None:
        self._arm_op("reset", "Reset sent to PLC")

    def _op_bits(self) -> dict[str, bool]:
        now = time.monotonic()
        return {
            name: bool(self._pending_op[name] or now < self._op_until[name])
            for name in self._pending_op
        }

    def has_held_ops(self) -> bool:
        return any(self._op_bits().values())

    def _note_ops_sent(self) -> None:
        """Clear the one-shot flags; wall-clock hold still keeps the bits TRUE."""
        self._pending_op = {"start": False, "stop": False, "reset": False}


@dataclass(frozen=True)
class PlcTarget:
    """User-supplied connection data from the sidebar."""

    driver: str = DRIVER_MODBUS
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    hr_base: int = HR_BASE
    coil_base: int = 0
    slot: int = 0
    cip_path: str = ""
    tags: tuple[tuple[str, str], ...] = ()

    def key(self) -> tuple:
        return (
            self.driver,
            self.host,
            self.port,
            self.hr_base,
            self.coil_base,
            self.slot,
            self.cip_path,
            self.tags,
        )

    def tag_map(self) -> dict[str, str]:
        return {**DEFAULT_LOGIX_TAGS, **dict(self.tags)}


def create_bridge(target: PlcTarget):
    """Build the client for the selected driver. SoftPLC remains the default."""
    if target.driver == DRIVER_LOGIX:
        from logix_bridge import LogixPlcBridge

        return LogixPlcBridge(
            host=target.host,
            slot=target.slot,
            cip_path=target.cip_path,
            tags=target.tag_map(),
        )
    return ModbusPlcBridge(
        host=target.host,
        port=target.port,
        hr_base=target.hr_base,
        coil_base=target.coil_base,
    )


class ModbusPlcBridge(HmiPulseMixin):
    """Modbus master: we initiate every read/write; the SoftPLC only responds."""

    driver = DRIVER_MODBUS

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        hr_base: int = HR_BASE,
        coil_base: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self.hr_base = int(hr_base)
        self.coil_base = int(coil_base)
        self.state = BridgeState()
        self._client = ModbusTcpClient(host=host, port=port, timeout=0.5)
        self._init_hmi_pulse()

    @property
    def target_label(self) -> str:
        return f"Modbus TCP @ {self.host}:{self.port}"

    def config_key(self) -> tuple:
        return ("modbus", self.host, self.port, self.hr_base, self.coil_base)

    def close(self) -> None:
        self._client.close()
        self.state.connected = False

    def connect(self) -> bool:
        ok = bool(self._client.connect())
        self.state.connected = ok
        if ok:
            self.state.last_message = f"Connected to Modbus TCP at {self.host}:{self.port}"
        else:
            self.state.last_message = (
                f"Cannot reach Modbus TCP at {self.host}:{self.port} — "
                "check host/port (start soft_plc.py for the bundled SoftPLC)"
            )
        return ok

    def ensure_connected(self) -> bool:
        if self._client.connected:
            self.state.connected = True
            return True
        return self.connect()

    def step(self, feedback: PlantFeedback) -> PlantCommands:
        """Write plant + HMI → wait one scan → read PLC coils."""
        if not self.ensure_connected():
            return PlantCommands()

        try:
            values = self._write_inputs(feedback)
            # Snapshot while the HMI pulse is still high so the live IO panel shows it.
            self.state.holding_registers = [
                (str(self.hr_base + i), name, value)
                for i, (name, value) in enumerate(zip(_HR_NAMES, values))
            ]
            self._note_ops_sent()

            time.sleep(SETTLE_S)
            commands, start_blocked = self._read_coils()
            self.state.start_blocked = start_blocked
            self.state.coils = [
                (str(self.coil_base + i), name, int(val))
                for i, (name, val) in enumerate(
                    zip(
                        _COIL_NAMES,
                        (
                            commands.pump_start_cmd,
                            commands.pump_stop_cmd,
                            commands.pump_reset_cmd,
                            start_blocked,
                        ),
                    )
                )
            ]
            self.state.last_io_at = time.time()
            if start_blocked:
                self.state.last_message = (
                    "Start blocked — PLC rejected the start (check permissives)"
                )

            self.state.connected = True
            return commands
        except Exception as exc:  # noqa: BLE001 — show link errors in the UI
            self.state.connected = False
            self.state.last_message = f"Modbus error: {exc}"
            self._client.close()
            return PlantCommands()

    def _write_inputs(self, feedback: PlantFeedback) -> list[int]:
        ops = self._op_bits()
        values = [
            int(feedback.pump_running),
            int(feedback.pump_fault),
            int(feedback.disch_pressure_ok),
            int(feedback.downstream_valve_open),
            int(ops["start"]),
            int(ops["stop"]),
            int(ops["reset"]),
        ]
        result = self._client.write_registers(self.hr_base, values)
        if result.isError():
            raise RuntimeError(f"write_registers failed: {result}")
        return values

    def _read_coils(self) -> tuple[PlantCommands, bool]:
        result = self._client.read_coils(self.coil_base, count=4)
        if result.isError():
            raise RuntimeError(f"read_coils failed: {result}")
        bits = [bool(b) for b in result.bits[:4]]
        commands = PlantCommands(
            pump_start_cmd=bits[0],
            pump_stop_cmd=bits[1],
            pump_reset_cmd=bits[2],
        )
        return commands, bits[3]
