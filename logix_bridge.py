"""EtherNet/IP client for Allen-Bradley Logix (GuardLogix / ControlLogix / CompactLogix).

Same plant/HMI contract as ModbusPlcBridge — only the wire protocol changes.
Tags must be controller-scoped BOOLs (standard tags on GuardLogix, not safety memory).
"""

from __future__ import annotations

import time

from io_map import (
    DEFAULT_LOGIX_PORT,
    DEFAULT_LOGIX_TAGS,
    INPUT_SIGNALS,
    OUTPUT_SIGNALS,
)
from plc_bridge import (
    CONNECT_BACKOFF_S,
    LOGIX_SETTLE_S,
    BridgeState,
    HmiPulseMixin,
)
from simulation import PlantCommands, PlantFeedback

try:
    from pycomm3 import LogixDriver
except ImportError:  # pragma: no cover — optional until pip install pycomm3
    LogixDriver = None


def build_logix_path(ip: str, slot: int = 0, cip_path: str = "") -> str:
    """CIP path for pycomm3.

    1756-L84ES embedded Ethernet: IP only (slot 0).
    ControlLogix via a 1756-ENxT in another slot: ``ip/slot``.
    Leave *cip_path* set to override both (full route as shown in Studio 5000).
    """
    custom = (cip_path or "").strip()
    if custom:
        return custom
    ip = (ip or "").strip()
    if not ip:
        return ""
    if int(slot) == 0:
        return ip
    return f"{ip}/{int(slot)}"


def _tag_bool(result) -> bool:
    if getattr(result, "error", None):
        raise RuntimeError(f"{result.tag}: {result.error}")
    return bool(result.value)


