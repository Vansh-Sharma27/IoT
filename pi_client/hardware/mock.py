"""Mock hardware backends — used on the VM for integration testing."""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np

from pi_client.hardware import Alerts, Camera, Motors, Ultrasonic

log = logging.getLogger(__name__)


class MockMotors(Motors):
    def __init__(self) -> None:
        self.last: tuple[str, float] = ("stop", 0.0)

    def forward(self, speed: float) -> None:
        self.last = ("forward", speed)
        log.debug("mock motors: forward %.2f", speed)

    def backward(self, speed: float) -> None:
        self.last = ("backward", speed)
        log.debug("mock motors: backward %.2f", speed)

    def turn_left(self, speed: float) -> None:
        self.last = ("left", speed)
        log.debug("mock motors: left %.2f", speed)

    def turn_right(self, speed: float) -> None:
        self.last = ("right", speed)
        log.debug("mock motors: right %.2f", speed)

    def stop(self) -> None:
        self.last = ("stop", 0.0)
        log.debug("mock motors: stop")


class MockUltrasonic(Ultrasonic):
    """Returns a programmable distance. Tests inject a sequence by assigning
    ``feed`` to a list; pop()-ed values are returned in order, then the last
    value persists. Default is 200 cm (clear ahead)."""

    def __init__(self) -> None:
        self.feed: list[float] = []
        self._last: float = 200.0

    def distance_cm(self) -> float:
        if self.feed:
            self._last = float(self.feed.pop(0))
        return self._last


class MockCamera(Camera):
    def __init__(self, width: int = 640, height: int = 480, jpeg_quality: int = 80) -> None:
        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality
        self.grabs = 0

    def grab_jpeg(self) -> bytes:
        self.grabs += 1
        img = np.random.default_rng(self.grabs).integers(
            0, 255, (self.height, self.width, 3), dtype=np.uint8
        )
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        assert ok
        return buf.tobytes()

    def close(self) -> None:
        pass


class MockAlerts(Alerts):
    def __init__(self) -> None:
        self.led_history: list[tuple[str, float]] = []
        self.buzz_history: list[int] = []

    def led(self, color: str, seconds: float = 0.0) -> None:
        log.info("mock alert: led=%s for %.1fs", color, seconds)
        self.led_history.append((color, seconds))

    def buzzer(self, beeps: int) -> None:
        log.info("mock alert: buzzer x%d", beeps)
        self.buzz_history.append(beeps)
