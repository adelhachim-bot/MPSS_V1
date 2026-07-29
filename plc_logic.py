"""Sump-pump start permissive logic (FDS Appendix A).

This is the control logic that a SoftPLC / OpenPLC program executes.
Plant behaviour stays in simulation.py — this module only decides commands.

If you're new to PLCs: a PLC doesn't run continuously like a normal program.
It runs a tiny program over and over, forever, in a loop called a "scan"
(see soft_plc.py's scan_loop). On every single scan it:
    1. reads its inputs (sensors, buttons)
    2. runs its program once, top to bottom
    3. writes its outputs (commands, alarms)
    4. repeats

`SumpPumpPlcLogic.scan()` below IS that "run the program once" step. It gets
called ~20 times per second (every 50 ms) by soft_plc.py. Everything this
class remembers between one call and the next (PlcLogicState) is exactly
what a PLC would keep in its own internal memory between scans.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlcInputs:
    """What the PLC reads at the start of a scan (its "sensors").

    These mirror the plant's feedback signals 1:1 (see PlantFeedback in
    simulation.py) plus the three momentary operator buttons from the HMI.
    In the real Modbus link these come from holding registers 1024-1030;
    soft_plc.py's _read_inputs() is what actually fills this in each scan.
    """

    pump_running: bool = False
    pump_fault: bool = False
    disch_pressure_ok: bool = False
    downstream_valve_open: bool = True
    op_start: bool = False  # HMI "Start" button, held true for ~1 scan cycle
    op_stop: bool = False  # HMI "Stop" button
    op_reset: bool = False  # HMI "Reset" button (clears alarms)


@dataclass
class PlcOutputs:
    """What the PLC decides at the end of a scan (its "commands").

    These are what gets written back out to the plant/HMI as Modbus coils.
    `message` is a human-readable explanation for the HMI only — a real PLC
    wouldn't have this (Modbus has no "send a string" concept), it's just a
    convenience for this pilot's UI.
    """

    pump_start_cmd: bool = False
    pump_stop_cmd: bool = False
    pump_reset_cmd: bool = False
    start_blocked: bool = False  # latched alarm: last Start was rejected by a permissive
    message: str = "Ready"


@dataclass
class PlcLogicState:
    """Everything the PLC needs to remember between scans.

    A PLC has no concept of "the previous function call" the way normal code
    does — each scan is a fresh call to scan(). So anything that depends on
    *change* (like "did the button just get pressed?") has to be remembered
    explicitly here and carried forward. This is the PLC's internal memory.
    """

    start_blocked: bool = False  # sticky alarm, only cleared by an explicit Reset
    # "prev_*" flags remember last scan's input value, purely so we can
    # detect the moment a button transitions from not-pressed to pressed.
    prev_op_start: bool = False
    prev_op_stop: bool = False
    prev_op_reset: bool = False
    message: str = "Ready"
    # "*_hold" are countdown timers, in units of scans (not seconds). While
    # one is > 0 the matching output command stays TRUE. See the pulse-hold
    # explanation on SumpPumpPlcLogic below.
    start_hold: int = 0
    stop_hold: int = 0
    reset_hold: int = 0


class SumpPumpPlcLogic:
    """Rising-edge HMI commands → held plant command pulses + latching alarm.

    Pulses are held for several scans so a Modbus client polling slower than the
    SoftPLC scan rate still observes the command bit.

    Two PLC concepts show up here that are worth understanding up front:

    1. Rising-edge detection. In Modbus, a "button press" is just a register
       sitting at 1 for as long as the HMI holds it there — there's no
       built-in "button was just clicked" event. So the PLC has to compare
       *this* scan's value to *last* scan's value itself: if it's 1 now and
       was 0 last scan, that's the instant of the click (a "rising edge").
       Without this check, holding a button down would re-trigger the action
       on every single 50 ms scan instead of once.

    2. Pulse holding. The SoftPLC scans every 50 ms, but the Modbus client
       (MPSS) only polls it roughly every 100-250 ms. If the PLC set an
       output true for just one 50 ms scan, MPSS could easily poll in the
       gap and miss it completely. So instead of a single-scan pulse, the
       PLC holds each output command true for `pulse_scans` scans in a row —
       long enough that a slower outside observer is guaranteed to see it.
    """

    def __init__(self, pulse_scans: int = 6) -> None:
        # 6 scans * 50ms/scan = ~300ms — comfortably longer than MPSS's poll
        # interval, so a slow client can never step over a command pulse.
        self.pulse_scans = pulse_scans
        self.state = PlcLogicState()

    def reset(self) -> None:
        """Wipe all PLC memory — equivalent to power-cycling the controller."""
        self.state = PlcLogicState()

    def scan(self, inputs: PlcInputs) -> PlcOutputs:
        """Run the control program once. Called every scan (~50 ms) by soft_plc.py.

        This mirrors how a real PLC program executes: read inputs → evaluate
        rules top-to-bottom → produce outputs → remember what changed for
        next time. Nothing here "waits" — the whole function runs in a tiny
        fraction of a millisecond, then control returns to the scan loop.
        """
        # --- Step 1: edge detection -----------------------------------
        # Compare this scan's button state to last scan's (stored in
        # self.state) to find the exact scan a button was newly pressed.
        start_edge = inputs.op_start and not self.state.prev_op_start
        stop_edge = inputs.op_stop and not self.state.prev_op_stop
        reset_edge = inputs.op_reset and not self.state.prev_op_reset

        # Remember this scan's raw button values for next scan's comparison.
        self.state.prev_op_start = inputs.op_start
        self.state.prev_op_stop = inputs.op_stop
        self.state.prev_op_reset = inputs.op_reset

        # --- Step 2: evaluate rules (this is "the program") ------------
        if reset_edge:
            # Operator pressed Reset: clear the latched alarm and pulse the
            # PUMP_RESET_CMD output so the plant can clear its own fault bit.
            self.state.start_blocked = False
            self.state.reset_hold = self.pulse_scans
            self.state.message = "Reset issued — alarms cleared"

        if stop_edge:
            self.state.stop_hold = self.pulse_scans
            self.state.message = "Stop command issued"

        if start_edge:
            # This is the actual "permissive" check the FDS scenario asks
            # for: the PLC must refuse to start the pump unless it's safe to.
            if self.state.start_blocked or inputs.pump_fault:
                # Already alarmed, or the equipment itself is faulted —
                # refuse silently until the operator clears it with Reset.
                self.state.message = "Start rejected — clear fault / alarm first"
            elif not inputs.downstream_valve_open:
                # The interlock: don't start the pump into a closed valve.
                # Note this *latches* start_blocked = True rather than just
                # rejecting once — the alarm stays up until Reset, exactly
                # like a real safety interlock would.
                self.state.start_blocked = True
                self.state.message = (
                    "Start blocked — downstream valve not open (permissive fail)"
                )
            else:
                # All permissives satisfied: begin the start-command pulse.
                self.state.start_hold = self.pulse_scans
                self.state.message = "Start command issued"

        # --- Step 3: build this scan's outputs --------------------------
        # A command is TRUE for as long as its hold counter hasn't run out.
        out = PlcOutputs(
            pump_start_cmd=self.state.start_hold > 0,
            pump_stop_cmd=self.state.stop_hold > 0,
            pump_reset_cmd=self.state.reset_hold > 0,
            start_blocked=self.state.start_blocked,
            message=self.state.message,
        )

        # --- Step 4: count the pulse timers down for next scan ----------
        # Each hold counter ticks down by one scan; once it hits 0 the
        # corresponding output goes back to FALSE on its own.
        if self.state.start_hold > 0:
            self.state.start_hold -= 1
        if self.state.stop_hold > 0:
            self.state.stop_hold -= 1
        if self.state.reset_hold > 0:
            self.state.reset_hold -= 1

        return out
