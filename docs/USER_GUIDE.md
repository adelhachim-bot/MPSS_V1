# MPSS Pilot — User Guide

Mining Process Simulation Sandbox (MPSS) is a demo of a **virtual sump-pump station** with a **PLC in the loop**.

The plant (pump, valve, pressure) is simulated in Python. Start / stop / reset decisions are made by a **separate PLC**, reached over the network. MPSS does **not** decide whether a start is allowed.

Default demo PLC: bundled Python SoftPLC over **Modbus TCP**. Optional: a real Logix controller (GuardLogix / ControlLogix / CompactLogix) over **EtherNet/IP**.

---

## 1. What you need

- Python 3.10+ (3.11 or 3.12 recommended)
- Two terminal windows
- A browser (Streamlit opens one automatically)

No hardware PLC is required. The bundled SoftPLC is a Python Modbus TCP server.

---

## 2. Install

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

That installs Streamlit, pymodbus, pycomm3, and pytest.

---

## 3. Run the demo

**The SoftPLC must be running before the UI can connect.** Use two terminals, both with the venv activated.

### Terminal 1 — SoftPLC

```bash
python soft_plc.py
```

You should see a log line similar to:

```
SoftPLC listening on 127.0.0.1:5502 (Modbus TCP)
```

Leave this terminal running. Optional flags:

```bash
python soft_plc.py --host 127.0.0.1 --port 5502 --scan-ms 50
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `5502` | Modbus TCP port (5502 avoids privileged port 502) |
| `--scan-ms` | `50` | PLC scan period in milliseconds |

### Terminal 2 — HMI

```bash
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`).

The header should show a green **Modbus TCP @ 127.0.0.1:5502**. If it is red, the UI cannot reach the SoftPLC — start `soft_plc.py` first, then confirm host/port in the sidebar match.

---

## 4. How the application is structured

```
Streamlit UI (app.py + ui.py)
    │  operator Start / Stop / Reset + fault injection
    ▼
Virtual plant (simulation.py)          ← MPSS: equipment behaviour
    │
    ├─ Modbus TCP (plc_bridge.py) ── SoftPLC / OpenPLC / other Modbus PLC
    └─ EtherNet/IP (logix_bridge.py) ── GuardLogix / ControlLogix / CompactLogix
