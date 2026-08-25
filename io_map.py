"""Shared Modbus map (OpenPLC-compatible).

  coils 0+                → %QX0.0+
  holding registers 1024+ → %MW0+

MPSS is the Modbus TCP client; the SoftPLC is the server.
"""

from __future__ import annotations

HR_BASE = 1024  # OpenPLC %MW0

HR_PUMP_RUNNING = HR_BASE + 0          # %MW0
HR_PUMP_FAULT = HR_BASE + 1            # %MW1
HR_DISCH_PRESSURE_OK = HR_BASE + 2     # %MW2
HR_DOWNSTREAM_VALVE_OPEN = HR_BASE + 3 # %MW3
HR_OP_START = HR_BASE + 4              # %MW4  (HMI momentary)
HR_OP_STOP = HR_BASE + 5               # %MW5
HR_OP_RESET = HR_BASE + 6              # %MW6

COIL_PUMP_START_CMD = 0  # %QX0.0
COIL_PUMP_STOP_CMD = 1   # %QX0.1
COIL_PUMP_RESET_CMD = 2  # %QX0.2
COIL_START_BLOCKED = 3   # %QX0.3  (alarm latch to HMI)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5502  # avoid privileged port 502
DEFAULT_LOGIX_PORT = 44818  # EtherNet/IP (display / docs only; pycomm3 uses CIP path)

DRIVER_MODBUS = "modbus"
DRIVER_LOGIX = "logix"

# Plant → PLC (same order as the 7 contiguous holding registers).
INPUT_SIGNALS = (
    "PUMP_RUNNING",
    "PUMP_FAULT",
    "DISCH_PRESSURE_OK",
    "DOWNSTREAM_VALVE_OPEN",
    "OP_START",
    "OP_STOP",
    "OP_RESET",
)

# PLC → plant / HMI (same order as coils 0–3).
OUTPUT_SIGNALS = (
    "PUMP_START_CMD",
    "PUMP_STOP_CMD",
    "PUMP_RESET_CMD",
    "START_BLOCKED",
)

# Controller-scoped BOOL tags. Override in the UI if the Logix program uses other names.
# Use standard (non-safety) tags on a GuardLogix 1756-L84ES.
DEFAULT_LOGIX_TAGS = {
    "PUMP_RUNNING": "MPSS_PUMP_RUNNING",
    "PUMP_FAULT": "MPSS_PUMP_FAULT",
    "DISCH_PRESSURE_OK": "MPSS_DISCH_PRESSURE_OK",
    "DOWNSTREAM_VALVE_OPEN": "MPSS_DOWNSTREAM_VALVE_OPEN",
    "OP_START": "MPSS_OP_START",
    "OP_STOP": "MPSS_OP_STOP",
    "OP_RESET": "MPSS_OP_RESET",
    "PUMP_START_CMD": "PLC_PUMP_START_CMD",
    "PUMP_STOP_CMD": "PLC_PUMP_STOP_CMD",
    "PUMP_RESET_CMD": "PLC_PUMP_RESET_CMD",
    "START_BLOCKED": "PLC_START_BLOCKED",
}
