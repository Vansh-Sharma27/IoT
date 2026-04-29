"""Configuration loader for the Pi client. Mirrors vm_server.config style."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PiCfg:
    vm_url: str             # e.g. "https://abc-xyz.trycloudflare.com"
    vm_token: str           # bearer token shared with vm_server.config.server.secret_token
    hardware_backend: str   # "mock" | "real"


@dataclass(frozen=True)
class ControlCfg:
    tick_seconds: float
    forward_speed: float
    turn_speed: float
    trigger_distance_cm: int
    obstacle_distance_cm: int
    stable_seconds: float
    stable_delta_cm: int
    retry_after_capture_seconds: float


@dataclass(frozen=True)
class CameraCfg:
    device_index: int
    jpeg_quality: int
    width: int
    height: int


@dataclass(frozen=True)
class GpioCfg:
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    pi: PiCfg
    control: ControlCfg
    camera: CameraCfg
    gpio: GpioCfg


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "pi_client" / "config.yaml"


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path or os.environ.get("PI_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(
        pi=PiCfg(**data["pi"]),
        control=ControlCfg(**data["control"]),
        camera=CameraCfg(**data["camera"]),
        gpio=GpioCfg(raw=data.get("gpio", {})),
    )
