"""Tests the pure ``decide()`` function and react_to() side effects with mocks."""

from __future__ import annotations

import pytest

from pi_client.config import load_config
from pi_client.hardware import build
from pi_client.main import FsmState, State, decide, react_to
from protocol import AuthResult, Decision


@pytest.fixture()
def cfg():
    return load_config()


@pytest.fixture()
def hw(cfg, monkeypatch):
    monkeypatch.setattr(cfg.pi, "hardware_backend", "mock")  # frozen dataclass; let's just rebuild
    return build(cfg)


def test_clear_path_drives_forward(cfg):
    s, a = decide(FsmState(), distance_cm=200.0, now=0.0, cfg=cfg)
    assert a.motors == "forward"
    assert a.speed == cfg.control.forward_speed
    assert s.stable_since is None


def test_obstacle_turns_away(cfg):
    s, a = decide(FsmState(last_distance=50.0), distance_cm=15.0, now=0.0, cfg=cfg)
    assert a.motors in ("left", "right")
    assert a.speed == cfg.control.turn_speed
    assert s.stable_since is None


def test_target_in_range_starts_stability_clock(cfg):
    s, a = decide(FsmState(), distance_cm=60.0, now=10.0, cfg=cfg)
    assert s.stable_since == 10.0
    assert a.motors == "forward"
    assert a.do_capture is False


def test_target_held_long_enough_triggers_capture(cfg):
    s1, _ = decide(FsmState(), distance_cm=60.0, now=10.0, cfg=cfg)
    s2, _ = decide(s1, distance_cm=60.5, now=10.5, cfg=cfg)
    s3, a3 = decide(s2, distance_cm=60.5, now=11.5, cfg=cfg)
    assert s3.state == State.CAPTURE
    assert a3.do_capture is True
    assert a3.motors == "stop"


def test_distance_jump_resets_stability(cfg):
    s1, _ = decide(FsmState(), distance_cm=60.0, now=0.0, cfg=cfg)
    s2, a2 = decide(s1, distance_cm=40.0, now=0.5, cfg=cfg)  # > stable_delta_cm jump
    assert s2.stable_since == 0.5
    assert a2.do_capture is False


def test_cooldown_skips_capture_until_expired(cfg):
    state = FsmState(state=State.COOLDOWN, cooldown_until=10.0)
    s1, a1 = decide(state, distance_cm=60.0, now=5.0, cfg=cfg)
    assert s1.state == State.COOLDOWN
    assert a1.do_capture is False
    s2, a2 = decide(state, distance_cm=60.0, now=11.0, cfg=cfg)
    assert s2.state == State.WANDER


def test_react_allowed(cfg):
    hw = build(cfg)
    react_to(AuthResult(Decision.ALLOWED, name="A", similarity=0.9), hw)
    assert ("green", 2.0) in hw.alerts.led_history
    assert hw.alerts.buzz_history == []


def test_react_denied(cfg):
    hw = build(cfg)
    react_to(AuthResult(Decision.DENIED, reason="unknown_face"), hw)
    assert hw.alerts.buzz_history == [3]
    assert any(c == "red" for c, _ in hw.alerts.led_history)


def test_react_unknown(cfg):
    hw = build(cfg)
    react_to(AuthResult(Decision.UNKNOWN, reason="no_face"), hw)
    assert any(c == "amber" for c, _ in hw.alerts.led_history)
    assert hw.alerts.buzz_history == []


def test_react_non_human(cfg):
    hw = build(cfg)
    react_to(AuthResult(Decision.NON_HUMAN), hw)
    assert hw.alerts.led_history == []
    assert hw.alerts.buzz_history == []


def test_react_to_none_means_vm_unreachable(cfg):
    hw = build(cfg)
    react_to(None, hw)
    assert any(c == "amber" for c, _ in hw.alerts.led_history)
