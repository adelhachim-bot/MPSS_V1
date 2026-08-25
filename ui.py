"""HMI-style visuals for the MPSS Streamlit demo."""

from __future__ import annotations

import time

import streamlit as st
from PIL import Image, ImageDraw

from simulation import PlantFeedback

# Industrial panel palette (steel / amber — not purple-on-white).
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');

html, body, [class*="css"] {
  font-family: "IBM Plex Sans", sans-serif;
}

.block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1200px; }

.mpss-hero {
  background: linear-gradient(135deg, #0f1720 0%, #1a2a3a 55%, #243447 100%);
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 1rem 1.25rem 1.1rem;
  margin-bottom: 1rem;
  color: #e2e8f0;
}
.mpss-hero h1 {
  font-size: 1.55rem; font-weight: 700; margin: 0 0 0.2rem 0;
  letter-spacing: 0.02em; color: #f8fafc;
}
.mpss-hero p { margin: 0; color: #94a3b8; font-size: 0.92rem; }

.mpss-link-ok, .mpss-link-bad {
  display: inline-flex; align-items: center; gap: 0.45rem;
  margin-top: 0.65rem; padding: 0.35rem 0.7rem; border-radius: 999px;
  font-size: 0.82rem; font-weight: 600; font-family: "IBM Plex Mono", monospace;
}
.mpss-link-ok { background: #14532d33; color: #4ade80; border: 1px solid #22c55e55; }
.mpss-link-bad { background: #7f1d1d33; color: #f87171; border: 1px solid #ef444455; }
.mpss-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.mpss-dot.on { background: #4ade80; box-shadow: 0 0 8px #4ade80; }
.mpss-dot.off { background: #f87171; box-shadow: 0 0 8px #f87171; }

.mpss-panel {
  background: #111827;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 0.9rem 1rem 1rem;
  margin-bottom: 0.85rem;
}
.mpss-panel h3 {
  margin: 0 0 0.75rem 0; font-size: 0.78rem; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; color: #94a3b8;
}

.mpss-status {
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; padding: 0.85rem 1rem; border-radius: 10px;
  border: 1px solid #334155; margin-bottom: 0.85rem;
}
.mpss-status .label { font-size: 0.75rem; letter-spacing: 0.1em; text-transform: uppercase; color: #94a3b8; }
.mpss-status .value {
  font-family: "IBM Plex Mono", monospace; font-size: 1.6rem; font-weight: 700;
  letter-spacing: 0.06em;
}
.mpss-status.STOPPED { background: #1e293b; }
.mpss-status.STOPPED .value { color: #94a3b8; }
.mpss-status.STARTING { background: #422006; border-color: #d97706; }
.mpss-status.STARTING .value { color: #fbbf24; }
.mpss-status.RUNNING { background: #052e16; border-color: #16a34a; }
.mpss-status.RUNNING .value { color: #4ade80; }
.mpss-status.FAULT { background: #450a0a; border-color: #dc2626; }
.mpss-status.FAULT .value { color: #f87171; }

.mpss-lamps { display: grid; grid-template-columns: 1fr 1fr; gap: 0.55rem; }
.mpss-lamp {
  display: flex; align-items: center; gap: 0.65rem;
  background: #0f172a; border: 1px solid #334155; border-radius: 10px;
  padding: 0.55rem 0.7rem;
}
.mpss-lamp .led {
  width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0;
  border: 2px solid #475569; background: #334155;
}
.mpss-lamp.on .led {
  border-color: #86efac; background: #22c55e;
  box-shadow: 0 0 10px #22c55eaa;
}
.mpss-lamp.alarm.on .led {
  border-color: #fca5a5; background: #ef4444;
  box-shadow: 0 0 10px #ef4444aa;
  animation: mpss-blink 1s step-end infinite;
}
.mpss-lamp .tag {
  font-family: "IBM Plex Mono", monospace; font-size: 0.72rem; font-weight: 600;
  color: #cbd5e1; line-height: 1.2;
}
.mpss-lamp .state {
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.04em;
  color: #64748b;
}
.mpss-lamp.on .state { color: #86efac; }
.mpss-lamp.alarm.on .state { color: #fca5a5; }

@keyframes mpss-blink {
  50% { opacity: 0.35; box-shadow: none; }
}

.mpss-msg {
  margin-top: 0.75rem; padding: 0.65rem 0.8rem; border-radius: 8px;
  font-size: 0.88rem; font-weight: 500;
}
.mpss-msg.info { background: #0c4a6e33; border: 1px solid #0284c855; color: #7dd3fc; }
.mpss-msg.alarm { background: #7f1d1d33; border: 1px solid #ef444455; color: #fca5a5; }

/* Operator / MPSS action buttons */
div[data-testid="stHorizontalBlock"] button {
  font-family: "IBM Plex Sans", sans-serif !important;
  font-weight: 700 !important;
  letter-spacing: 0.04em !important;
  min-height: 3.4rem !important;
  border-radius: 10px !important;
  white-space: pre-line !important;
}

/* Start / Stop / Reset — marker markdown sibling of the button row */
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] button {
  color: #fff !important; border: none !important;
}
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] > div:nth-child(1) button {
  background: linear-gradient(180deg, #16a34a, #15803d) !important;
  box-shadow: 0 2px 0 #14532d;
}
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] > div:nth-child(1) button:hover {
  background: linear-gradient(180deg, #22c55e, #16a34a) !important;
}
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
  background: linear-gradient(180deg, #dc2626, #b91c1c) !important;
  box-shadow: 0 2px 0 #7f1d1d;
}
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] > div:nth-child(2) button:hover {
  background: linear-gradient(180deg, #ef4444, #dc2626) !important;
}
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] > div:nth-child(3) button {
  background: linear-gradient(180deg, #d97706, #b45309) !important;
  box-shadow: 0 2px 0 #78350f;
}
div[data-testid="stMarkdown"]:has(.mpss-ops) + div[data-testid="stHorizontalBlock"] > div:nth-child(3) button:hover {
  background: linear-gradient(180deg, #f59e0b, #d97706) !important;
}

div[data-testid="stMarkdown"]:has(.mpss-faults) + div[data-testid="stHorizontalBlock"] button {
  font-weight: 650 !important; min-height: 3.1rem !important; border-radius: 10px !important;
  white-space: pre-line !important;
}
div[data-testid="stMarkdown"]:has(.mpss-faults) + div[data-testid="stHorizontalBlock"] > div:nth-child(1) button {
  background: linear-gradient(180deg, #9a3412, #7c2d12) !important;
  color: #ffedd5 !important; border: 1px solid #ea580c88 !important;
}
div[data-testid="stMarkdown"]:has(.mpss-faults) + div[data-testid="stHorizontalBlock"] > div:nth-child(2) button {
  background: #1e293b !important; color: #e2e8f0 !important;
  border: 1px solid #475569 !important;
}

.mpss-script {
  background: #0f172a; border: 1px solid #334155; border-radius: 10px;
  padding: 0.75rem 0.9rem; color: #cbd5e1; font-size: 0.86rem; line-height: 1.45;
}
.mpss-script strong { color: #f8fafc; }
.mpss-script ol { margin: 0.35rem 0 0 1.1rem; padding: 0; }
.mpss-script li { margin-bottom: 0.25rem; }

.mpss-hint {
  font-size: 0.78rem; color: #64748b; margin: 0.35rem 0 0.6rem;
}

/* Live Modbus IO panel — a raw register/coil dump, like a Modbus test tool */
.mpss-io-table { display: flex; flex-direction: column; gap: 0.32rem; }
.mpss-io-row {
  display: grid; grid-template-columns: minmax(6.5rem, 1.3fr) 1fr 2.2rem; align-items: center;
  gap: 0.5rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px;
  padding: 0.32rem 0.6rem; font-family: "IBM Plex Mono", monospace; font-size: 0.74rem;
}
.mpss-io-row.on { border-color: #22c55e88; background: #14532d22; }
.mpss-io-addr { color: #64748b; }
.mpss-io-name { color: #cbd5e1; letter-spacing: 0.02em; }
.mpss-io-val {
  text-align: center; font-weight: 700; border-radius: 4px; padding: 0.1rem 0;
  color: #64748b; background: #1e293b;
}
.mpss-io-row.on .mpss-io-val { color: #052e16; background: #4ade80; }
.mpss-io-empty { color: #64748b; font-size: 0.82rem; padding: 0.3rem 0; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def render_header(*, linked: bool, link_text: str) -> None:
    kind, dot = ("ok", "on") if linked else ("bad", "off")
    link_html = (
        f'<div class="mpss-link-{kind}"><span class="mpss-dot {dot}"></span>{link_text}</div>'
    )
    st.markdown(
        f"""
        <div class="mpss-hero">
          <h1>MPSS Pilot Demo</h1>
          <p>Sump pump station — virtual plant with PLC-in-the-loop control</p>
          {link_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_banner(status: str) -> None:
    st.markdown(
        f"""
        <div class="mpss-status {status}">
          <div>
            <div class="label">Pump status</div>
            <div class="value">{status}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_signal_lamps(feedback: PlantFeedback) -> None:
    lamps = [
        ("PUMP_RUNNING", feedback.pump_running, False),
        ("PUMP_FAULT", feedback.pump_fault, True),
        ("DISCH_PRESSURE_OK", feedback.disch_pressure_ok, False),
        ("DOWNSTREAM_VALVE_OPEN", feedback.downstream_valve_open, False),
    ]
    parts = ['<div class="mpss-lamps">']
    for tag, on, alarm in lamps:
        cls = "mpss-lamp" + (" on" if on else "") + (" alarm" if alarm else "")
        parts.append(
            f'<div class="{cls}">'
            f'<div class="led"></div>'
            f'<div><div class="tag">{tag}</div>'
            f'<div class="state">{"TRUE" if on else "FALSE"}</div></div>'
            f"</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_message(text: str, *, alarm: bool) -> None:
    kind = "alarm" if alarm else "info"
    st.markdown(
        f'<div class="mpss-msg {kind}">{text}</div>',
        unsafe_allow_html=True,
    )


def render_schematic(feedback: PlantFeedback, *, status: str) -> None:
    """Process mimic as a PNG — Streamlit strips SVG in Markdown."""
    running = feedback.pump_running
    starting = status == "STARTING"
    fault = feedback.pump_fault
    valve_open = feedback.downstream_valve_open
    pressure_ok = feedback.disch_pressure_ok

    if fault:
        pump_fill, pump_outline = "#7f1d1d", "#ef4444"
    elif running:
        pump_fill, pump_outline = "#14532d", "#4ade80"
    elif starting:
        pump_fill, pump_outline = "#78350f", "#fbbf24"
    else:
        pump_fill, pump_outline = "#334155", "#94a3b8"

    valve_colour = "#4ade80" if valve_open else "#ef4444"
    pt_colour = "#4ade80" if pressure_ok else "#64748b"
    flow_colour = "#38bdf8" if running and valve_open else "#475569"

    image = Image.new("RGB", (1200, 280), "#0b1220")
    draw = ImageDraw.Draw(image)

    # Outer process-mimic panel.
    draw.rounded_rectangle((8, 8, 1192, 272), radius=16, fill="#0f172a", outline="#334155", width=2)
    draw.text((32, 25), "PROCESS MIMIC — LIVE VIRTUAL PLANT", fill="#94a3b8")

    # Sump and liquid level.
    draw.rounded_rectangle((45, 90, 175, 225), radius=10, fill="#1e293b", outline="#64748b", width=3)
    draw.rounded_rectangle((52, 155, 168, 218), radius=5, fill="#0369a1")
    draw.text((84, 65), "SUMP", fill="#cbd5e1")

    # Pipe and flow direction: blue when flow can pass; gray otherwise.
    draw.line((175, 158, 300, 158), fill=flow_colour, width=10)
    draw.line((400, 140, 535, 140), fill=flow_colour, width=10)
    draw.line((635, 140, 760, 140), fill=flow_colour, width=10)
    draw.line((860, 140, 980, 140), fill=flow_colour, width=10)
    if running and valve_open:
        for x in (205, 450, 680, 905):
            draw.polygon([(x, 130), (x + 20, 140), (x, 150)], fill="#7dd3fc")

    # Centrifugal pump: body and impeller.
    draw.ellipse((300, 90, 400, 190), fill=pump_fill, outline=pump_outline, width=5)
    draw.ellipse((337, 127, 363, 153), fill="#0b1220", outline=pump_outline, width=3)
    draw.polygon([(350, 100), (372, 140), (350, 180), (328, 140)], fill=pump_outline)
    draw.text((315, 205), "PUMP", fill="#e2e8f0")
    draw.text((302, 225), status, fill=pump_outline)

    # Pressure transmitter.
    draw.rounded_rectangle((535, 105, 635, 175), radius=10, fill="#0b1220", outline=pt_colour, width=4)
    draw.ellipse((570, 120, 600, 150), fill=pt_colour)
    draw.text((568, 190), "PT", fill="#cbd5e1")
    draw.text((555, 210), "PRESSURE " + ("OK" if pressure_ok else "LOW"), fill=pt_colour)

    # Isolation valve.
    draw.ellipse((760, 100, 860, 180), fill="#0b1220", outline=valve_colour, width=4)
    if valve_open:
        draw.line((772, 140, 848, 140), fill=valve_colour, width=9)
    else:
        draw.line((810, 107, 810, 173), fill=valve_colour, width=9)
    draw.text((775, 190), "ISOLATION VALVE", fill="#cbd5e1")
    draw.text((790, 210), "OPEN" if valve_open else "CLOSED", fill=valve_colour)

    # Downstream process destination.
    draw.rounded_rectangle((980, 100, 1145, 180), radius=12, fill="#1e293b", outline="#64748b", width=3)
    draw.text((1013, 122), "DOWNSTREAM", fill="#e2e8f0")
    draw.text((1030, 145), "PROCESS", fill="#94a3b8")

    st.markdown("#### Process mimic")
    st.caption(
        "A live picture of the virtual station: green pump / blue pipe means "
        "the process is flowing; valve and pressure respond to each scenario."
    )
    st.image(image, width="stretch")


def _io_rows_html(rows: list[tuple[str, str, int]], *, addr_prefix: str) -> str:
    if not rows:
        return '<div class="mpss-io-empty">No data yet — waiting for first poll…</div>'
    parts = ['<div class="mpss-io-table">']
    for address, name, value in rows:
        on = bool(value)
        addr = f"{addr_prefix} {address}".strip() if addr_prefix else str(address)
        parts.append(
            f'<div class="mpss-io-row{" on" if on else ""}">'
            f'<span class="mpss-io-addr">{addr}</span>'
            f'<span class="mpss-io-name">{name}</span>'
            f'<span class="mpss-io-val">{1 if on else 0}</span>'
            f"</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def render_io_panel(bridge) -> None:
    """Raw values on the wire (registers/coils or Logix tags)."""
    driver = getattr(bridge, "driver", "modbus")
    label = getattr(bridge, "target_label", f"{bridge.host}:{bridge.port}")
    if driver == "logix":
        title = "EtherNet/IP — live tags"
        in_hint = "MPSS → PLC (written tags)"
        out_hint = "PLC → MPSS (read tags)"
        in_prefix = out_prefix = ""
    else:
        title = "Modbus link — live IO"
        in_hint = "MPSS → PLC (holding registers)"
        out_hint = "PLC → MPSS (coils)"
        in_prefix, out_prefix = "HR", "Coil"

    st.markdown(f"#### {title}")
    if bridge.state.last_io_at:
        age_s = time.time() - bridge.state.last_io_at
        st.caption(f"{label} · last poll {age_s:.1f}s ago")
    else:
        st.caption(f"Not connected yet — {label}")

    col_in, col_out = st.columns(2)
    with col_in:
        st.markdown(f'<p class="mpss-hint">{in_hint}</p>', unsafe_allow_html=True)
        st.markdown(
            _io_rows_html(bridge.state.holding_registers, addr_prefix=in_prefix),
            unsafe_allow_html=True,
        )
    with col_out:
        st.markdown(f'<p class="mpss-hint">{out_hint}</p>', unsafe_allow_html=True)
        st.markdown(
            _io_rows_html(bridge.state.coils, addr_prefix=out_prefix),
            unsafe_allow_html=True,
        )


def render_demo_script() -> None:
    st.markdown(
        """
        <div class="mpss-script">
          <strong>Demo script (FDS)</strong>
          <ol>
            <li><strong>Normal</strong> — valve open → Start → wait ~4s → RUNNING + pressure OK</li>
            <li><strong>Fault</strong> — Reset sim → close valve → Start → start blocked</li>
            <li><strong>Recovery</strong> — open valve → Reset → Start → RUNNING again</li>
            <li><strong>Optional</strong> — while RUNNING, Inject pump trip → FAULT</li>
          </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )
