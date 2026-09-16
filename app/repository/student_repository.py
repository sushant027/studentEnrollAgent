"""SQLite-backed student store — the one table the app actually persists.

Schema (SPEC section 6):
    students(student_id TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, password_hash TEXT)
"""

from __future__ import annotations

import sqlite3

from app.config import get_settings
from app.constants.constants import Events
from app.repository.mock_data import SEED_STUDENTS
from app.utilities.logger import get_logger
from app.utilities.security import hash_password

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL
)
"""


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_settings().database_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create the table and seed the three demo students. Idempotent."""
    path = db_path or get_settings().database_path
    with _connect(path) as conn:
        conn.execute(_SCHEMA)
        existing = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]
        if existing == 0:
            for student in SEED_STUDENTS:
                conn.execute(
                    "INSERT INTO students (student_id, name, email, password_hash) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        student["student_id"],
                        student["name"],
                        student["email"],
                        hash_password(student["password"]),
                    ),
                )
        conn.commit()
    log.event(
        Events.DB_INITIALIZED,
        "student store ready",
        db_path=path,
        seeded=existing == 0,
        student_count=existing or len(SEED_STUDENTS),
    )


def find_by_email(email: str, db_path: str | None = None) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT student_id, name, email, password_hash FROM students WHERE email = ?",
            ((email or "").strip(),),
        ).fetchone()
    return dict(row) if row else None


def find_by_student_id(student_id: str, db_path: str | None = None) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT student_id, name, email FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()
    return dict(row) if row else None
