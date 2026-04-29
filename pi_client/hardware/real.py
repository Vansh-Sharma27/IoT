"""Real hardware backends. Imported only when hardware_backend == "real".

Requires gpiozero + lgpio (install on the Pi via the Pi-only extras).
Not exercised on the VM — wiring will be smoke-tested on first power-up.
"""

from __future__ import annotations

import logging
import time
from threading import Thread

import cv2

from pi_client.hardware import Alerts, Camera, Motors, Ultrasonic

log = logging.getLogger(__name__)


class RealMotors(Motors):
    """L298N driver via gpiozero.Motor. Each side has a forward/backward pin
    pair and a hardware-PWM enable pin for speed control."""

    def __init__(self, pins: dict) -> None:
        from gpiozero import Motor, PWMOutputDevice

        self._left = Motor(forward=pins["left_forward"], backward=pins["left_backward"])
        self._right = Motor(forward=pins["right_forward"], backward=pins["right_backward"])
        self._left_pwm = PWMOutputDevice(pins["left_pwm"])
        self._right_pwm = PWMOutputDevice(pins["right_pwm"])

    def _pwm(self, speed: float) -> None:
        s = max(0.0, min(1.0, float(speed)))
        self._left_pwm.value = s
        self._right_pwm.value = s

    def forward(self, speed: float) -> None:
        self._pwm(speed)
        self._left.forward()
        self._right.forward()

    def backward(self, speed: float) -> None:
        self._pwm(speed)
        self._left.backward()
        self._right.backward()

    def turn_left(self, speed: float) -> None:
        self._pwm(speed)
        self._left.backward()
        self._right.forward()

    def turn_right(self, speed: float) -> None:
        self._pwm(speed)
        self._left.forward()
        self._right.backward()

    def stop(self) -> None:
        self._left.stop()
        self._right.stop()
        self._pwm(0.0)


class RealUltrasonic(Ultrasonic):
    """HC-SR04 with a 5-sample median for noise rejection."""

    def __init__(self, pins: dict) -> None:
        from gpiozero import DistanceSensor
        self._sensor = DistanceSensor(echo=pins["echo"], trigger=pins["trigger"], max_distance=2.0)

    def distance_cm(self) -> float:
        samples = [self._sensor.distance for _ in range(5)]
        samples.sort()
        return float(samples[2]) * 100.0


class RealCamera(Camera):
    def __init__(self, device_index: int, width: int, height: int, jpeg_quality: int) -> None:
        self.jpeg_quality = jpeg_quality
        self._cap = cv2.VideoCapture(device_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open camera device {device_index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def grab_jpeg(self) -> bytes:
        for _ in range(2):
            self._cap.grab()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("camera read failed")
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            raise RuntimeError("jpeg encode failed")
        return buf.tobytes()

    def close(self) -> None:
        self._cap.release()


class RealAlerts(Alerts):
    def __init__(self, buzzer: int, led_red: int, led_green: int, led_amber: int) -> None:
        from gpiozero import Buzzer, LED
        self._buzzer = Buzzer(buzzer)
        self._leds = {
            "red": LED(led_red),
            "green": LED(led_green),
            "amber": LED(led_amber),
        }

    def led(self, color: str, seconds: float = 0.0) -> None:
        led = self._leds.get(color)
        if led is None:
            log.warning("unknown LED colour: %s", color)
            return
        for other in self._leds.values():
            if other is not led:
                other.off()
        led.on()
        if seconds > 0:
            def off_later():
                time.sleep(seconds)
                led.off()
            Thread(target=off_later, daemon=True).start()

    def buzzer(self, beeps: int) -> None:
        def run():
            for _ in range(int(beeps)):
                self._buzzer.on()
                time.sleep(0.15)
                self._buzzer.off()
                time.sleep(0.1)
        Thread(target=run, daemon=True).start()
