"""MPSS Pilot — Streamlit HMI over the virtual plant + a PLC in the loop."""

from __future__ import annotations

import time

import streamlit as st

from io_map import (
    DEFAULT_HOST,
    DEFAULT_LOGIX_TAGS,
    DEFAULT_PORT,
    DRIVER_LOGIX,
    DRIVER_MODBUS,
    HR_BASE,
    INPUT_SIGNALS,
    OUTPUT_SIGNALS,
)
from plc_bridge import PlcTarget, create_bridge
from simulation import SumpPumpStation
from ui import (
    inject_css,
    render_demo_script,
    render_header,
    render_io_panel,
    render_message,
    render_schematic,
    render_signal_lamps,
    render_status_banner,
)

POLL_INTERVAL_S = 0.25

_DRIVER_LABELS = {
    DRIVER_MODBUS: "Modbus TCP — SoftPLC, OpenPLC, or other Modbus PLC",
    DRIVER_LOGIX: "EtherNet/IP — GuardLogix / ControlLogix / CompactLogix",
}


def _init_session() -> None:
    ss = st.session_state
    ss.setdefault("plant", SumpPumpStation(startup_delay_s=4.0, pressure_rise_s=1.0))
    ss.setdefault("plc_driver", DRIVER_MODBUS)
    ss.setdefault("modbus_host", DEFAULT_HOST)
    ss.setdefault("modbus_port", DEFAULT_PORT)
    ss.setdefault("hr_base", HR_BASE)
    ss.setdefault("coil_base", 0)
    ss.setdefault("logix_ip", "")
    ss.setdefault("logix_slot", 0)
    ss.setdefault("logix_path", "")
    ss.setdefault("logix_tags", dict(DEFAULT_LOGIX_TAGS))
    ss.setdefault("logix_enabled", False)
    ss.setdefault("live_io", True)
    if "plc" not in ss:
        target = _target_from_session()
        ss.plc = create_bridge(target)
        ss.plc_config_key = target.key()


def _target_from_session() -> PlcTarget:
    ss = st.session_state
    if ss.plc_driver == DRIVER_LOGIX:
        tags = tuple(
            (name, str(ss.logix_tags.get(name, DEFAULT_LOGIX_TAGS[name])).strip())
            for name in (*INPUT_SIGNALS, *OUTPUT_SIGNALS)
        )
        return PlcTarget(
            driver=DRIVER_LOGIX,
            host=str(ss.logix_ip).strip(),
            slot=int(ss.logix_slot),
            cip_path=str(ss.logix_path).strip(),
            tags=tags,
        )
    return PlcTarget(
        driver=DRIVER_MODBUS,
        host=str(ss.modbus_host).strip(),
        port=int(ss.modbus_port),
        hr_base=int(ss.hr_base),
        coil_base=int(ss.coil_base),
    )


def _ensure_plc():
    """Rebuild the client when the operator changes driver, address, or tags."""
    ss = st.session_state
    target = _target_from_session()
    if ss.get("plc_config_key") != target.key():
        ss.plc.close()
        ss.plc = create_bridge(target)
        ss.plc_config_key = target.key()
        if target.driver == DRIVER_LOGIX:
            ss.logix_enabled = False
    if getattr(ss.plc, "driver", None) == DRIVER_LOGIX:
        ss.plc.set_enabled(bool(ss.logix_enabled))
    return ss.plc


def _render_connection_sidebar() -> None:
    ss = st.session_state
    st.markdown("### PLC connection")
    st.selectbox(
        "PLC driver",
        options=[DRIVER_MODBUS, DRIVER_LOGIX],
        format_func=lambda key: _DRIVER_LABELS[key],
        key="plc_driver",
        help=(
            "SoftPLC and other Modbus devices use Modbus TCP. "
            "A 1756-L84ES GuardLogix (and other Logix) uses EtherNet/IP."
        ),
    )

    if ss.plc_driver == DRIVER_LOGIX:
        st.text_input(
            "Logix IP address",
            key="logix_ip",
            help="1756-L84ES: IP of the controller's embedded Ethernet port.",
        )
        st.number_input(
            "Controller slot",
            min_value=0,
            max_value=16,
            key="logix_slot",
            help="0 for 1756-L84ES embedded Ethernet. Use the CPU slot if you connect via a 1756-ENxT.",
        )
        st.text_input(
            "CIP path (optional override)",
            key="logix_path",
            help="Leave blank unless you need a full Studio 5000-style route.",
        )
        st.caption(
            "Create controller-scoped **standard BOOL** tags on the Logix "
            "(not safety tags). Names default to the MPSS contract; edit them "
            "below if your program already uses other names."
        )
        with st.expander("Logix tag names", expanded=False):
            st.markdown("**MPSS → PLC**")
            for name in INPUT_SIGNALS:
                widget_key = f"logix_tag_{name}"
                ss.setdefault(widget_key, ss.logix_tags.get(name, DEFAULT_LOGIX_TAGS[name]))
                st.text_input(name, key=widget_key)
                ss.logix_tags[name] = ss[widget_key]
            st.markdown("**PLC → MPSS**")
            for name in OUTPUT_SIGNALS:
                widget_key = f"logix_tag_{name}"
                ss.setdefault(widget_key, ss.logix_tags.get(name, DEFAULT_LOGIX_TAGS[name]))
                st.text_input(name, key=widget_key)
                ss.logix_tags[name] = ss[widget_key]
        st.caption(
            "MPSS does not write tags until you click Connect. "
            "The first connect uploads the Logix tag list and can take a few seconds."
        )
        c1, c2 = st.columns(2)
        if c1.button("Connect", use_container_width=True, disabled=ss.logix_enabled):
            ss.logix_enabled = True
            st.rerun()
        if c2.button("Disconnect", use_container_width=True, disabled=not ss.logix_enabled):
            ss.logix_enabled = False
            st.rerun()
    else:
        st.text_input("Modbus host", key="modbus_host")
        st.number_input(
            "Modbus port",
            min_value=1,
            max_value=65535,
            key="modbus_port",
        )
        st.caption("Bundled SoftPLC: start `python soft_plc.py` first (`127.0.0.1:5502`).")
        with st.expander("Modbus addresses", expanded=False):
            st.number_input(
                "Holding register base (7 registers)",
                min_value=0,
                max_value=65535,
                key="hr_base",
                help="OpenPLC / SoftPLC: 1024 (%MW0). Signals must be contiguous, same order as the live IO panel.",
            )
            st.number_input(
                "Coil base (4 coils)",
                min_value=0,
                max_value=65535,
                key="coil_base",
                help="OpenPLC / SoftPLC: 0 (%QX0.0). Signals must be contiguous, same order as the live IO panel.",
            )

    st.markdown("### Live view")
    st.toggle(
        "Auto-refresh live IO",
        key="live_io",
        help="Keep polling the PLC so the live IO panel updates while idle.",
    )


def main() -> None:
    st.set_page_config(
        page_title="MPSS Pilot — Sump Pump",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    _init_session()

    with st.sidebar:
        _render_connection_sidebar()

    plant: SumpPumpStation = st.session_state.plant
    plc = _ensure_plc()

    plant.set_commands(plc.step(plant.get_feedback()))
    feedback = plant.tick()

    if plc.state.connected:
        render_header(linked=True, link_text=plc.target_label)
    else:
        render_header(linked=False, link_text=plc.state.last_message)

    render_schematic(feedback, status=plant.status_label)

    left, right = st.columns([1.15, 1], gap="large")

    with left:
        st.markdown("#### Process state")
        render_status_banner(plant.status_label)
        render_signal_lamps(feedback)
        render_message(plc.state.last_message, alarm=plc.state.start_blocked)

        st.markdown("#### Operator commands")
        st.markdown(
            '<p class="mpss-hint">HMI → PLC — Start / Stop / Reset (permissives enforced by the PLC)</p>'
            '<div class="mpss-ops"></div>',
            unsafe_allow_html=True,
        )
        b1, b2, b3 = st.columns(3)
        if b1.button("▶  START", use_container_width=True, help="Issue pump start to PLC"):
            plc.operator_start()
            st.rerun()
        if b2.button("■  STOP", use_container_width=True, help="Issue pump stop to PLC"):
            plc.operator_stop()
            st.rerun()
        if b3.button("↺  RESET", use_container_width=True, help="Clear start-blocked / fault latch"):
            plc.operator_reset()
            st.rerun()

    with right:
        st.markdown("#### Fault injection (MPSS)")
        st.markdown(
            '<p class="mpss-hint">Plant-side scenario controls — not PLC operator actions</p>',
            unsafe_allow_html=True,
        )

        valve_open = st.toggle(
            "Downstream isolation valve OPEN",
            value=feedback.downstream_valve_open,
            help="Sets DOWNSTREAM_VALVE_OPEN feedback into the PLC",
        )
        if valve_open != feedback.downstream_valve_open:
            plant.set_downstream_valve_open(valve_open)
            st.rerun()

        st.markdown('<div class="mpss-faults"></div>', unsafe_allow_html=True)
        f1, f2 = st.columns(2)
        if f1.button("⚡  INJECT TRIP", use_container_width=True, help="Force PUMP_FAULT and stop the pump"):
            plant.inject_pump_fault()
            plc.state.last_message = "Pump trip injected from MPSS"
            st.rerun()
        if f2.button("⟲  RESET SIM", use_container_width=True, help="Return plant + PLC to FDS initial state"):
            plant.reset_simulation()
            plc.reset_logic()
            plc.operator_reset()
            st.rerun()

        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        render_demo_script()

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
    with st.expander("🔌 Live IO (raw values on the wire)", expanded=True):
        render_io_panel(plc)

    if (
        st.session_state.live_io
        or plant.is_starting
        or (feedback.pump_running and not feedback.disch_pressure_ok)
        or getattr(plc, "has_held_ops", lambda: False)()
    ):
        time.sleep(POLL_INTERVAL_S)
        st.rerun()


if __name__ == "__main__":
    main()