class LogixPlcBridge(HmiPulseMixin):
    """CIP originator: write plant/HMI tags, read command tags."""

    driver = "logix"

    def __init__(
        self,
        host: str,
        slot: int = 0,
        cip_path: str = "",
        tags: dict[str, str] | None = None,
    ) -> None:
        self.host = (host or "").strip()
        self.port = DEFAULT_LOGIX_PORT
        self.slot = int(slot)
        self.cip_path = (cip_path or "").strip()
        self.path = build_logix_path(self.host, self.slot, self.cip_path)
        self.tags = {**DEFAULT_LOGIX_TAGS, **(tags or {})}
        self.state = BridgeState()
        self._init_hmi_pulse()
        self._client = None
        self._enabled = False
        self._next_connect_at = 0.0

    @property
    def target_label(self) -> str:
        return f"Logix EIP @ {self.path or '(no path)'}"

    def empty_tag_names(self) -> list[str]:
        return [
            sig
            for sig in (*INPUT_SIGNALS, *OUTPUT_SIGNALS)
            if not str(self.tags.get(sig, "")).strip()
        ]

    def set_enabled(self, enabled: bool) -> None:
        """Explicit Connect/Disconnect. Disabled means no CIP and no tag writes."""
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self.close()
            self._next_connect_at = 0.0
            self.state.last_message = "Disconnected — click Connect to talk to the Logix"

    def config_key(self) -> tuple:
        return (
            "logix",
            self.host,
            self.slot,
            self.cip_path,
            tuple(self.tags.get(k, "") for k in (*INPUT_SIGNALS, *OUTPUT_SIGNALS)),
        )

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        self.state.connected = False

    def connect(self) -> bool:
        if LogixDriver is None:
            self.state.connected = False
            self.state.last_message = "pycomm3 is not installed — pip install pycomm3"
            return False
        if not self.path:
            self.state.connected = False
            self.state.last_message = "Enter the Logix IP address (or a CIP path)"
            return False
        blank = self.empty_tag_names()
        if blank:
            self.state.connected = False
            self.state.last_message = f"Empty tag name for: {', '.join(blank)}"
            return False
        try:
            if self._client is not None:
                self.close()
            self.state.last_message = (
                f"Connecting to Logix at {self.path} (tag list upload can take a few seconds)…"
            )
            self._client = LogixDriver(self.path)
            opened = bool(self._client.open())
            session_ok = bool(getattr(self._client, "connected", False))
            if not opened or not session_ok:
                self.state.connected = False
                self.state.last_message = f"Cannot reach Logix at {self.path}"
                self.close()
                return False
            self.state.connected = True
            self.state.last_message = f"Connected to Logix at {self.path}"
            return True
        except Exception as exc:  # noqa: BLE001
            self.state.connected = False
            self.state.last_message = f"Logix connect error: {exc}"
            self.close()
            return False

    def ensure_connected(self) -> bool:
        if not self._enabled:
            return False
        if self._client is not None and getattr(self._client, "connected", False):
            self.state.connected = True
            return True
        now = time.monotonic()
        if now < self._next_connect_at:
            return False
        ok = self.connect()
        if not ok:
            self._next_connect_at = time.monotonic() + CONNECT_BACKOFF_S
        else:
            self._next_connect_at = 0.0
        return ok

    def step(self, feedback: PlantFeedback) -> PlantCommands:
        if not self._enabled:
            self.state.connected = False
            if not self.path:
                self.state.last_message = "Enter the Logix IP address, then click Connect"
            elif self.empty_tag_names():
                self.state.last_message = (
                    f"Empty tag name for: {', '.join(self.empty_tag_names())}"
                )
            else:
                self.state.last_message = (
                    "Click Connect when ready to write tags to this Logix"
                )
            return PlantCommands()

        blank = self.empty_tag_names()
        if blank:
            self.state.connected = False
            self.state.last_message = f"Empty tag name for: {', '.join(blank)}"
            return PlantCommands()

        if not self.ensure_connected():
            return PlantCommands()

        try:
            written = self._write_inputs(feedback)
            self.state.holding_registers = [
                (self.tags[name], name, value) for name, value in written
            ]
            self._note_ops_sent()

            time.sleep(LOGIX_SETTLE_S)
            commands, start_blocked = self._read_outputs()
            self.state.start_blocked = start_blocked
            self.state.coils = [
                (self.tags[name], name, int(val))
                for name, val in (
                    ("PUMP_START_CMD", commands.pump_start_cmd),
                    ("PUMP_STOP_CMD", commands.pump_stop_cmd),
                    ("PUMP_RESET_CMD", commands.pump_reset_cmd),
                    ("START_BLOCKED", start_blocked),
                )
            ]
            self.state.last_io_at = time.time()
            if start_blocked:
                self.state.last_message = (
                    "Start blocked — PLC rejected the start (check permissives)"
                )

            self.state.connected = True
            return commands
        except Exception as exc:  # noqa: BLE001
            self.state.connected = False
            self.state.last_message = f"EtherNet/IP error: {exc}"
            self.close()
            self._next_connect_at = time.monotonic() + CONNECT_BACKOFF_S
            return PlantCommands()

    def _write_inputs(self, feedback: PlantFeedback) -> list[tuple[str, int]]:
        ops = self._op_bits()
        values = {
            "PUMP_RUNNING": int(feedback.pump_running),
            "PUMP_FAULT": int(feedback.pump_fault),
            "DISCH_PRESSURE_OK": int(feedback.disch_pressure_ok),
            "DOWNSTREAM_VALVE_OPEN": int(feedback.downstream_valve_open),
            "OP_START": int(ops["start"]),
            "OP_STOP": int(ops["stop"]),
            "OP_RESET": int(ops["reset"]),
        }
        pairs = tuple((self.tags[name], bool(values[name])) for name in INPUT_SIGNALS)
        result = self._client.write(*pairs)
        self._raise_if_write_failed(result)
        return [(name, values[name]) for name in INPUT_SIGNALS]

    def _read_outputs(self) -> tuple[PlantCommands, bool]:
        names = list(OUTPUT_SIGNALS)
        result = self._client.read(*(self.tags[n] for n in names))
        if not isinstance(result, list):
            result = [result]
        bits = [_tag_bool(item) for item in result]
        commands = PlantCommands(
            pump_start_cmd=bits[0],
            pump_stop_cmd=bits[1],
            pump_reset_cmd=bits[2],
        )
        return commands, bits[3]

    @staticmethod
    def _raise_if_write_failed(result) -> None:
        items = result if isinstance(result, list) else [result]
        errors = [item for item in items if getattr(item, "error", None)]
        if errors:
            first = errors[0]
            raise RuntimeError(f"{first.tag}: {first.error}")
