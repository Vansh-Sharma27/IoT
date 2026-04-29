# Raspberry Pi provisioning

For Raspberry Pi 4 Model B running our surveillance robot client.

## 1. Flash the SD card

Use Raspberry Pi Imager. Pick **Raspberry Pi OS Lite (64-bit, Bookworm)** — we
do not need the desktop. In the imager's advanced settings (gear icon):

- Set hostname (e.g. `surveillance-bot`)
- Enable SSH with a public key
- Set Wi-Fi SSID + password
- Set locale and timezone

Eject, boot the Pi, find it on the LAN (router admin or `arp -a`), and SSH in.

## 2. Base packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git libatlas-base-dev v4l-utils
```

## 3. Tailscale

See `docs/tailscale_setup.md`.

## 4. Clone and install

```bash
git clone <repo-url> ~/IoT
cd ~/IoT/pi_client

# Bookworm forces PEP 668; use a venv to keep things clean.
python3 -m venv ~/.venvs/surveillance
source ~/.venvs/surveillance/bin/activate
pip install -r requirements.txt
# Then uncomment the Pi-only lines in requirements.txt and re-run:
pip install gpiozero lgpio
```

## 5. Configure

Edit `~/IoT/pi_client/config.yaml`:

- `pi.vm_host`: the VM's tailnet IP (run `tailscale ip -4` on the VM).
- `pi.hardware_backend`: change `mock` -> `real`.
- `gpio.*`: match the actual wiring (see pin map below).

## 6. Wiring (BCM pin numbers)

```
Raspberry Pi 4 (BCM)        Component
--------------------        -----------------------------------------
GPIO 17                     L298N IN1 (left motor forward)
GPIO 27                     L298N IN2 (left motor backward)
GPIO 18 (PWM0)              L298N ENA (left motor speed)
GPIO 22                     L298N IN3 (right motor forward)
GPIO 23                     L298N IN4 (right motor backward)
GPIO 13 (PWM1)              L298N ENB (right motor speed)
GPIO 5                      HC-SR04 TRIG (front)
GPIO 6                      HC-SR04 ECHO (front, via 1k/2k divider!)
GPIO 25                     Active buzzer +
GPIO 16                     Red LED (via 220Ω)
GPIO 20                     Green LED (via 220Ω)
GPIO 21                     Amber LED (via 220Ω)
5V (pin 2)                  L298N +5V logic / HC-SR04 VCC
GND (pin 6)                 Common ground (Pi, L298N, HC-SR04, motor PSU)
```

Power the L298N motor side from the Li-ion pack / power bank, **not** the Pi's
5V rail. Common-ground only.

USB camera plugs into any USB-2 port; check it appears with `v4l2-ctl --list-devices`.

## 7. Smoke test

```bash
source ~/.venvs/surveillance/bin/activate
cd ~/IoT
PYTHONPATH=. python3 -c "
from pi_client.config import load_config
from pi_client.hardware import build
hw = build(load_config())
print('front distance cm =', hw.front.distance_cm())
hw.alerts.led('green', 1.0)
hw.shutdown()
"
```

Expected: a distance reading and a 1-second green LED.

Bench-test motors with the wheels off the ground before driving:
```bash
PYTHONPATH=. python3 -c "
import time
from pi_client.config import load_config
from pi_client.hardware import build
hw = build(load_config())
hw.motors.forward(0.4); time.sleep(1)
hw.motors.turn_left(0.4); time.sleep(1)
hw.motors.stop(); hw.shutdown()
"
```

## 8. Run on boot (systemd)

Create `/etc/systemd/system/surveillance-robot.service`:

```ini
[Unit]
Description=Surveillance robot client
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/IoT
Environment=PYTHONPATH=/home/pi/IoT
ExecStart=/home/pi/.venvs/surveillance/bin/python -m pi_client.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now surveillance-robot
journalctl -u surveillance-robot -f
```
