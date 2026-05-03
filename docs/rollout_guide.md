# Rollout guide

End-to-end checklist for taking the codebase from "tests pass on the VM" to
"robot drives around the lab and authenticates visitors". The transport is
**FastAPI on the VM, exposed via a Cloudflare Quick Tunnel**, and the Pi
talks to the public `https://*.trycloudflare.com` URL over HTTPS. There is
nothing to install on the Pi for transport — `requests` is already in
`pi_client/requirements.txt`.

## Friend's first-boot checklist (Pi side, after `git clone`)

This is the short version for the team-mate setting up the Pi. Detailed
explanation is in `docs/pi_provisioning.md`.

```bash
git clone <repo-url> ~/IoT
bash ~/IoT/pi_client/deploy/setup.sh        # apt + venv + pip + systemd unit install
# Edit pi_client/config.yaml: pi.vm_url, pi.vm_token, gpio.* (if rewired).
sudo systemctl enable --now surveillance-robot
journalctl -u surveillance-robot -f
```

Wire 4 motors across the **single** L298N as paired sides (both left motors
in parallel on Channel A; both right in parallel on Channel B). Full pin
map in `docs/pi_provisioning.md` §6.

> **Calibration is currently skipped.** We have only 1 photo per enrolled
> person, but `vm_server/calibrate_threshold.py` needs ≥2. The bootstrap
> threshold of 0.50 in `vm_server/config.yaml.example` is shipped as-is.
> If FAR/FRR is bad in the lab, capture 2-3 photos per person with the
> webcam and re-run `python -m vm_server.calibrate_threshold`.

> **Pipeline gating caveat (verified 2026-05-03 against 18 random web
> images):** The pipeline runs YOLOv8n at `yolo_person_conf=0.5` *before*
> the face model, so an image with no detected `person` bbox short-circuits
> to `NON_HUMAN` and the face model never runs. This is fine for the bot's
> operational scenario — at the ~80 cm trigger distance the USB camera
> captures upper-body, which YOLO detects reliably — but tight headshots
> (cropped to face only, no shoulders) are mis-classified as `NON_HUMAN`.
> If you observe spurious `non_human` decisions in the lab, lower
> `models.yolo_person_conf` to `0.3` in `vm_server/config.yaml`. Verified
> behaviour on the test set:
>
> | Input bucket | n | Pipeline output |
> |---|---|---|
> | Enrolled face photos | 3 | 3× `ALLOWED` with correct name, similarity ≈ 1.0 |
> | Random unknown faces (mid-shot) | 4 | 4× `DENIED` `unknown_face` |
> | Empty chairs / landscapes | 3 | 3× `NON_HUMAN` `no_person_bbox` |
> | Animal close-ups (cat / dog) | 3 | 3× `NON_HUMAN` `no_person_bbox` |
> | Group photos with small/distant faces | 3 | 2× `UNKNOWN` `no_face`, 1× `NON_HUMAN` |
> | Tight sunglasses headshots | 2 | 2× `NON_HUMAN` (false negative — see above) |

The rest of this document covers the original phased rollout and is kept
for reference.

---

## Phase A — bring up the Pi without the camera

### A1. VM: start the service and the Cloudflare tunnel

```bash
[VM] cd ~/IoT
# One-time: generate a bearer token, paste it into vm_server/config.yaml
[VM] openssl rand -hex 24
# Edit vm_server/config.yaml::server.secret_token (must NOT be CHANGE_ME)

# Start FastAPI on 127.0.0.1:8000
[VM] PYTHONPATH=. python3 -m vm_server.http_server &

# In a second shell on the VM, open the tunnel.
# It prints a public https://*.trycloudflare.com URL — copy it; call it $VM_URL.
[VM] cloudflared tunnel --url http://127.0.0.1:8000
```

If `cloudflared` is missing, install it per `docs/cloudflare_tunnel.md`. For a
service that survives reboots, install the systemd unit from that doc instead
of running `cloudflared` by hand.

