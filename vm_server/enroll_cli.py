"""Enroll a single face from an image file.

Usage:
    python -m vm_server.enroll_cli --name "Alice" --role allowed --image alice.jpg

Stores the embedding + a copy of the photo in vm_server/db/photos/.
Exits non-zero with a clear message if the image has no detectable face.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from vm_server.config import load_config
from vm_server.db.face_db import FaceDB
from vm_server.services import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enroll a face into the surveillance DB")
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", required=True, choices=["allowed", "restricted"])
    parser.add_argument("--image", required=True, type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()

    if not args.image.exists():
        print(f"error: image not found: {args.image}", file=sys.stderr)
        return 2

    jpeg_bytes = args.image.read_bytes()
    emb = pipeline.embed_image(cfg, jpeg_bytes)
    if emb is None:
        print(f"error: no face detected in {args.image}", file=sys.stderr)
        return 3

    cfg.photos_dir.mkdir(parents=True, exist_ok=True)
    dst = cfg.photos_dir / args.image.name
    shutil.copy2(args.image, dst)

    db = FaceDB(cfg.db_path)
    try:
        face_id = db.enroll(name=args.name, role=args.role, embedding=emb, photo_path=str(dst))
    finally:
        db.close()
    print(f"enrolled id={face_id} name={args.name!r} role={args.role} photo={dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
