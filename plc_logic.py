"""Sump-pump start permissives (FDS Appendix A).

This is the program a PLC would run. The plant itself lives in simulation.py.

A PLC does not run continuously: it *scans* — read inputs, run this program
once, write outputs, repeat (~every 50 ms in soft_plc.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlcInputs:
    """Sensors + HMI buttons the PLC reads at the start of a scan (HR 1024–1030)."""

    pump_running: bool = False
    pump_fault: bool = False
    disch_pressure_ok: bool = False
    downstream_valve_open: bool = True
    op_start: bool = False
    op_stop: bool = False
    op_reset: bool = False


@dataclass
class PlcOutputs:
    """Commands + alarm the PLC writes to coils. `message` is HMI-only (not Modbus)."""

    pump_start_cmd: bool = False
    pump_stop_cmd: bool = False
    pump_reset_cmd: bool = False
    start_blocked: bool = False
    message: str = "Ready"


class Button:
    """HMI button: rising-edge detect + a multi-scan output pulse.

    Modbus has no click event — a button is just a bit held at 1. We fire on
    the up→down edge so holding it does not repeat, then keep the command coil
    TRUE for a few scans so a slower Modbus client cannot miss the pulse.
    """

    def __init__(self) -> None:
        self._was_down = False
        self._scans_left = 0

    def pressed(self, is_down: bool) -> bool:
        rising = is_down and not self._was_down
        self._was_down = is_down
        return rising

    def hold(self, scans: int) -> None:
        self._scans_left = scans

    @property
    def is_active(self) -> bool:
        return self._scans_left > 0

    def countdown(self) -> None:
        if self._scans_left > 0:
            self._scans_left -= 1


class SumpPumpPlcLogic:
    """Start only if the valve is open and the pump is not faulted.

    A failed start latches START_BLOCKED until Reset. Stop and Reset always
    work. Default pulse is 6 scans × 50 ms ≈ 300 ms.
    """

    def __init__(self, pulse_scans: int = 6) -> None:
        self.pulse_scans = pulse_scans
        self.start_button = Button()
        self.stop_button = Button()
        self.reset_button = Button()
        self.start_blocked = False
        self.message = "Ready"

    def scan(self, inputs: PlcInputs) -> PlcOutputs:
        start_pressed = self.start_button.pressed(inputs.op_start)
        stop_pressed = self.stop_button.pressed(inputs.op_stop)
        reset_pressed = self.reset_button.pressed(inputs.op_reset)

        if reset_pressed:
            self.start_blocked = False
            self.reset_button.hold(self.pulse_scans)
            self.message = "Reset issued — alarms cleared"

        if stop_pressed:
            self.stop_button.hold(self.pulse_scans)
            self.message = "Stop command issued"

        if start_pressed:
            if self.start_blocked or inputs.pump_fault:
                self.message = "Start rejected — clear fault / alarm first"
            elif not inputs.downstream_valve_open:
                self.start_blocked = True
                self.message = (
                    "Start blocked — downstream valve not open (permissive fail)"
                )
            else:
                self.start_button.hold(self.pulse_scans)
                self.message = "Start command issued"

        outputs = PlcOutputs(
            pump_start_cmd=self.start_button.is_active,
            pump_stop_cmd=self.stop_button.is_active,
            pump_reset_cmd=self.reset_button.is_active,
            start_blocked=self.start_blocked,
            message=self.message,
        )
        self.start_button.countdown()
        self.stop_button.countdown()
        self.reset_button.countdown()
        return outputs