Smoke-check from anywhere with internet:

```bash
curl $VM_URL/ping
# {"ok":true,"service":"surveillance-vision"}
```

### A2. Install the repo on the Pi

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git \
     libopenblas-dev v4l-utils swig \
     python3-lgpio python3-gpiozero

git clone <your-repo-url> ~/IoT
cd ~/IoT

# --system-site-packages exposes python3-lgpio and python3-gpiozero inside the venv.
python3 -m venv --system-site-packages ~/.venvs/surveillance
source ~/.venvs/surveillance/bin/activate

pip install -r pi_client/requirements.txt
# gpiozero and lgpio come from the system install above — no separate pip step.
```

`lgpio` is the right backend for Trixie; `RPi.GPIO` is deprecated and
should NOT be installed. `libatlas-base-dev` was dropped in Trixie —
`libopenblas-dev` is the replacement for any numpy/scipy native extensions.

### A3. Configure the Pi client

Edit `~/IoT/pi_client/config.yaml`:

```yaml
pi:
  vm_url: "<paste $VM_URL from step A1>"      # https://*.trycloudflare.com
  vm_token: "<same value as vm_server config secret_token>"
  hardware_backend: "mock"      # keep mock until Phase A4 passes; switch to "real" in A5
```

Leave the `gpio:` and `control:` blocks at their defaults for now. Pin map
matches `docs/pi_provisioning.md`.

### A4. Smoke-test the HTTPS link from the Pi (mock hardware)

```bash
cd ~/IoT
source ~/.venvs/surveillance/bin/activate

# Raw ping — proves the public tunnel + bearer auth.
PYTHONPATH=. python3 -c "
import requests, yaml
cfg = yaml.safe_load(open('pi_client/config.yaml'))['pi']
r = requests.get(cfg['vm_url'] + '/ping', timeout=10,
                 headers={'Authorization': 'Bearer ' + cfg['vm_token']})
print(r.status_code, r.json())
"
# Expected: 200 {'ok': True, 'service': 'surveillance-vision'}
```

Now run the full Pi state machine in mock mode. The mock camera generates
random JPEGs, so `authenticate()` will return `non_human` (YOLO sees no person)
— that's fine; the goal here is to prove the loop runs without crashing and
the JSON deserialises correctly.

```bash
PYTHONPATH=. python3 -m pi_client.main
```

You should see log lines like:

```
INFO pi_client.main: connecting to VM at https://<random>.trycloudflare.com
INFO pi_client.main: VM reachable
INFO pi_client.main: starting main loop; tick=0.050s
INFO pi_client.main: auth result: non_human name=None sim=None reason=no_person_bbox
```

`Ctrl+C` to stop. If you see `auth call failed — VM unreachable`, run the
`/ping` curl from A1 and confirm both the URL and bearer token are correct in
`pi_client/config.yaml`.

### A5. Hardware bring-up (no camera)

Wire the L298N, HC-SR04, buzzer, and three LEDs per the BCM pin table in
`docs/pi_provisioning.md`. Check each subsystem **with wheels off the
ground** before driving.

Switch the Pi config to real hardware:

```yaml
pi:
  hardware_backend: "real"
```

#### A5a. Ultrasonic sanity check

```bash
PYTHONPATH=. python3 -c "
from pi_client.config import load_config
from pi_client.hardware import build
hw = build(load_config())
for _ in range(5):
    print('front cm =', hw.front.distance_cm())
hw.shutdown()
"
```

Move your hand 10 cm and 100 cm from the sensor — values should change
accordingly. **If the ECHO line is wired straight to a 5 V output, you will
fry the GPIO** — use the 1 kΩ / 2 kΩ divider noted in the wiring doc.

#### A5b. LEDs and buzzer

```bash
PYTHONPATH=. python3 -c "
import time
from pi_client.config import load_config
from pi_client.hardware import build
hw = build(load_config())
for c in ('red', 'green', 'amber'):
    print(c); hw.alerts.led(c, 0.5); time.sleep(0.7)
