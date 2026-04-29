"""Tests for FaceDB with synthetic embeddings (no model required)."""

from __future__ import annotations

import numpy as np
import pytest

from vm_server.db.face_db import EMBEDDING_DIM, FaceDB


def _rand_emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(EMBEDDING_DIM).astype(np.float32)


@pytest.fixture()
def db(tmp_path):
    return FaceDB(tmp_path / "test.sqlite")


def test_empty_db_match_returns_none(db):
    assert db.match(_rand_emb(0), threshold=0.5) is None


def test_enroll_and_self_match(db):
    emb = _rand_emb(1)
    rid = db.enroll("Alice", "allowed", emb)
    assert rid == 1
    hit = db.match(emb, threshold=0.5)
    assert hit is not None
    assert hit.row.name == "Alice"
    assert hit.row.role == "allowed"
    assert hit.similarity == pytest.approx(1.0, abs=1e-5)


def test_match_below_threshold_returns_none(db):
    db.enroll("Bob", "allowed", _rand_emb(2))
    other = _rand_emb(99)  # uncorrelated
    assert db.match(other, threshold=0.5) is None


def test_match_picks_closest(db):
    a = _rand_emb(10)
    b = _rand_emb(11)
    db.enroll("A", "allowed", a)
    db.enroll("B", "restricted", b)
    hit = db.match(a + 0.01 * b, threshold=0.5)
    assert hit is not None
    assert hit.row.name == "A"


def test_invalid_role_rejected(db):
    with pytest.raises(ValueError):
        db.enroll("X", "admin", _rand_emb(3))


def test_invalid_dim_rejected(db):
    with pytest.raises(ValueError):
        db.enroll("X", "allowed", np.zeros(128, dtype=np.float32))


def test_zero_embedding_rejected(db):
    with pytest.raises(ValueError):
        db.enroll("X", "allowed", np.zeros(EMBEDDING_DIM, dtype=np.float32))


def test_delete_removes_row(db):
    rid = db.enroll("Carol", "allowed", _rand_emb(4))
    assert db.delete(rid) is True
    assert db.match(_rand_emb(4), threshold=0.5) is None
    assert db.delete(9999) is False


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "persist.sqlite"
    with FaceDB(path) as db1:
        db1.enroll("Dora", "allowed", _rand_emb(5))
    with FaceDB(path) as db2:
        assert len(db2.list_all()) == 1
        assert db2.list_all()[0].name == "Dora"
