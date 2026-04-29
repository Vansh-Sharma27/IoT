"""Hardware abstraction layer.

Two backends:
  - "mock":  pure-Python stubs. Lets the state machine run on the VM for
             integration testing without GPIO / camera / motors.
  - "real":  gpiozero + OpenCV USB capture. Imported lazily so the VM never
             needs gpiozero installed.

The state machine in ``pi_client.main`` only ever talks to the four ABC
interfaces below. Adding a Hailo accelerator or swapping the L298N for a
TB6612 later means writing a new backend, not editing the state machine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from pi_client.config import Config

log = logging.getLogger(__name__)


class Motors(ABC):
    @abstractmethod
    def forward(self, speed: float) -> None: ...
    @abstractmethod
    def backward(self, speed: float) -> None: ...
    @abstractmethod
    def turn_left(self, speed: float) -> None: ...
    @abstractmethod
    def turn_right(self, speed: float) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...


class Ultrasonic(ABC):
    @abstractmethod
    def distance_cm(self) -> float: ...


class Camera(ABC):
    @abstractmethod
    def grab_jpeg(self) -> bytes: ...
    @abstractmethod
    def close(self) -> None: ...


class Alerts(ABC):
    @abstractmethod
    def led(self, color: str, seconds: float = 0.0) -> None: ...
    @abstractmethod
    def buzzer(self, beeps: int) -> None: ...


class HardwareBundle:
    def __init__(self, motors: Motors, front: Ultrasonic, camera: Camera, alerts: Alerts):
        self.motors = motors
        self.front = front
        self.camera = camera
        self.alerts = alerts

    def shutdown(self) -> None:
        try:
            self.motors.stop()
        finally:
            self.camera.close()


def build(cfg: Config) -> HardwareBundle:
    backend = cfg.pi.hardware_backend
    if backend == "mock":
        from pi_client.hardware.mock import (
            MockMotors, MockUltrasonic, MockCamera, MockAlerts,
        )
        log.info("hardware backend: MOCK")
        return HardwareBundle(
            motors=MockMotors(),
            front=MockUltrasonic(),
            camera=MockCamera(width=cfg.camera.width, height=cfg.camera.height,
                              jpeg_quality=cfg.camera.jpeg_quality),
            alerts=MockAlerts(),
        )
    if backend == "real":
        from pi_client.hardware.real import (
            RealMotors, RealUltrasonic, RealCamera, RealAlerts,
        )
        log.info("hardware backend: REAL (Pi GPIO + USB camera)")
        return HardwareBundle(
            motors=RealMotors(cfg.gpio.raw["motors"]),
            front=RealUltrasonic(cfg.gpio.raw["ultrasonic_front"]),
            camera=RealCamera(
                cfg.camera.device_index, cfg.camera.width, cfg.camera.height,
                cfg.camera.jpeg_quality,
            ),
            alerts=RealAlerts(
                buzzer=cfg.gpio.raw["buzzer"],
                led_red=cfg.gpio.raw["led_red"],
                led_green=cfg.gpio.raw["led_green"],
                led_amber=cfg.gpio.raw["led_amber"],
            ),
        )
    raise ValueError(f"unknown hardware backend: {backend!r}")
