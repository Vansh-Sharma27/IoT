# Surveillance robot

Autonomous wheeled robot built for the IoT & Robotics lab. A Raspberry Pi 4B
drives motors, reads ultrasonic distance, and captures images from a USB
camera. Heavy vision work (face detection, ArcFace embedding, identity match)
runs on a VM and is reached over Tailscale via RPyC.

## Architecture

```
+-------------------+          Tailscale          +--------------------------+
|  Raspberry Pi 4B  |  RPyC over WireGuard mesh   |             VM            |
|                   | <-------------------------> |                          |
|  - L298N + motors |                             |  RPyC VisionService      |
|  - HC-SR04        |       JPEG bytes  ->        |   ├ pipeline.authenticate|
|  - USB camera     |    <- AuthResult (JSON)     |   │   ├ YOLOv8n (person?)|
|  - buzzer + LEDs  |                             |   │   └ InsightFace      |
|  - state machine  |                             |   │      (SCRFD+ArcFace) |
|                   |                             |   └ FaceDB (SQLite +     |
|                   |                             |        cosine search)    |
+-------------------+                             +--------------------------+
```

The Pi owns everything safety / latency-critical. The VM owns model inference.
The RPyC contract is small (`ping`, `authenticate`, `enroll`, `list_known`,
`delete`) and uses **JSON-encoded payloads** so it stays portable.

## Repo layout

| Path | Purpose |
|---|---|
| `protocol/` | Shared `AuthResult` dataclass + `Decision` enum |
| `vm_server/` | Vision pipeline, RPyC service, enroll & calibration CLIs |
| `pi_client/` | Hardware drivers (mock + real), state machine, RPC client |
| `docs/` | Tailscale + Pi provisioning notes |

## Quickstart — VM

```bash
cd vm_server
pip install -r requirements.txt
cd ..

# One-time: pull InsightFace + YOLO weights (~250 MB).
PYTHONPATH=. python3 -m vm_server.bootstrap_models

# Enroll team faces (run for each person).
PYTHONPATH=. python3 -m vm_server.enroll_cli --name "Alice" --role allowed --image ./photos/alice.jpg

# Calibrate the threshold against your team's photos.
# Layout: ./calibration_photos/<person>/01.jpg, 02.jpg, ...
PYTHONPATH=. python3 -m vm_server.calibrate_threshold --photos-dir ./calibration_photos

# Start the service. Bind is 0.0.0.0; ufw + Tailscale gate access.
PYTHONPATH=. python3 -m vm_server.server
```

## Quickstart — Pi

See `docs/pi_provisioning.md` for OS install + wiring + systemd. Short version:

```bash
cd pi_client
pip install -r requirements.txt
# Edit config.yaml: set pi.vm_host to the VM's tailnet IP, hardware_backend: real
PYTHONPATH=.. python3 -m pi_client.main
```

## Running locally on the VM (no Pi yet)

The Pi client ships with a `mock` hardware backend so you can exercise the
state machine on the VM. Set `pi.hardware_backend: mock` in `pi_client/config.yaml`,
then run `python3 -m pi_client.main` from the repo root.

## Tests

```bash
PYTHONPATH=. python3 -m pytest -v
```

Currently 30 tests covering the face DB, vision pipeline, RPyC surface, and
the Pi state machine. None of them require the model weights — they use
synthetic embeddings and stubbed model loaders.

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
