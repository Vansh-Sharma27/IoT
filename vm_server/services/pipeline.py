"""Vision pipeline: JPEG bytes -> AuthResult.

Lazy-loads YOLOv8n (person detector) and InsightFace buffalo_s (face detector
+ ArcFace embedder) on first authenticate() call. Both models are then held
in module-level singletons for the lifetime of the server process.

Decision flow:
    1. Decode JPEG -> BGR ndarray.
    2. YOLO -> any 'person' bbox above conf threshold? If not, NON_HUMAN.
    3. InsightFace -> at least one face? If not, UNKNOWN ('no_face').
    4. Pick the largest face, embed, cosine-match against FaceDB.
       - Hit + role=allowed       -> ALLOWED
       - Hit + role=restricted    -> DENIED ('restricted_role')
       - Miss                     -> DENIED ('unknown_face')
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import cv2
import numpy as np

from protocol import AuthResult, Decision
from vm_server.config import Config
from vm_server.db.face_db import FaceDB

log = logging.getLogger(__name__)

_models_lock = threading.Lock()
_yolo = None
_face_app = None


def _load_yolo(cfg: Config):
    global _yolo
    if _yolo is None:
        from ultralytics import YOLO

        weights = cfg.models_dir / cfg.models.yolo_weights
        # ultralytics handles auto-download if the weight file is just a name
        # (e.g. "yolov8n.pt") and not present in CWD.
        if weights.exists():
            _yolo = YOLO(str(weights))
        else:
            _yolo = YOLO(cfg.models.yolo_weights)
        log.info("loaded YOLO model")
    return _yolo


def _load_face_app(cfg: Config):
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis

        cfg.models_dir.mkdir(parents=True, exist_ok=True)
        app = FaceAnalysis(
            name=cfg.models.insightface_pack,
            root=str(cfg.models_dir),
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _face_app = app
        log.info("loaded InsightFace pack=%s", cfg.models.insightface_pack)
    return _face_app


def warm_up(cfg: Config) -> None:
    """Force-load both models. Call once at server startup so the first
    authenticate() request doesn't pay the model-load latency."""
    with _models_lock:
        _load_yolo(cfg)
        _load_face_app(cfg)


def _decode_jpeg(jpeg_bytes: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def _has_person(yolo, img: np.ndarray, conf: float) -> bool:
    # COCO class 0 = person
    results = yolo.predict(img, classes=[0], conf=conf, verbose=False)
    if not results:
        return False
    boxes = results[0].boxes
    return boxes is not None and len(boxes) > 0


def _largest_face_embedding(face_app, img: np.ndarray) -> Optional[np.ndarray]:
    faces = face_app.get(img)
    if not faces:
        return None

    def area(face) -> float:
        x1, y1, x2, y2 = face.bbox
        return float(max(0, x2 - x1) * max(0, y2 - y1))

    biggest = max(faces, key=area)
    emb = biggest.normed_embedding  # already L2-normalised by InsightFace
    return np.asarray(emb, dtype=np.float32)


def authenticate(cfg: Config, db: FaceDB, jpeg_bytes: bytes) -> AuthResult:
    img = _decode_jpeg(jpeg_bytes)
    if img is None:
        return AuthResult(decision=Decision.UNKNOWN, reason="bad_jpeg")

    with _models_lock:
        yolo = _load_yolo(cfg)
        face_app = _load_face_app(cfg)

    if not _has_person(yolo, img, cfg.models.yolo_person_conf):
        return AuthResult(decision=Decision.NON_HUMAN, reason="no_person_bbox")

    emb = _largest_face_embedding(face_app, img)
    if emb is None:
        return AuthResult(decision=Decision.UNKNOWN, reason="no_face")

    hit = db.match(emb, threshold=cfg.matching.threshold)
    if hit is None:
        return AuthResult(decision=Decision.DENIED, reason="unknown_face")

    if hit.row.role == "allowed":
        return AuthResult(
            decision=Decision.ALLOWED,
            name=hit.row.name,
            similarity=hit.similarity,
        )
    return AuthResult(
        decision=Decision.DENIED,
        name=hit.row.name,
        similarity=hit.similarity,
        reason="restricted_role",
    )


def embed_image(cfg: Config, jpeg_bytes: bytes) -> Optional[np.ndarray]:
    """Used by enroll_cli and calibrate_threshold to get an embedding for an
    image without going through the full authenticate path."""
    img = _decode_jpeg(jpeg_bytes)
    if img is None:
        return None
    with _models_lock:
        face_app = _load_face_app(cfg)
    return _largest_face_embedding(face_app, img)
