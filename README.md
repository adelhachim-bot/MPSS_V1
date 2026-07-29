# MPSS Pilot Demo

Mining Process Simulation Sandbox — sump pump pilot (FDS Appendix A).

## Architecture

```
Streamlit UI (app.py + ui.py)
    │  operator Start/Stop/Reset + fault injection
    ▼
Virtual plant (simulation.py)     ←── MPSS responsibility
    │
Modbus TCP client (plc_bridge.py)
    │
SoftPLC Modbus TCP server (soft_plc.py)  ←── control logic (black box)
    runs plc_logic.py
```

The SoftPLC owns start permissives. MPSS owns plant behaviour and fault injection.
It is a real, separate process reached over Modbus TCP — not an in-process shortcut.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — SoftPLC
python soft_plc.py

# Terminal 2 — UI
streamlit run app.py
```

Default link: `127.0.0.1:5502` (sidebar can change host/port). The SoftPLC must be
running before the UI can connect.

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
