"""Virtual sump-pump station (logical equipment, not physics).

Does not decide whether a start is *allowed* — that is the PLC's job.
This only answers: given the PLC's commands, what does the equipment do next?
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time


@dataclass
class PlantFeedback:
    """Sensors the plant reports to the PLC."""

    pump_running: bool = False
    pump_fault: bool = False
    disch_pressure_ok: bool = False
    downstream_valve_open: bool = True


@dataclass
class PlantCommands:
    """Actuator commands the PLC writes into the plant."""

    pump_start_cmd: bool = False
    pump_stop_cmd: bool = False
    pump_reset_cmd: bool = False


class SumpPumpStation:
    """STOPPED → STARTING (~4 s) → RUNNING, then pressure OK (~1 s later)."""

    def __init__(
        self,
        startup_delay_s: float = 4.0,
        pressure_rise_s: float = 1.0,
    ) -> None:
        self.startup_delay_s = startup_delay_s
        self.pressure_rise_s = pressure_rise_s
        self.reset_simulation()

    def set_commands(self, commands: PlantCommands) -> None:
        self._commands = commands

    def get_feedback(self) -> PlantFeedback:
        return PlantFeedback(**asdict(self._feedback))

    def set_downstream_valve_open(self, is_open: bool) -> None:
        """Scenario control: this valve is not driven by the PLC in the demo."""
        self._feedback.downstream_valve_open = is_open

    def inject_pump_fault(self) -> None:
        self._feedback.pump_fault = True
        self._stop_pump()

    def reset_simulation(self) -> None:
        """FDS initial state: stopped, valve open, no faults."""
        self._commands = PlantCommands()
        self._feedback = PlantFeedback()
        self._starting = False
        self._start_ready_at: float | None = None
        self._pressure_ready_at: float | None = None
        self._prev_start = False
        self._prev_reset = False

    @property
    def is_starting(self) -> bool:
        return self._starting

    @property
    def status_label(self) -> str:
        if self._feedback.pump_fault:
            return "FAULT"
        if self._starting:
            return "STARTING"
        if self._feedback.pump_running:
            return "RUNNING"
        return "STOPPED"

    def tick(self, now: float | None = None) -> PlantFeedback:
        """Advance on wall-clock time so delays are real seconds, not tick counts."""
        now = time.monotonic() if now is None else now
        cmd = self._commands

        start_edge = cmd.pump_start_cmd and not self._prev_start
        reset_edge = cmd.pump_reset_cmd and not self._prev_reset
        self._prev_start = cmd.pump_start_cmd
        self._prev_reset = cmd.pump_reset_cmd

        if reset_edge and self._feedback.pump_fault:
            self._feedback.pump_fault = False

        if cmd.pump_stop_cmd:
            self._stop_pump()
        elif start_edge and not self._feedback.pump_fault:
            if not self._feedback.pump_running and not self._starting:
                self._starting = True
                self._start_ready_at = now + self.startup_delay_s
                self._pressure_ready_at = None
                self._feedback.disch_pressure_ok = False

        if self._starting and self._start_ready_at is not None and now >= self._start_ready_at:
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
            self._feedback.disch_pressure_ok = True
            self._pressure_ready_at = None

        if not self._feedback.pump_running and not self._starting:
            self._feedback.disch_pressure_ok = False
            self._pressure_ready_at = None

        return self.get_feedback()

    def _stop_pump(self) -> None:
        self._starting = False
        self._start_ready_at = None
        self._pressure_ready_at = None
        self._feedback.pump_running = False
        self._feedback.disch_pressure_ok = False