print('buzz x2'); hw.alerts.buzzer(2)
hw.shutdown()
"
```

Each LED should light for 0.5 s in sequence; buzzer should beep twice.

#### A5c. Motors (wheels OFF the ground)

```bash
PYTHONPATH=. python3 -c "
import time
from pi_client.config import load_config
from pi_client.hardware import build
hw = build(load_config())
hw.motors.forward(0.4);   time.sleep(0.8)
hw.motors.backward(0.4);  time.sleep(0.8)
hw.motors.turn_left(0.4); time.sleep(0.8)
hw.motors.turn_right(0.4);time.sleep(0.8)
hw.motors.stop();         hw.shutdown()
"
```

Both wheels should spin in matching directions for forward/back, and in
opposing directions for left/right. If one wheel runs the wrong way, swap
that motor's two L298N output wires (or swap IN1/IN2 — software-side, just
flip the pins in `config.yaml > gpio.left_motor_in1/in2`).

### A6. Closed-loop run (camera-less, expect NON_HUMAN every cycle)

With everything wired and `hardware_backend: real`, but **no camera attached**,
running `pi_client.main` will fail at `cv2.VideoCapture` when it first tries
to capture. Two options:

1. **Skip Phase A6.** Move to Phase B once the camera is on hand.
2. **Temporarily fall back to mock camera while keeping real motors/sensors.**
   Easiest patch: in `pi_client/hardware/__init__.py`'s `build()`, force
   `camera = MockCamera()` while leaving `motors`/`front`/`alerts` real.
   Don't commit this — it's a bench hack.

The "right" option is #1: we already proved the RPC loop in A4 (mock hardware)
and the hardware in A5 (no camera). Camera + faces is Phase B.

---

## Phase B — once the USB camera arrives

### B1. Plug in and identify the camera

```bash
v4l2-ctl --list-devices
# Look for /dev/video0 (or whatever index the cam landed on).
# If multiple devices appear, set pi_client/config.yaml > pi.camera_index
# to match. (Default is 0.)
```

Quick visual check (capture one frame to disk):

```bash
PYTHONPATH=. python3 -c "
from pi_client.config import load_config
from pi_client.hardware import build
hw = build(load_config())
jpeg = hw.camera.grab_jpeg()
open('/tmp/cam_test.jpg','wb').write(jpeg)
print('wrote', len(jpeg), 'bytes')
hw.shutdown()
" && ls -lh /tmp/cam_test.jpg
```

`scp` it to your laptop and confirm the image isn't black, blurry, or
upside-down. If the camera mounts upside-down on the chassis, rotate in
software inside `RealCamera.grab_jpeg()` (cv2.flip).

### B2. Enroll team members (run on the VM)

For each person, take 1 clean front-facing photo (good light, single face,
no sunglasses). Copy them to the VM, then:

```bash
[VM] cd ~/IoT
[VM] PYTHONPATH=. python3 -m vm_server.enroll_cli \
        --name "Alice" --role allowed --image ./photos/alice.jpg
[VM] PYTHONPATH=. python3 -m vm_server.enroll_cli \
        --name "Bob"   --role allowed --image ./photos/bob.jpg
# ... repeat
```

`role` is either `allowed` (green LED, robot resumes) or `restricted`
(buzzer + red LED). Verify enrollment:

```bash
[VM] python3 -c "
import requests, yaml
cfg = yaml.safe_load(open('vm_server/config.yaml'))['server']
r = requests.get(f'http://127.0.0.1:{cfg[\"port\"]}/known',
                 headers={'Authorization': 'Bearer ' + cfg['secret_token']})
print(r.json())
"
```

### B3. Calibrate the threshold

Take **3–5 photos per person** under realistic lab lighting (different angles
+ a bit of facial expression variation). Layout:

```
~/IoT/calibration_photos/
├── Alice/
│   ├── 01.jpg
│   ├── 02.jpg
│   └── 03.jpg
└── Bob/
    ├── 01.jpg
    └── 02.jpg
