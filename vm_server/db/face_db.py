"""SQLite-backed face database with in-memory cosine search.

Embeddings are stored as little-endian float32 BLOBs (2048 bytes for a 512-d
ArcFace vector). The full embedding matrix is loaded into memory on
:meth:`FaceDB.load_all`; brute-force cosine search is fine for the expected
size of a lab DB (tens to low hundreds of identities).

Embeddings are unit-normalised at insert time, so cosine similarity reduces
to a single matrix-vector dot product.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

EMBEDDING_DIM = 512
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@dataclass(frozen=True)
class FaceRow:
    id: int
    name: str
    role: str
    photo_path: Optional[str]
    created_at: str


@dataclass(frozen=True)
class MatchHit:
    row: FaceRow
    similarity: float


def _to_blob(emb: np.ndarray) -> bytes:
    if emb.shape != (EMBEDDING_DIM,):
        raise ValueError(f"expected shape ({EMBEDDING_DIM},), got {emb.shape}")
    return emb.astype("<f4", copy=False).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def _normalise(emb: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(emb)
    if norm == 0.0:
        raise ValueError("zero-norm embedding")
    return (emb / norm).astype(np.float32, copy=False)


class FaceDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._cache_matrix: Optional[np.ndarray] = None
        self._cache_rows: list[FaceRow] = []
        self.load_all()

    def _init_schema(self) -> None:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self._conn.executescript(f.read())
        self._conn.commit()

    def load_all(self) -> tuple[np.ndarray, list[FaceRow]]:
        cur = self._conn.execute(
            "SELECT id, name, role, embedding, photo_path, created_at FROM faces ORDER BY id"
        )
        rows: list[FaceRow] = []
        embs: list[np.ndarray] = []
        for r in cur:
            embs.append(_from_blob(r["embedding"]))
            rows.append(
                FaceRow(
                    id=r["id"],
                    name=r["name"],
                    role=r["role"],
                    photo_path=r["photo_path"],
                    created_at=r["created_at"],
                )
            )
        if embs:
            matrix = np.stack(embs, axis=0)
        else:
            matrix = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        self._cache_matrix = matrix
        self._cache_rows = rows
        return matrix, rows

    def enroll(
        self,
        name: str,
        role: str,
        embedding: np.ndarray,
        photo_path: Optional[str] = None,
    ) -> int:
        if role not in ("allowed", "restricted"):
            raise ValueError(f"invalid role: {role}")
        normalised = _normalise(embedding)
        cur = self._conn.execute(
            "INSERT INTO faces (name, role, embedding, photo_path) VALUES (?, ?, ?, ?)",
            (name, role, _to_blob(normalised), photo_path),
        )
        self._conn.commit()
        self.load_all()
        new_id = cur.lastrowid
        assert new_id is not None
        return new_id

    def delete(self, face_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM faces WHERE id = ?", (face_id,))
        self._conn.commit()
        self.load_all()
        return cur.rowcount > 0

    def list_all(self) -> list[FaceRow]:
        return list(self._cache_rows)

    def match(self, query_emb: np.ndarray, threshold: float) -> Optional[MatchHit]:
        if self._cache_matrix is None or self._cache_matrix.shape[0] == 0:
            return None
        q = _normalise(query_emb)
        sims = self._cache_matrix @ q
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        if best_sim < threshold:
            return None
        return MatchHit(row=self._cache_rows[best_idx], similarity=best_sim)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "FaceDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
