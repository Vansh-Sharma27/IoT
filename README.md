# Surveillance robot

Autonomous wheeled robot built for the IoT & Robotics lab. A Raspberry Pi 4B
drives motors, reads ultrasonic distance, and captures images from a USB
camera. Heavy vision work (face detection, ArcFace embedding, identity match)
runs on a VM and is reached over HTTPS via a **Cloudflare Quick Tunnel**.

> **Why not Tailscale?** The previous design used RPyC over Tailscale. Campus
> Fortinet firewalls block Tailscale's DERP relay (SSL inspection breaks it)
> and direct WireGuard UDP, so the Pi could never reach the VM on campus
> Wi-Fi. The current design uses an outbound HTTPS tunnel from the VM, which
> the corporate firewall treats as ordinary web traffic.

## Architecture

```
+-------------------+       HTTPS (TLS)        +--------------------------+
|  Raspberry Pi 4B  |  POST /authenticate      |             VM            |
|                   | ---  JPEG bytes  ---->   |                          |
|  - L298N + motors |                          |  FastAPI vision service  |
|  - HC-SR04        |  <--- AuthResult JSON ---|   ├ pipeline.authenticate|
|  - USB camera     |                          |   │   ├ YOLOv8n (person?)|
|  - buzzer + LEDs  |                          |   │   └ InsightFace      |
|  - state machine  |                          |   │      (SCRFD+ArcFace) |
|                   |                          |   └ FaceDB (SQLite +     |
|                   |                          |        cosine search)    |
|     |  ^                                     +--------------------------+
|     |  |                                                  ^
|     v  |                                                  |
| https://*.trycloudflare.com  <-----  outbound tunnel ----+
|       (Cloudflare edge)            cloudflared on VM
+-------------------+
```

The Pi owns everything safety / latency-critical. The VM owns model inference.
The HTTP contract (`GET /ping`, `POST /authenticate`, `POST /enroll`,
`GET /known`, `DELETE /known/{id}`) is small, JSON-only, and authenticated
with a shared bearer token.

## Repo layout

| Path | Purpose |
|---|---|
| `protocol/` | Shared `AuthResult` dataclass + `Decision` enum |
| `vm_server/` | Vision pipeline, FastAPI HTTP service, enroll & calibration CLIs |
| `pi_client/` | Hardware drivers (mock + real), state machine, HTTP client |
| `docs/` | Cloudflare Tunnel + Pi provisioning notes |

## Quickstart — VM

```bash
cd vm_server
pip install -r requirements.txt
cd ..

# One-time: pull InsightFace + YOLO weights (~250 MB).
PYTHONPATH=. python3 -m vm_server.bootstrap_models

# Generate a bearer token, paste it into vm_server/config.yaml::server.secret_token
openssl rand -hex 24

# Enroll team faces (run for each person).
PYTHONPATH=. python3 -m vm_server.enroll_cli --name "Alice" --role allowed --image ./photos/alice.jpg

# Calibrate the threshold against your team's photos.
PYTHONPATH=. python3 -m vm_server.calibrate_threshold --photos-dir ./calibration_photos

# Start the FastAPI service on 127.0.0.1:8000.
PYTHONPATH=. python3 -m vm_server.http_server

# In a second shell, expose it via a Cloudflare Quick Tunnel.
# This prints the public https://*.trycloudflare.com URL — copy it to the Pi config.
cloudflared tunnel --url http://127.0.0.1:8000
```

See `docs/cloudflare_tunnel.md` for `cloudflared` install + a systemd unit
that keeps the tunnel up across reboots.

## Quickstart — Pi

See `docs/pi_provisioning.md` for OS install + wiring + systemd. Short version:

```bash
cd pi_client
pip install -r requirements.txt
# Edit config.yaml:
#   pi.vm_url:   https://<random>.trycloudflare.com   (from the VM)
#   pi.vm_token: <same value as vm_server config.yaml::server.secret_token>
#   pi.hardware_backend: real
PYTHONPATH=.. python3 -m pi_client.main
```

## Running locally on the VM (no Pi yet)

The Pi client ships with a `mock` hardware backend. Set
`pi.hardware_backend: mock` in `pi_client/config.yaml`, leave `vm_url` pointing
at `http://127.0.0.1:8000` (and use the same token), then run
`python3 -m pi_client.main` from the repo root.

## Tests

```bash
PYTHONPATH=. python3 -m pytest -v
```

The HTTP test (`vm_server/tests/test_http_server.py`) uses FastAPI's in-process
`TestClient` — no real network or model weights required.

## Threat policy

| What the camera sees | Decision | Robot reaction |
|---|---|---|
| Known person, role=allowed | `ALLOWED` | Green LED 2s, resume wandering |
| Known person, role=restricted | `DENIED` | Buzzer x3, red LED 5s, back up |
| Unknown person | `DENIED` | Buzzer x3, red LED 5s, back up |
| No face but a person bbox (back-of-head) | `UNKNOWN` | Amber LED 1s, retry on next approach |
| Non-human (chair, animal, wall) | `NON_HUMAN` | Silent, resume wandering |
| VM unreachable | `None` (no result) | Amber LED 1s, robot keeps wandering |

## Why these choices

See `~/.claude/plans/me-and-my-team-fancy-hickey.md` for the full plan with
reasoning on Python (vs Go/Rust) for the backend, cosine similarity (the
correct metric for ArcFace), threshold calibration, and what is intentionally
out of scope.
