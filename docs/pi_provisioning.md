# Raspberry Pi provisioning

For Raspberry Pi 4 Model B running our surveillance robot client.
Tested on **Raspberry Pi OS Lite (64-bit, Trixie / Debian 13)** with Python 3.13.

## 1. Flash the SD card

Use Raspberry Pi Imager. Pick **Raspberry Pi OS Lite (64-bit, Trixie)** — we
do not need the desktop. In the imager's advanced settings (gear icon):

- Set hostname (e.g. `surveillance-bot`)
- Enable SSH with a public key
- Set Wi-Fi SSID + password
- Set locale and timezone

Eject, boot the Pi, find it on the LAN (router admin or `arp -a`), and SSH in.

## 2. Base packages

```bash
sudo apt update && sudo apt upgrade -y
# libopenblas-dev replaces libatlas-base-dev (dropped in Trixie)
# python3-lgpio / python3-gpiozero: pip build of lgpio requires liblgpio.so
#   which isn't packaged separately; use distro packages instead.
sudo apt install -y python3-pip python3-venv git \
     libopenblas-dev v4l-utils swig \
     python3-lgpio python3-gpiozero
```

## 3. Network transport

The Pi reaches the VM over a public Cloudflare Quick Tunnel URL — there is
nothing to install on the Pi for transport, just `requests` (already in
`pi_client/requirements.txt`). See `docs/cloudflare_tunnel.md` for the
VM-side setup.

## 4. Clone and install

```bash
git clone <repo-url> ~/IoT
cd ~/IoT/pi_client

# --system-site-packages lets the venv see python3-lgpio and python3-gpiozero
# installed above; without it those packages are invisible inside the venv.
python3 -m venv --system-site-packages ~/.venvs/surveillance
source ~/.venvs/surveillance/bin/activate
pip install -r requirements.txt
# gpiozero and lgpio are already present via system packages — no extra pip step.
```

## 5. Configure

Edit `~/IoT/pi_client/config.yaml`:

- `pi.vm_url`: the public `https://*.trycloudflare.com` URL printed by
  `cloudflared` on the VM.
- `pi.vm_token`: the bearer token (must match `vm_server/config.yaml::server.secret_token`).
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
After=network-online.target
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
