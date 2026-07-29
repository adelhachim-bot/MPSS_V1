"""Free SoftPLC for the MPSS pilot (Modbus TCP server + FDS permissive logic).

Run this *before* the Streamlit app:

    python soft_plc.py

Uses the same Modbus map as OpenPLC (%MW / %QX), so you can later swap this
process for OpenPLC Runtime without changing MPSS.

Big picture: this file's job is to make plc_logic.py's decisions reachable
over the network, and to keep calling it forever on a fixed clock — exactly
what a real PLC's firmware does for whatever program you've downloaded to it.
It has two moving parts that run at the same time (see `serve()`):
  - a Modbus TCP *server* thread (from pymodbus) that answers read/write
    requests from MPSS, and
  - a *scan loop* thread that repeatedly reads inputs, runs the logic, and
    writes outputs — this is the actual "PLC scanning" behaviour.
Both threads share one in-memory table (`self.device`), which is exactly
what "holding registers" and "coils" are: an implicit shared address space
that a network client (MPSS) never sees directly — it only sees the values
in it through Modbus read/write requests.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartTcpServer

from io_map import (
    COIL_PUMP_START_CMD,
    DEFAULT_HOST,
    DEFAULT_PORT,
    HR_DISCH_PRESSURE_OK,
    HR_DOWNSTREAM_VALVE_OPEN,
    HR_OP_RESET,
    HR_OP_START,
    HR_OP_STOP,
    HR_PUMP_FAULT,
    HR_PUMP_RUNNING,
)
from plc_logic import PlcInputs, SumpPumpPlcLogic

log = logging.getLogger("soft_plc")

# pymodbus identifies which "table" (coils vs holding registers, etc.) a
# read/write applies to by a Modbus function code, not by name. 1 = coils,
# 3 = holding registers — these are Modbus protocol constants, not MPSS's.
_FC_COIL = 1
_FC_HR = 3


class SoftPlcRuntime:
    """A minimal stand-in for a real PLC: Modbus TCP server + scan loop."""

    def __init__(self, host: str, port: int, scan_s: float = 0.05) -> None:
        self.host = host
        self.port = port
        self.scan_s = scan_s  # scan period in seconds — how "fast" this PLC runs
        self.logic = SumpPumpPlcLogic()

        # This is the PLC's entire memory: four Modbus data tables, each a
        # flat array of values. MPSS only ever touches `co` (coils, PLC's
        # outputs) and `hr` (holding registers, PLC's inputs) — `di` and
        # `ir` exist because pymodbus requires all four but MPSS ignores them.
        # Address space large enough for OpenPLC-style %MW base at 1024.
        self.device = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * 100),
            co=ModbusSequentialDataBlock(0, [0] * 100),
            hr=ModbusSequentialDataBlock(0, [0] * 2048),
            ir=ModbusSequentialDataBlock(0, [0] * 100),
            zero_mode=True,  # addresses are used exactly as given, no +1 offset
        )
        # A Modbus server can technically host multiple "slave" devices;
        # `single=True` means "there's only one PLC here," which is all a
        # a Pilot needs.
        self.context = ModbusServerContext(slaves=self.device, single=True)
        # Lets serve() signal the scan-loop thread to stop cleanly on shutdown.
        self._stop = threading.Event()

    def _hr(self, address: int) -> int:
        """Read one holding register directly from memory (no network hop —
        the scan loop and the Modbus server share the same process)."""
        return int(self.device.getValues(_FC_HR, address, 1)[0])

    def _set_coils(self, start: bool, stop: bool, reset: bool, blocked: bool) -> None:
        """Write the PLC's decision into its four output coils in one call.

        These four are contiguous (coils 0-3, see io_map.py), so pymodbus
        can set all of them with a single setValues call, starting at the
        first coil's address.
        """
        self.device.setValues(
            _FC_COIL,
            COIL_PUMP_START_CMD,
            [
                1 if start else 0,
                1 if stop else 0,
                1 if reset else 0,
                1 if blocked else 0,
            ],
        )

    def _read_inputs(self) -> PlcInputs:
        """Gather this scan's inputs from the holding registers MPSS writes to.

        Modbus registers only store raw integers, so "!= 0" is how a 0/1
        integer gets turned back into the boolean plc_logic.py expects.
        """
        return PlcInputs(
            pump_running=self._hr(HR_PUMP_RUNNING) != 0,
            pump_fault=self._hr(HR_PUMP_FAULT) != 0,
            disch_pressure_ok=self._hr(HR_DISCH_PRESSURE_OK) != 0,
            downstream_valve_open=self._hr(HR_DOWNSTREAM_VALVE_OPEN) != 0,
            op_start=self._hr(HR_OP_START) != 0,
            op_stop=self._hr(HR_OP_STOP) != 0,
            op_reset=self._hr(HR_OP_RESET) != 0,
        )

    def scan_loop(self) -> None:
        """The actual "PLC scan": read → decide → write → wait, forever.

        This is the loop that makes this a PLC rather than just a Modbus
        data store. It runs on its own background thread so it can tick on
        a fixed clock independently of whenever a network client happens to
        connect and poll — a real PLC's scan doesn't wait for anyone either.
        """
        log.info("SoftPLC scan loop started (%.0f ms)", self.scan_s * 1000)
        while not self._stop.is_set():
            inputs = self._read_inputs()
            outputs = self.logic.scan(inputs)  # run the control program once
            self._set_coils(
                outputs.pump_start_cmd,
                outputs.pump_stop_cmd,
                outputs.pump_reset_cmd,
                outputs.start_blocked,
            )
            time.sleep(self.scan_s)

    def serve(self) -> None:
        """Start the scan loop in the background, then block serving Modbus TCP.

        `StartTcpServer` is what actually opens the network socket and
        answers MPSS's read/write requests — it never returns until the
        process is stopped, which is why the scan loop has to run on its
        own thread rather than after this call.
        """
        scanner = threading.Thread(target=self.scan_loop, name="plc-scan", daemon=True)
        scanner.start()
        log.info("SoftPLC listening on %s:%s (Modbus TCP)", self.host, self.port)
        try:
            StartTcpServer(context=self.context, address=(self.host, self.port))
        finally:
            self._stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="MPSS free SoftPLC (Modbus TCP)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--scan-ms", type=float, default=50.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    SoftPlcRuntime(args.host, args.port, scan_s=args.scan_ms / 1000.0).serve()


if __name__ == "__main__":
    main()