```

| Piece | Owns | Does not own |
|--------|------|----------------|
| **Virtual plant** | Motor spin-up, pressure rise, valve position, pump trip | Whether a start is allowed |
| **PLC (SoftPLC or hardware)** | Start permissives, latched “start blocked” alarm, command pulses | Plant physics / fault injection |
| **Streamlit UI** | HMI buttons, scenario controls, live picture | Permissive decisions |

The PLC is a **real separate process** (or hardware), not an in-process shortcut. The Modbus map is OpenPLC-compatible (`%MW` / `%QX`). Logix uses the same 11 signals as named BOOL tags.

### One cycle (each UI refresh)

1. MPSS writes plant sensors and any pending HMI button into **holding registers** HR 1024–1030.
2. It waits **100 ms** so the SoftPLC can complete at least one **scan**.
3. It reads PLC **coils** (start / stop / reset commands + start-blocked alarm).
4. The plant applies those commands and advances wall-clock time (startup delay, pressure rise).

The SoftPLC scan loop (every **50 ms**) is: read inputs → run `SumpPumpPlcLogic.scan()` → write outputs. That is the same read–decide–write pattern a real PLC uses.

HMI buttons are **momentary**. MPSS writes `1` for one poll, then writes `0`, so the PLC sees a press-and-release, not a stuck button. The PLC only acts on the **rising edge**, and holds each command coil true for ~6 scans (~300 ms) so a slower client cannot miss the pulse.

---

## 5. Using the UI

### Sidebar

- **PLC driver** — Modbus TCP (bundled SoftPLC or any Modbus PLC) or EtherNet/IP (Logix).
- **Modbus host / port** — default `127.0.0.1:5502` for `soft_plc.py`. Expand **Modbus addresses** if the PLC does not use HR 1024 / coil 0.
- **Logix IP / slot / CIP path / tag names** — shown when EtherNet/IP is selected. Click **Connect** before MPSS writes tags. See [Connecting a real PLC](#14-connecting-a-real-plc).
- **Auto-refresh live IO** — keep polling while idle so the live IO panel updates. Refresh also stays on during STARTING and while discharge pressure is still rising.

### Process mimic

Live picture of the station: sump → pump → pressure transmitter → isolation valve → downstream process.

| Appearance | Meaning |
|------------|---------|
| Green pump, blue pipe | Flowing (running + valve open) |
| Amber pump | STARTING |
| Red pump | FAULT |
| Valve green / red | OPEN / CLOSED |

### Operator commands (HMI → PLC)

These go to the SoftPLC. Permissives are enforced **there**, not in the UI.

| Button | Effect |
|--------|--------|
| **START** | Request a start. Accepted only if the valve is open and there is no fault / start-blocked alarm. |
| **STOP** | Stop immediately (cancels a start in progress). Always allowed. |
| **RESET** | Clear the start-blocked latch. Always allowed. |

### Fault injection (MPSS — not PLC actions)

These change the **plant**, then the new sensor values are written to the PLC on the next poll.

| Control | Effect |
|---------|--------|
| **Downstream isolation valve OPEN** | Sets `DOWNSTREAM_VALVE_OPEN`. Close it to fail the start permissive. |
| **INJECT TRIP** | Forces `PUMP_FAULT` and stops the pump. |
| **RESET SIM** | Returns plant **and** pending HMI commands to the initial demo state (stopped, valve open, no faults), then sends Reset to the PLC. |

### Live Modbus IO

The expander at the bottom is a raw register/coil dump — the same bits on the wire, not the interpreted lamps above.

- Left: **MPSS → PLC** holding registers (HR 1024–1030)
- Right: **PLC → MPSS** coils (0–3)

A Start / Stop / Reset press shows as `1` on that poll, then returns to `0`.

---

## 6. Plant behaviour

The plant is a **state machine**, not a physics model. Status is one of:

| Status | Meaning |
|--------|---------|
| **STOPPED** | Pump off; discharge pressure not OK |
| **STARTING** | Start accepted; ~4 s spin-up before `PUMP_RUNNING` |
| **RUNNING** | Motor on; discharge pressure OK ~1 s later |
| **FAULT** | Trip injected; pump dropped offline |

If the PLC issues a start command, the pump starts (unless already faulted). If the PLC refuses, the plant stays stopped.

---

## 7. PLC logic (permissives)

Rules in `plc_logic.py`:

- **Start** is allowed only if the downstream valve is open and the pump is not faulted.
- Start with the valve closed **latches** `START_BLOCKED`. Opening the valve later does **not** clear it. Press **Reset**, then **Start** again.
- **Stop** and **Reset** always work; no permissives.

That latch is the interlock the demo is meant to show.

---

## 8. Demo script (FDS Appendix A)

Start from a clean state. Use **RESET SIM** if the station is not at STOPPED with the valve open.

### 1. Normal start

1. Confirm the isolation valve is **OPEN**.
2. Press **START**.
3. Status goes **STARTING** for ~4 seconds.
4. Status becomes **RUNNING**; ~1 second later **DISCH_PRESSURE_OK** turns true.

### 2. Fault — start blocked

1. Press **RESET SIM**.
2. Turn **Downstream isolation valve OPEN** off (valve closed).
3. Press **START**.
4. The message shows start blocked; the pump stays **STOPPED**. Coil `START_BLOCKED` is 1.

### 3. Recovery

1. Open the valve again.
2. Press **RESET** (clears the latch). Opening the valve alone is not enough.
3. Press **START**.
4. The pump goes **RUNNING** as in scenario 1.

### 4. Optional — pump trip

1. With the pump **RUNNING**, press **INJECT TRIP**.
2. Status becomes **FAULT**; the pump stops.

---

## 9. Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Red header: cannot reach SoftPLC | Terminal 1 is running `python soft_plc.py`. Host/port in the sidebar match (`127.0.0.1` / `5502`). |
| `Address already in use` on SoftPLC start | Another `soft_plc.py` is still running, or port 5502 is taken. Stop the old process, or use `--port` and set the same port in the UI. |
| Start does nothing after closing then opening the valve | The start-blocked alarm is still latched. Press **RESET**, then **START**. |
| Live IO panel looks frozen | Turn **Auto-refresh Modbus IO** on in the sidebar. |
| Buttons work but plant never reaches RUNNING | Wait the full ~4 s startup delay. Confirm SoftPLC is connected so start commands actually arrive. |

---

## 10. Modbus IO map

Hardcoded in `io_map.py` (acceptable for the Pilot).

| Signal | Direction | Modbus | Default Logix tag |
|--------|-----------|--------|-------------------|
| PUMP_RUNNING | MPSS → PLC | HR 1024 | `MPSS_PUMP_RUNNING` |
| PUMP_FAULT | MPSS → PLC | HR 1025 | `MPSS_PUMP_FAULT` |
| DISCH_PRESSURE_OK | MPSS → PLC | HR 1026 | `MPSS_DISCH_PRESSURE_OK` |
| DOWNSTREAM_VALVE_OPEN | MPSS → PLC | HR 1027 | `MPSS_DOWNSTREAM_VALVE_OPEN` |
| OP_START | MPSS → PLC | HR 1028 | `MPSS_OP_START` |
| OP_STOP | MPSS → PLC | HR 1029 | `MPSS_OP_STOP` |
| OP_RESET | MPSS → PLC | HR 1030 | `MPSS_OP_RESET` |
| PUMP_START_CMD | PLC → MPSS | Coil 0 | `PLC_PUMP_START_CMD` |
| PUMP_STOP_CMD | PLC → MPSS | Coil 1 | `PLC_PUMP_STOP_CMD` |
| PUMP_RESET_CMD | PLC → MPSS | Coil 2 | `PLC_PUMP_RESET_CMD` |
| START_BLOCKED | PLC → MPSS | Coil 3 | `PLC_START_BLOCKED` |

---

## 11. Source map

| File | Role |
|------|------|
| `app.py` | Streamlit loop: poll PLC, tick plant, handle buttons |
| `ui.py` | HMI layout, mimic, lamps, live IO panel |
| `simulation.py` | Virtual plant state machine |
| `plc_bridge.py` | Modbus TCP client (IO only — no permissives) |
| `logix_bridge.py` | EtherNet/IP client for Logix (GuardLogix / ControlLogix / CompactLogix) |
| `soft_plc.py` | Modbus TCP server + 50 ms scan loop |
| `plc_logic.py` | Permissive program the SoftPLC executes |
| `io_map.py` | Shared signal names, Modbus addresses, default Logix tags |

---

## 12. Tests

From the project root, with the venv activated:

```bash
pytest -q
```

| File | Covers |
|------|--------|
| `test_plc_logic.py` | Permissives, no network |
| `test_simulation.py` | Plant timing and fault injection |
| `test_modbus_softplc.py` | Real Modbus against a spawned SoftPLC |
| `test_logix_bridge.py` | CIP path helper and bridge factory (no hardware) |

---

## 13. Limitations

- One process module (sump pump). PLC drivers today: Modbus TCP and Logix EtherNet/IP (not Siemens S7, Mitsubishi, etc.).
- `soft_plc.py` is a lightweight demo runtime, not a certified PLC.
- A GuardLogix test must use **standard** tags, not safety-memory tags. This is PLC-in-the-loop for logic, not a SIL validation of the safety task.
- Timing is wall-clock, not a fixed-step real-time simulation.
- Each poll blocks the UI ~100 ms waiting for a scan — fine for a demo, not for high throughput.
- No multi-PLC, SCADA, or physics-accurate flow/pressure modelling.

---

## 14. Connecting a real PLC

The plant UI stays the same. Only the sidebar driver changes.

### Modbus TCP (OpenPLC or any Modbus server)

1. Leave **PLC driver** on Modbus TCP.
2. Enter the PLC **host** and **port** (often `502`; bundled SoftPLC uses `5502`).
3. If the map is the same 7 holding registers + 4 coils but not at 1024 / 0, expand **Modbus addresses** and set the bases.
4. The 11 signals must stay in the order listed in the IO map.

### EtherNet/IP Logix (1756-L84ES GuardLogix and other Logix)

1. Put the PC and the controller on the same subnet. For a **1756-L84ES**, use the **embedded Ethernet** IP, **slot 0**, and leave **CIP path** blank.
2. In Studio 5000, create **controller-scoped standard BOOL** tags matching the default names (or type your existing names into **Logix tag names**).
3. Implement the same permissives as `plc_logic.py` (start only if valve open and not faulted; latch start-blocked until Reset).
4. In the MPSS sidebar: **EtherNet/IP**, enter the IP (slot 0, CIP path blank for a 1756-L84ES).
5. Edit **Logix tag names** if your program does not use the defaults. Empty names are rejected.
6. Click **Connect**. MPSS does not write tags until then. The first connect uploads the controller tag list (can take a few seconds).
7. Allow EtherNet/IP through the firewall (**TCP/UDP 44818**). Use **Disconnect** when finished.

Hold Start/Stop/Reset bits for ~0.5 s so a Logix periodic task can sample them. Command bits on the Logix should also be held for a few hundred milliseconds (same idea as `plc_logic.py`), not a single 10 ms scan.

If your tags already have other names, edit them once in the sidebar — you do not re-enter them every session (Streamlit keeps them while the app is open). Connecting a second Logix is then IP (and slot/path) only, as long as the tag names match.

**ControlLogix via a 1756-ENxT:** set **Controller slot** to the CPU slot, or paste the full CIP path from Studio 5000.
