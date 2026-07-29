"""Virtual IO map shared by MPSS and the SoftPLC (OpenPLC-compatible).

OpenPLC Runtime (Modbus TCP slave) maps:
  coils 0+              → %QX0.0+
  holding registers 1024+ → %MW0+

MPSS is the Modbus TCP *client*. The SoftPLC (Python or OpenPLC) is the *server*.
"""

from __future__ import annotations

# --- Holding registers written by MPSS (plant + HMI → PLC) ---
# OpenPLC: %MW0 .. %MW6  (Modbus HR address = 1024 + offset)
HR_BASE = 1024

HR_PUMP_RUNNING = HR_BASE + 0  # %MW0
HR_PUMP_FAULT = HR_BASE + 1  # %MW1s
HR_DISCH_PRESSURE_OK = HR_BASE + 2  # %MW2
HR_DOWNSTREAM_VALVE_OPEN = HR_BASE + 3  # %MW3
HR_OP_START = HR_BASE + 4  # %MW4  (HMI momentary)
HR_OP_STOP = HR_BASE + 5  # %MW5
HR_OP_RESET = HR_BASE + 6  # %MW6

# --- Coils written by PLC (PLC → plant / HMI) ---
# OpenPLC: %QX0.0 .. %QX0.3
COIL_PUMP_START_CMD = 0  # %QX0.0
COIL_PUMP_STOP_CMD = 1  # %QX0.1
COIL_PUMP_RESET_CMD = 2  # %QX0.2
COIL_START_BLOCKED = 3  # %QX0.3  (alarm latch to HMI)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5502  # avoid privileged port 502; OpenPLC often uses 502
