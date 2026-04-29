"""Surveillance robot state machine.

States:
    WANDER   — drive forward; turn away from close obstacles; if a target is
               held within trigger_distance for stable_seconds, go to CAPTURE.
    CAPTURE  — stop, grab a JPEG, ask the VM. Act on the result, then return
               to WANDER with a short cool-down so we don't re-fire on the
               same person.

The state machine is structured around a pure ``decide()`` function so that
``test_state_machine.py`` can drive it deterministically without sleeping.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, replace
from enum import Enum
from random import choice
from typing import Optional

from pi_client.client import VisionClient
from pi_client.config import Config, load_config
from pi_client.hardware import HardwareBundle, build
from protocol import AuthResult, Decision

log = logging.getLogger(__name__)


class State(str, Enum):
    WANDER = "wander"
    CAPTURE = "capture"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class FsmState:
    state: State = State.WANDER
    stable_since: Optional[float] = None
    last_distance: Optional[float] = None
    cooldown_until: float = 0.0


@dataclass(frozen=True)
class Action:
    motors: str            # "forward" | "stop" | "back" | "left" | "right"
    speed: float = 0.0
    do_capture: bool = False


def decide(prev: FsmState, distance_cm: float, now: float, cfg: Config) -> tuple[FsmState, Action]:
    """Pure transition: (state, sensor reading, time, config) -> (new state, action).

    Has no side effects; ``main_loop`` actually drives the motors / camera.
    """
    c = cfg.control

    if prev.state == State.COOLDOWN:
        if now >= prev.cooldown_until:
            return replace(prev, state=State.WANDER, stable_since=None, last_distance=None), \
                   Action(motors="forward", speed=c.forward_speed)
        return prev, Action(motors="forward", speed=c.forward_speed)

    if distance_cm < c.obstacle_distance_cm:
        # Wall-style obstacle: turn away, reset stability tracking.
        direction = choice(["left", "right"])
        return replace(prev, state=State.WANDER, stable_since=None, last_distance=distance_cm), \
               Action(motors=direction, speed=c.turn_speed)

    if distance_cm < c.trigger_distance_cm:
        # Something interesting in front.
        if prev.last_distance is None or abs(distance_cm - prev.last_distance) > c.stable_delta_cm:
            return replace(prev, state=State.WANDER, stable_since=now, last_distance=distance_cm), \
                   Action(motors="forward", speed=c.forward_speed * 0.5)
        held = now - (prev.stable_since or now)
        if held >= c.stable_seconds:
            return replace(prev, state=State.CAPTURE, last_distance=distance_cm), \
                   Action(motors="stop", do_capture=True)
        return replace(prev, last_distance=distance_cm), \
               Action(motors="forward", speed=c.forward_speed * 0.5)

    return replace(prev, stable_since=None, last_distance=distance_cm), \
           Action(motors="forward", speed=c.forward_speed)


def apply_motors(hw: HardwareBundle, action: Action) -> None:
    if action.motors == "forward":
        hw.motors.forward(action.speed)
    elif action.motors == "back":
        hw.motors.backward(action.speed)
    elif action.motors == "left":
        hw.motors.turn_left(action.speed)
    elif action.motors == "right":
        hw.motors.turn_right(action.speed)
    else:
        hw.motors.stop()


def react_to(result: Optional[AuthResult], hw: HardwareBundle) -> None:
    if result is None:
        log.warning("auth call failed — VM unreachable")
        hw.alerts.led("amber", 1.0)
        return
    log.info("auth result: %s name=%s sim=%s reason=%s",
             result.decision.value, result.name, result.similarity, result.reason)
    if result.decision == Decision.ALLOWED:
        hw.alerts.led("green", 2.0)
    elif result.decision == Decision.DENIED:
        hw.alerts.buzzer(3)
        hw.alerts.led("red", 5.0)
        hw.motors.backward(0.4)
        time.sleep(0.5)
    elif result.decision == Decision.UNKNOWN:
        hw.alerts.led("amber", 1.0)
    elif result.decision == Decision.NON_HUMAN:
        pass


def main_loop(cfg: Config, hw: HardwareBundle, client: VisionClient) -> None:
    state = FsmState()
    log.info("starting main loop; tick=%.3fs", cfg.control.tick_seconds)
    while True:
        now = time.monotonic()
        dist = hw.front.distance_cm()
        state, action = decide(state, dist, now, cfg)
        apply_motors(hw, action)
        if action.do_capture:
            jpeg = hw.camera.grab_jpeg()
            result = client.authenticate(jpeg)
            react_to(result, hw)
            state = FsmState(
                state=State.COOLDOWN,
                cooldown_until=time.monotonic() + cfg.control.retry_after_capture_seconds,
            )
        time.sleep(cfg.control.tick_seconds)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    log.info("connecting to VM at %s:%d", cfg.pi.vm_host, cfg.pi.vm_port)
    client = VisionClient(cfg.pi.vm_host, cfg.pi.vm_port)
    if client.ping():
        log.info("VM reachable")
    else:
        log.warning("VM not reachable yet — will keep retrying in background")

    hw = build(cfg)
    try:
        main_loop(cfg, hw, client)
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        hw.shutdown()
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
