"""FastAPI HTTP server for the VM-side vision service.

Replaces the previous RPyC server. Bind to 127.0.0.1:8000 and expose the
public URL via a Cloudflare Quick Tunnel:

    cloudflared tunnel --url http://127.0.0.1:8000

The Pi talks to the resulting https://*.trycloudflare.com URL. Bearer-token
auth is the only access control on the public URL — keep the token secret.

Usage:
    python -m vm_server.http_server                 # uses vm_server/config.yaml
    VM_CONFIG=/path/to/other.yaml python -m vm_server.http_server
"""

from __future__ import annotations

import logging
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from vm_server.config import Config, load_config
from vm_server.db.face_db import FaceDB
from vm_server.services import pipeline

log = logging.getLogger(__name__)


def _check_token(expected: str, authorization: Optional[str]) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad token")


def build_app(cfg: Config, db: FaceDB) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        log.info("warming up models...")
        pipeline.warm_up(cfg)
        log.info("models ready")
        yield
        db.close()
        log.info("server stopped")

    app = FastAPI(title="surveillance-vision", lifespan=lifespan)

    def auth(authorization: Optional[str] = Header(default=None)) -> None:
        _check_token(cfg.server.secret_token, authorization)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True, "service": "surveillance-vision"}

    @app.post("/authenticate")
    async def authenticate(request: Request, _: None = Depends(auth)) -> JSONResponse:
        jpeg_bytes = await request.body()
        if not jpeg_bytes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty body")
        result = pipeline.authenticate(cfg, db, jpeg_bytes)
        log.info(
            "authenticate -> %s (name=%s sim=%s reason=%s)",
            result.decision.value, result.name, result.similarity, result.reason,
        )
        return JSONResponse(result.to_dict())

    @app.post("/enroll")
    async def enroll(
        request: Request,
        name: str,
        role: str,
        photo_filename: str = "",
        _: None = Depends(auth),
    ) -> JSONResponse:
        jpeg_bytes = await request.body()
        if not jpeg_bytes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty body")

        emb = pipeline.embed_image(cfg, jpeg_bytes)
        if emb is None:
            return JSONResponse({"ok": False, "error": "no_face_in_image"})

        photo_path: Optional[str] = None
        if photo_filename:
            cfg.photos_dir.mkdir(parents=True, exist_ok=True)
            dst = cfg.photos_dir / Path(photo_filename).name
            with open(dst, "wb") as f:
                f.write(jpeg_bytes)
            photo_path = str(dst)

        try:
            face_id = db.enroll(name=name, role=role, embedding=emb, photo_path=photo_path)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)})
        return JSONResponse({"ok": True, "id": face_id})

    @app.get("/known")
    def known(_: None = Depends(auth)) -> list[dict]:
        return [
            {
                "id": r.id,
                "name": r.name,
                "role": r.role,
                "photo_path": r.photo_path,
                "created_at": r.created_at,
            }
            for r in db.list_all()
        ]

    @app.delete("/known/{face_id}")
    def delete(face_id: int, _: None = Depends(auth)) -> dict:
        return {"ok": db.delete(int(face_id))}

    return app


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    if not cfg.server.secret_token or cfg.server.secret_token == "CHANGE_ME":
        log.error("server.secret_token is unset; refuse to start. Generate one with: openssl rand -hex 24")
        return 1
    log.info(
        "loaded config: db=%s threshold=%.3f host=%s port=%d",
        cfg.db_path, cfg.matching.threshold, cfg.server.host, cfg.server.port,
    )
    db = FaceDB(cfg.db_path)
    log.info("face DB has %d enrolled identities", len(db.list_all()))

    app = build_app(cfg, db)
    uvicorn.run(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
