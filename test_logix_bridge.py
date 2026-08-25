"""Unit tests for Logix path helper and bridge factory (no PLC required)."""

from __future__ import annotations

from io_map import DEFAULT_HOST, DEFAULT_LOGIX_TAGS, DEFAULT_PORT, DRIVER_LOGIX, HR_BASE
from logix_bridge import LogixPlcBridge, build_logix_path
from plc_bridge import HmiPulseMixin, ModbusPlcBridge, PlcTarget, create_bridge
from simulation import PlantFeedback


def test_l84es_embedded_ethernet_is_ip_only() -> None:
    assert build_logix_path("192.168.1.10", slot=0) == "192.168.1.10"


def test_en2t_path_includes_slot() -> None:
    assert build_logix_path("192.168.1.10", slot=2) == "192.168.1.10/2"


def test_custom_cip_path_wins() -> None:
    assert build_logix_path("192.168.1.10", slot=2, cip_path="1.2.3.4/1") == "1.2.3.4/1"


def test_create_bridge_defaults_to_modbus() -> None:
    bridge = create_bridge(PlcTarget())
    assert isinstance(bridge, ModbusPlcBridge)
    assert bridge.host == DEFAULT_HOST
    assert bridge.port == DEFAULT_PORT
    assert bridge.hr_base == HR_BASE
    bridge.close()


def test_create_logix_bridge_without_connecting() -> None:
    target = PlcTarget(driver=DRIVER_LOGIX, host="10.0.0.5", slot=0)
    bridge = create_bridge(target)
    assert bridge.driver == DRIVER_LOGIX
    assert bridge.path == "10.0.0.5"
    assert bridge.tags["OP_START"] == "MPSS_OP_START"
    bridge.close()


def test_hmi_pulse_stays_true_after_note_ops_sent() -> None:
    class Dummy(HmiPulseMixin):
        def __init__(self) -> None:
            from plc_bridge import BridgeState

            self.state = BridgeState()
            self._init_hmi_pulse()

    dummy = Dummy()
    dummy.operator_start()
    assert dummy._op_bits()["start"]
    dummy._note_ops_sent()
    assert dummy.has_held_ops()
    assert dummy._op_bits()["start"]


def test_disabled_logix_does_not_open_a_session() -> None:
    bridge = LogixPlcBridge("10.0.0.1")
    commands = bridge.step(PlantFeedback())
    assert not commands.pump_start_cmd
    assert "Connect" in bridge.state.last_message
    assert bridge._client is None
    bridge.close()


def test_empty_tag_names_are_rejected() -> None:
    tags = {name: "" for name in DEFAULT_LOGIX_TAGS}
    bridge = LogixPlcBridge("10.0.0.1", tags=tags)
    bridge.set_enabled(True)
    commands = bridge.step(PlantFeedback())
    assert not commands.pump_start_cmd
    assert "Empty tag name" in bridge.state.last_message
    assert bridge._client is None
    bridge.close()
