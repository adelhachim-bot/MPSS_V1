"""MPSS Pilot — Streamlit UI over sump pump simulation + Modbus SoftPLC."""

from __future__ import annotations

import time

import streamlit as st

from io_map import DEFAULT_HOST, DEFAULT_PORT
from plc_bridge import ModbusPlcBridge
from simulation import SumpPumpStation
from ui import (
    inject_css,
    render_demo_script,
    render_header,
    render_message,
    render_schematic,
    render_signal_lamps,
    render_status_banner,
)

POLL_INTERVAL_S = 0.25


def _init_session() -> None:
    if "plant" not in st.session_state:
        st.session_state.plant = SumpPumpStation(startup_delay_s=4.0, pressure_rise_s=1.0)
    if "bridge_host" not in st.session_state:
        st.session_state.bridge_host = DEFAULT_HOST
    if "bridge_port" not in st.session_state:
        st.session_state.bridge_port = DEFAULT_PORT
    if "plc" not in st.session_state:
        st.session_state.plc = ModbusPlcBridge(
            host=st.session_state.bridge_host,
            port=st.session_state.bridge_port,
        )


def _ensure_plc() -> ModbusPlcBridge:
    plc: ModbusPlcBridge = st.session_state.plc
    if plc.host != st.session_state.bridge_host or plc.port != st.session_state.bridge_port:
        plc.close()
        plc = ModbusPlcBridge(host=st.session_state.bridge_host, port=st.session_state.bridge_port)
        st.session_state.plc = plc
    return plc


def main() -> None:
    st.set_page_config(
        page_title="MPSS Pilot — Sump Pump",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    _init_session()

    with st.sidebar:
        st.markdown("### PLC connection")
        st.session_state.bridge_host = st.text_input(
            "SoftPLC host", value=st.session_state.bridge_host
        )
        st.session_state.bridge_port = int(
            st.number_input(
                "SoftPLC port",
                min_value=1,
                max_value=65535,
                value=int(st.session_state.bridge_port),
            )
        )
        st.caption("Start SoftPLC first: `python soft_plc.py`")

    plant: SumpPumpStation = st.session_state.plant
    plc = _ensure_plc()

    commands = plc.step(plant.get_feedback())
    plant.set_commands(commands)
    feedback = plant.tick()

    if plc.state.connected:
        render_header(linked=True, link_text=f"SoftPLC @ {plc.host}:{plc.port}")
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
            '<p class="mpss-hint">HMI → PLC — Start / Stop / Reset (permissives enforced by SoftPLC)</p>'
            '<div class="mpss-ops"></div>',
            unsafe_allow_html=True,
        )
        b1, b2, b3 = st.columns(3)
        if b1.button("▶  START", use_container_width=True, help="Issue pump start to PLC"):
            plc.operator_start(feedback)
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

    if plant.is_starting or (
        feedback.pump_running and not feedback.disch_pressure_ok
    ):
        time.sleep(POLL_INTERVAL_S)
        st.rerun()


if __name__ == "__main__":
    main()
