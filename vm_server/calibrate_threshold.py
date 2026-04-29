"""Calibrate the face match threshold against your team's actual photos.

Usage:
    python -m vm_server.calibrate_threshold --photos-dir ./calibration_photos

Layout expected:
    calibration_photos/
        alice/
            01.jpg
            02.jpg
            03.jpg
        bob/
            01.jpg
            02.jpg
        ...

For every photo we compute its ArcFace embedding. We then form:
  - GENUINE pairs: every (photo_i, photo_j) where i != j and both belong to the
    same person.
  - IMPOSTER pairs: every (photo_i, photo_j) where they belong to different
    people.

We compute cosine similarity on each pair, then pick the smallest threshold T
such that  (#imposter pairs with sim >= T) / (#imposter pairs) <= target_far
read from config. Reports FRR at that T as well, then writes T into
vm_server/config.yaml's matching.threshold field.

This is the principled answer to "what threshold should we use?" — better than
any number quoted in a paper because it is calibrated on YOUR cameras, lighting,
and team.
"""

from __future__ import annotations

import argparse
import logging
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

from vm_server.config import load_config, write_threshold
from vm_server.services import pipeline


def _embed_folder(cfg, root: Path) -> dict[str, list[np.ndarray]]:
    out: dict[str, list[np.ndarray]] = {}
    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        embs: list[np.ndarray] = []
        for img_path in sorted(person_dir.iterdir()):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                continue
            emb = pipeline.embed_image(cfg, img_path.read_bytes())
            if emb is None:
                logging.warning("no face in %s — skipping", img_path)
                continue
            embs.append(emb / np.linalg.norm(emb))
        if len(embs) >= 2:
            out[person_dir.name] = embs
        else:
            logging.warning("person %s has fewer than 2 valid photos — skipping", person_dir.name)
    return out


def _genuine_imposter_sims(by_person: dict[str, list[np.ndarray]]):
    genuine: list[float] = []
    imposter: list[float] = []
    names = list(by_person.keys())
    for name in names:
        for a, b in combinations(by_person[name], 2):
            genuine.append(float(a @ b))
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            for a in by_person[names[i]]:
                for b in by_person[names[j]]:
                    imposter.append(float(a @ b))
    return np.asarray(genuine), np.asarray(imposter)


def _pick_threshold(genuine: np.ndarray, imposter: np.ndarray, target_far: float) -> float:
    if imposter.size == 0:
        # No imposters -> can't bound FAR; fall back to a conservative default.
        return 0.5
    # Smallest T such that mean(imposter >= T) <= target_far.
    candidates = np.unique(np.concatenate([genuine, imposter]))
    candidates.sort()
    chosen = float(candidates[-1])  # most conservative default
    for t in candidates:
        far = float((imposter >= t).mean())
        if far <= target_far:
            chosen = float(t)
            break
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate face match threshold")
    parser.add_argument("--photos-dir", required=True, type=Path)
    parser.add_argument("--target-far", type=float, default=None,
                        help="overrides matching.target_far in config.yaml")
    parser.add_argument("--write/--no-write", dest="write", action="store_true", default=True)
    parser.add_argument("--no-write", dest="write", action="store_false")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    target_far = args.target_far if args.target_far is not None else cfg.matching.target_far

    if not args.photos_dir.exists():
        print(f"error: {args.photos_dir} not found", file=sys.stderr)
        return 2

    by_person = _embed_folder(cfg, args.photos_dir)
    if len(by_person) < 2:
        print("error: need at least 2 people with >=2 photos each", file=sys.stderr)
        return 3

    genuine, imposter = _genuine_imposter_sims(by_person)
    logging.info(
        "%d people, %d genuine pairs, %d imposter pairs",
        len(by_person), genuine.size, imposter.size,
    )
    logging.info(
        "genuine cosine: min=%.3f mean=%.3f max=%.3f",
        genuine.min(), genuine.mean(), genuine.max(),
    )
    logging.info(
        "imposter cosine: min=%.3f mean=%.3f max=%.3f",
        imposter.min(), imposter.mean(), imposter.max(),
    )

    threshold = _pick_threshold(genuine, imposter, target_far)
    far = float((imposter >= threshold).mean()) if imposter.size else 0.0
    frr = float((genuine < threshold).mean()) if genuine.size else 0.0
    print(f"chosen threshold = {threshold:.4f}  (target FAR <= {target_far})")
    print(f"observed FAR     = {far:.4f}")
    print(f"observed FRR     = {frr:.4f}")

    if args.write:
        write_threshold(threshold)
        print(f"wrote threshold to {cfg.repo_root / 'vm_server' / 'config.yaml'}")
    else:
        print("--no-write: config.yaml unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
