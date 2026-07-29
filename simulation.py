"""Sump pump station process simulation (virtual plant).

Models logical equipment behaviour for PLC-in-the-loop testing.
Physical fidelity is intentionally low — state transitions and delays matter.

This file deliberately knows nothing about permissives, alarms, or "should
this be allowed to start" — that's all the PLC's job (plc_logic.py). This
file only answers "given whatever command the PLC sent, what would the real
equipment physically do next?" That split mirrors reality: a real pump
doesn't know or care why the PLC told it to start — it just starts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time


@dataclass
class PlantFeedback:
    """Signals MPSS exposes to the PLC as inputs.

    This is the plant's "sensors" — what a real pump station would report
    back to a PLC via wired IO or a Modbus signal. See PlcInputs in
    plc_logic.py, which mirrors this 1:1 on the PLC side of the link.
    """

    pump_running: bool = False
    pump_fault: bool = False
    disch_pressure_ok: bool = False
    downstream_valve_open: bool = True


@dataclass
class PlantCommands:
    """Commands the PLC writes as outputs into MPSS.

    This is the plant's "actuators" — whatever the PLC decided in
    plc_logic.py (PlcOutputs), stripped down to just the three signals that
    actually affect equipment (the alarm/message fields stay PLC-side).
    """

    pump_start_cmd: bool = False
    pump_stop_cmd: bool = False
    pump_reset_cmd: bool = False


class SumpPumpStation:
    """Single sump transfer pump with downstream isolation valve and pressure TX.

    This is a small state machine, not a physics model: it tracks whether
    the pump is STOPPED / STARTING / RUNNING / FAULT and moves between those
    states after realistic *delays*, without simulating flow, pressure
    curves, or anything physically detailed. That's enough to make PLC
    timing logic (like "wait for the pump to actually be running before
    checking pressure") behave believably.
    """

    def __init__(
        self,
        startup_delay_s: float = 4.0,
        pressure_rise_s: float = 1.0,
    ) -> None:
        self.startup_delay_s = startup_delay_s
        self.pressure_rise_s = pressure_rise_s

        self._commands = PlantCommands()
        self._feedback = PlantFeedback()

        # _starting = "spinning up but not yet at speed" — a real motor
        # doesn't reach full running state instantly, so we model that gap
        # with a timer rather than flipping pump_running true immediately.
        self._starting = False
        self._start_ready_at: float | None = None  # wall-clock time when startup finishes
        self._pressure_ready_at: float | None = None  # wall-clock time pressure reads OK

        # Same edge-detection trick used in plc_logic.py, but here it's the
        # *plant* watching for the instant a command turns on, so a start
        # command that's held true for many scans only triggers one startup
        # sequence instead of restarting the timer every tick.
        self._prev_start = False
        self._prev_stop = False
        self._prev_reset = False

    # --- command / feedback API (used later by Modbus/OPC bridge) ---

    def set_commands(self, commands: PlantCommands) -> None:
        """Latch in whatever the PLC last decided, ready for the next tick()."""
        self._commands = PlantCommands(
            pump_start_cmd=commands.pump_start_cmd,
            pump_stop_cmd=commands.pump_stop_cmd,
            pump_reset_cmd=commands.pump_reset_cmd,
        )

    def get_feedback(self) -> PlantFeedback:
        # Returns a *copy* so callers can't accidentally mutate our internal
        # state through the returned object.
        return PlantFeedback(**asdict(self._feedback))

    def feedback_dict(self) -> dict[str, bool]:
        return asdict(self.get_feedback())

    # --- operator / demo controls (fault injection & sim reset) ---

    def set_downstream_valve_open(self, is_open: bool) -> None:
        """MPSS-only scenario control — a real valve isn't operated by the PLC
        in this scenario, so this bypasses the command/feedback loop entirely."""
        self._feedback.downstream_valve_open = is_open

    def inject_pump_fault(self) -> None:
        """Optional mid-run trip: equipment reports fault and drops offline."""
        self._feedback.pump_fault = True
        self._stop_pump(clear_fault=False)

    def reset_simulation(self) -> None:
        """Return plant to FDS initial state (stopped, valve open, no faults)."""
        self._commands = PlantCommands()
        self._feedback = PlantFeedback()
        self._starting = False
        self._start_ready_at = None
        self._pressure_ready_at = None
        self._prev_start = False
        self._prev_stop = False
        self._prev_reset = False

    @property
    def is_starting(self) -> bool:
        return self._starting

    @property
    def status_label(self) -> str:
        """One of STOPPED / STARTING / RUNNING / FAULT, purely for the HMI."""
        if self._feedback.pump_fault:
            return "FAULT"
        if self._starting:
            return "STARTING"
        if self._feedback.pump_running:
            return "RUNNING"
        return "STOPPED"

    # --- simulation tick ---

    def tick(self, now: float | None = None) -> PlantFeedback:
        """Advance plant state from current commands. Call ~1 Hz or faster.

        Everything below runs on every Streamlit rerun. It's intentionally
        time-based (using real elapsed seconds, `now`) rather than counting
        fixed steps, so delays feel like real seconds regardless of how
        often the UI happens to rerun.
        """
        now = time.monotonic() if now is None else now
        cmd = self._commands

        # Same rising-edge idea as plc_logic.py: only react at the instant a
        # command turns on, not on every tick it stays on.
        start_edge = cmd.pump_start_cmd and not self._prev_start
        stop_edge = cmd.pump_stop_cmd and not self._prev_stop
        reset_edge = cmd.pump_reset_cmd and not self._prev_reset

        self._prev_start = cmd.pump_start_cmd
        self._prev_stop = cmd.pump_stop_cmd
        self._prev_reset = cmd.pump_reset_cmd

        if reset_edge and self._feedback.pump_fault:
            self._feedback.pump_fault = False

        if stop_edge or cmd.pump_stop_cmd:
            # Stop wins immediately and unconditionally — no startup delay
            # on the way down, matching how a real motor contactor drops out.
            self._stop_pump(clear_fault=False)

        elif start_edge and not self._feedback.pump_fault:
            # Plant accepts a start command; permissives live in the PLC.
            # If already running/starting, ignore duplicate start edges.
            if not self._feedback.pump_running and not self._starting:
                # Begin the startup delay instead of jumping straight to
                # RUNNING — this is the "spin-up time" a real pump would need.
                self._starting = True
                self._start_ready_at = now + self.startup_delay_s
                self._pressure_ready_at = None
                self._feedback.disch_pressure_ok = False

        if self._starting and self._start_ready_at is not None and now >= self._start_ready_at:
            # Startup delay has elapsed: the pump is now actually running,
            # but discharge pressure takes a bit longer to build (below).
            self._starting = False
            self._start_ready_at = None
            self._feedback.pump_running = True
            self._pressure_ready_at = now + self.pressure_rise_s

        if (
            self._feedback.pump_running
            and not self._feedback.disch_pressure_ok
            and self._pressure_ready_at is not None
            and now >= self._pressure_ready_at
        ):
            # Pressure rise delay has elapsed: discharge pressure now reads OK.
            self._feedback.disch_pressure_ok = True
            self._pressure_ready_at = None

        if not self._feedback.pump_running and not self._starting:
            # Whenever the pump isn't actively running or starting, pressure
            # can't be "OK" — covers the stop/fault paths, which skip the
            # pressure-rise timer above entirely.
            self._feedback.disch_pressure_ok = False
            self._pressure_ready_at = None

        return self.get_feedback()

    def _stop_pump(self, *, clear_fault: bool) -> None:
        """Shared shutdown path for both a normal Stop and a fault trip."""
        self._starting = False
        self._start_ready_at = None
        self._pressure_ready_at = None
        self._feedback.pump_running = False
        self._feedback.disch_pressure_ok = False
        if clear_fault:
            self._feedback.pump_fault = False
