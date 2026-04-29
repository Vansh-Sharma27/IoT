"""Configuration loader for the VM server.

Reads ``vm_server/config.yaml`` (or a path passed in via VM_CONFIG env var) and
returns an immutable nested dataclass tree. No mutable globals.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ServerCfg:
    host: str
    port: int
    secret_token: str   # Bearer token required by the FastAPI server. Generate with `openssl rand -hex 24`.


@dataclass(frozen=True)
class PathsCfg:
    db: Path
    photos_dir: Path
    models_dir: Path


@dataclass(frozen=True)
class ModelsCfg:
    insightface_pack: str
    yolo_weights: str
    yolo_person_conf: float


@dataclass(frozen=True)
class MatchingCfg:
    threshold: float
    target_far: float


@dataclass(frozen=True)
class Config:
    server: ServerCfg
    paths: PathsCfg
    models: ModelsCfg
    matching: MatchingCfg
    repo_root: Path

    @property
    def db_path(self) -> Path:
        return self.repo_root / self.paths.db

    @property
    def photos_dir(self) -> Path:
        return self.repo_root / self.paths.photos_dir

    @property
    def models_dir(self) -> Path:
        return self.repo_root / self.paths.models_dir


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "vm_server" / "config.yaml"


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path or os.environ.get("VM_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(
        server=ServerCfg(**data["server"]),
        paths=PathsCfg(
            db=Path(data["paths"]["db"]),
            photos_dir=Path(data["paths"]["photos_dir"]),
            models_dir=Path(data["paths"]["models_dir"]),
        ),
        models=ModelsCfg(**data["models"]),
        matching=MatchingCfg(**data["matching"]),
        repo_root=REPO_ROOT,
    )


def write_threshold(new_threshold: float, path: str | Path | None = None) -> None:
    """Update only the matching.threshold field, preserving other keys."""
    cfg_path = Path(path or os.environ.get("VM_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["matching"]["threshold"] = float(new_threshold)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
