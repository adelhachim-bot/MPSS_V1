"""SoftPLC: Modbus TCP server + scan loop running plc_logic.py.

Start this before the Streamlit app:

    python soft_plc.py

Same address map as OpenPLC (%MW / %QX), so this process can later be swapped
for a real runtime without changing MPSS.
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
    HR_PUMP_RUNNING,
)
from plc_logic import PlcInputs, SumpPumpPlcLogic

log = logging.getLogger("soft_plc")

# pymodbus table ids: 1 = coils, 3 = holding registers.
_FC_COIL = 1
_FC_HR = 3


class SoftPlcRuntime:
    """Modbus TCP server plus a background scan: read → logic → write → sleep."""

    def __init__(self, host: str, port: int, scan_s: float = 0.05) -> None:
        self.host = host
        self.port = port
        self.scan_s = scan_s
        self.logic = SumpPumpPlcLogic()
        # di/ir exist because pymodbus requires all four tables; MPSS only uses co + hr.
        self.device = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * 100),
            co=ModbusSequentialDataBlock(0, [0] * 100),
            hr=ModbusSequentialDataBlock(0, [0] * 2048),
            ir=ModbusSequentialDataBlock(0, [0] * 100),
            zero_mode=True,  # use addresses as given (no +1 offset)
        )
        self.context = ModbusServerContext(slaves=self.device, single=True)
        self._stop = threading.Event()

    def _read_inputs(self) -> PlcInputs:
        vals = self.device.getValues(_FC_HR, HR_PUMP_RUNNING, 7)
        bits = [v != 0 for v in vals]
        return PlcInputs(
            pump_running=bits[0],
            pump_fault=bits[1],
            disch_pressure_ok=bits[2],
            downstream_valve_open=bits[3],
            op_start=bits[4],
            op_stop=bits[5],
            op_reset=bits[6],
        )

    def _write_outputs(self, start: bool, stop: bool, reset: bool, blocked: bool) -> None:
        self.device.setValues(
            _FC_COIL,
            COIL_PUMP_START_CMD,
            [int(start), int(stop), int(reset), int(blocked)],
        )

    def scan_loop(self) -> None:
        log.info("SoftPLC scan loop started (%.0f ms)", self.scan_s * 1000)
        while not self._stop.is_set():
            out = self.logic.scan(self._read_inputs())
            self._write_outputs(
                out.pump_start_cmd,
                out.pump_stop_cmd,
                out.pump_reset_cmd,
                out.start_blocked,
            )
            time.sleep(self.scan_s)

    def serve(self) -> None:
        # Scan must run on its own thread: StartTcpServer blocks forever.
        threading.Thread(target=self.scan_loop, name="plc-scan", daemon=True).start()
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
