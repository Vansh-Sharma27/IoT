CREATE TABLE IF NOT EXISTS faces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK (role IN ('allowed','restricted')),
    embedding   BLOB    NOT NULL,
    photo_path  TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_faces_role ON faces(role);
CREATE INDEX IF NOT EXISTS idx_faces_name ON faces(name);