```

Run the calibrator:

```bash
[VM] cd ~/IoT
[VM] PYTHONPATH=. python3 -m vm_server.calibrate_threshold \
        --photos-dir ./calibration_photos \
        --target-far 0.01 \
        --write
```

It prints the genuine vs imposter similarity distributions, picks the
smallest threshold where False Accept Rate ≤ 1%, and writes that value into
`vm_server/config.yaml`. Restart the server so the new threshold loads:

```bash
[VM] pkill -f vm_server.http_server
[VM] PYTHONPATH=. nohup python3 -m vm_server.http_server > /tmp/server.log 2>&1 &
```

### B4. Full closed-loop run

Back on the Pi:

```bash
cd ~/IoT
source ~/.venvs/surveillance/bin/activate
PYTHONPATH=. python3 -m pi_client.main
```

Walk in front of the robot at ~60 cm and stand still for ~1 s. Expected:

| Who walks up | Expected behaviour |
|---|---|
| Alice (allowed) | motors stop, green LED 2 s, then resume wandering |
| Bob (restricted) | buzzer 3 beeps + red LED 5 s + back up |
| Stranger | buzzer 3 beeps + red LED 5 s + back up |
| You hold up a chair | silent, robot resumes wandering |
| You stand at 60 cm but turn your back | amber LED 1 s (no face detected) |

If the robot fires repeatedly on the same visitor, increase
`control.retry_after_capture_seconds` in `pi_client/config.yaml` (default
should already be enough).

### B5. Run on boot (systemd)

Once you're happy with the behaviour, install the unit file shipped in
the repo:

```bash
sudo install -m 644 ~/IoT/pi_client/deploy/surveillance-robot.service \
    /etc/systemd/system/surveillance-robot.service
sudo systemctl daemon-reload
sudo systemctl enable --now surveillance-robot
journalctl -u surveillance-robot -f
```

(The `pi_client/deploy/setup.sh` one-shot script does this for you.)

---

## Troubleshooting cheat sheet

| Symptom | First thing to check |
|---|---|
| Pi `/ping` returns 401 | `vm_token` mismatch — must equal `server.secret_token` on VM |
| Pi `/ping` returns 403 | bearer token wrong; rotate via `openssl rand -hex 24` and update both configs |
| Pi `/ping` connection error | `cloudflared` died on the VM; check `journalctl -u cloudflared-quick` |
| New tunnel URL after VM reboot | Quick Tunnels are ephemeral; grep the log for the new `*.trycloudflare.com` and update `pi_client/config.yaml::pi.vm_url`, or switch to a Named Tunnel |
| Pi reaches VM but request times out | server warming up; first call is slow (~3 s) |
| `auth call failed — VM unreachable` log line | exception during call; `[VM] tail /tmp/server.log` |
| Always returns `unknown / no_face` | lighting too dark or face too small in frame |
| Always returns `non_human` | YOLO confidence too high; lower `models.yolo_person_conf` in `vm_server/config.yaml` |
| Robot fires on same person 3× in a row | `control.retry_after_capture_seconds` too short |
| Motors twitch but don't spin | L298N motor PSU not connected; common-ground missing |
| HC-SR04 reads always 0 or 200 cm | ECHO divider missing → GPIO toast; check with multimeter |

## What's NOT in this guide

- **Two extra ultrasonics on the sides:** the plan / code currently uses one
  front sensor only. If you want side sensors for smarter avoidance, extend
  `pi_client/hardware/real.py` with two more `RealUltrasonic` instances and
  add them to `HardwareBundle`.
- **Battery monitoring / auto-shutdown** — out of scope.
- **Live video stream to a dashboard** — would warrant MJPEG over HTTP as a
  separate FastAPI route. Not part of Phase 1.
