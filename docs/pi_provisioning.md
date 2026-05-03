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

The repo ships a template at `pi_client/config.yaml.example`. Copy it
to the live location (the `setup.sh` script does this for you):

```bash
cp ~/IoT/pi_client/config.yaml.example ~/IoT/pi_client/config.yaml
```

Then edit `~/IoT/pi_client/config.yaml`:

- `pi.vm_url`: the public `https://*.trycloudflare.com` URL printed by
  `cloudflared` on the VM.
- `pi.vm_token`: the bearer token (must match `vm_server/config.yaml::server.secret_token`).
- `pi.hardware_backend`: `real` on the Pi (the example already defaults to this).
- `gpio.*`: match the actual wiring (see pin map below).

## 6. Wiring (BCM pin numbers)

> **Hardware note (this build):** 4 wheels = 4 DC motors (12 V, 30 rpm) but
> only **one working L298N**. The fix: each L298N channel drives **two
> motors in parallel** — both left motors share Channel A, both right
> motors share Channel B. Both motors on a side then turn together,
> giving us a tank-style 2-side drive on a 4-wheel chassis. The
> `RealMotors` class in `pi_client/hardware/real.py` already speaks this
> 2-channel API, so no code changes are needed.

```
Raspberry Pi 4 (BCM)        L298N (single board) / component
--------------------        -----------------------------------------
GPIO 17                     IN1 — LEFT side forward
GPIO 27                     IN2 — LEFT side backward
GPIO 18 (PWM0)              ENA — LEFT side speed (PWM)
GPIO 22                     IN3 — RIGHT side forward
GPIO 23                     IN4 — RIGHT side backward
GPIO 13 (PWM1)              ENB — RIGHT side speed (PWM)
GPIO 5                      HC-SR04 TRIG (front)
GPIO 6                      HC-SR04 ECHO (front, via 1k/2k divider!)
GPIO 25                     Active buzzer +
GPIO 16                     Red LED (via 220Ω)
GPIO 20                     Green LED (via 220Ω)
GPIO 21                     Amber LED (via 220Ω)
5V (pin 2)                  L298N +5V logic / HC-SR04 VCC
GND (pin 6)                 Common ground (Pi, L298N, HC-SR04, motor PSU)

L298N output side:
OUT1, OUT2  ->  front-LEFT motor + rear-LEFT  motor (both wired in PARALLEL)
OUT3, OUT4  ->  front-RIGHT motor + rear-RIGHT motor (both wired in PARALLEL)
```

**Motor power & current.** Power the L298N motor side from the 12 V
pack, **not** from the Pi's 5V rail. Common-ground only. Each L298N
channel is rated 2 A continuous (3 A peak). With two 12 V 30 rpm
gearmotors paralleled per channel expect ~0.4–0.6 A running and up
to ~1.2 A on stall — within spec but at the higher end. Use 22 AWG
or thicker for the motor wires and **remove the L298N's onboard 5V
regulator jumper** if your supply is >12 V.

**Voltage drop.** L298N H-bridge drops ~1.5–2 V end-to-end, so 12 V
into the L298N gives ~10 V at the motors. Expected: slightly slower
than rated 30 rpm. Fine for a slow wandering robot.

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

The unit file lives in the repo at
`pi_client/deploy/surveillance-robot.service`. Install it:

```bash
sudo install -m 644 ~/IoT/pi_client/deploy/surveillance-robot.service \
    /etc/systemd/system/surveillance-robot.service
sudo systemctl daemon-reload
sudo systemctl enable --now surveillance-robot
journalctl -u surveillance-robot -f
```

> The one-shot `bash ~/IoT/pi_client/deploy/setup.sh` script does
> everything in §2–§5 and §8 in one go (apt install, venv, pip,
> config template copy, install systemd unit). Run it instead of
> doing each step by hand if you prefer.
