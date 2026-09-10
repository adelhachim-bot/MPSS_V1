# MPSS Pilot Demo

Mining Process Simulation Sandbox — sump pump pilot (FDS Appendix A).

Full walkthrough (install, run, UI, demo script, troubleshooting): **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

## Architecture

```
Streamlit UI (app.py + ui.py)
    │  operator Start/Stop/Reset + fault injection
    ▼
Virtual plant (simulation.py)     ←── MPSS responsibility
    │
    ├─ Modbus TCP (plc_bridge.py) ── SoftPLC / other Modbus PLC
    └─ EtherNet/IP (logix_bridge.py) ── GuardLogix / ControlLogix / CompactLogix
```

The PLC owns start permissives. MPSS owns plant behaviour and fault injection.
Default demo: bundled SoftPLC over Modbus TCP. Optional: a real Logix over EtherNet/IP (sidebar).

## Quick start (Windows)

Install [Python 3.10+](https://www.python.org/downloads/) and tick **Add python.exe to PATH**. Unzip the project (do not copy a `.venv` from another PC).

Double-click **`run.bat`**. The first run creates `.venv` and installs packages. After that it starts the SoftPLC and the UI (`http://localhost:8501`).

Allow Python in Windows Firewall if prompted. Close the Streamlit window to stop the UI; close the **MPSS SoftPLC** window to stop the SoftPLC.

For a real GuardLogix, use the same `run.bat`, then in the sidebar choose EtherNet/IP, enter the PLC IP, and click **Connect**.

## Demo scenarios

Same as FDS Appendix A:

1. **Normal** — valve open → Start → ~4s → RUNNING + pressure OK
2. **Fault** — close valve → Start → start blocked, pump stays stopped
3. **Recovery** — open valve → Reset → Start → RUNNING
4. **Optional** — Inject pump trip while RUNNING → FAULT

## Modbus IO map

| Signal | Direction | Modbus |
|--------|-----------|--------|
| PUMP_RUNNING | MPSS → PLC | HR 1024 |
| PUMP_FAULT | MPSS → PLC | HR 1025 |
| DISCH_PRESSURE_OK | MPSS → PLC | HR 1026 |
| DOWNSTREAM_VALVE_OPEN | MPSS → PLC | HR 1027 |
| OP_START / STOP / RESET | MPSS → PLC | HR 1028–1030 |
| PUMP_START_CMD | PLC → MPSS | Coil 0 |
| PUMP_STOP_CMD | PLC → MPSS | Coil 1 |
| PUMP_RESET_CMD | PLC → MPSS | Coil 2 |
| START_BLOCKED | PLC → MPSS | Coil 3 |

The mapping is intentionally hardcoded in `io_map.py` (acceptable for the Pilot per
the FDS).

## Limitations and assumptions

- Single process module (sump pump), single PLC platform (the bundled Python
  SoftPLC), as scoped by the FDS. No multi-PLC, SCADA/HMI, or physics-accurate
  modelling.
- `soft_plc.py` is a lightweight Python Modbus TCP server, not a certified PLC
  runtime — it demonstrates the PLC-in-the-loop pattern (external process,
  scan loop, real permissive logic) but isn't a substitute for validating
  against a production PLC platform.
- Timing is wall-clock based (not a fixed-step simulation), which is sufficient
  for logical realism but not for real-time-accurate testing.
- The Modbus link blocks the UI briefly (~100 ms) on each poll/command while it
  waits for a SoftPLC scan — acceptable for a demo, not tuned for throughput.

## Tests

```bash
pytest -q
```
