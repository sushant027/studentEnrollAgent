"""Test 2 — authentication: login, hashing, and the protected endpoint."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.repository import student_repository
from app.service.auth_service import InvalidCredentials, login
from app.utilities.jwt_utils import TokenError, create_access_token, verify_access_token
from app.utilities.security import hash_password, verify_password


def test_login_succeeds_and_returns_the_students_own_id(seeded_db):
    result = login("john@example.com", "password123")
    assert result["student_id"] == "STUDENT-001"
    assert result["access_token"]


def test_wrong_password_is_rejected(seeded_db):
    with pytest.raises(InvalidCredentials):
        login("john@example.com", "wrong-password")


def test_unknown_email_gives_the_same_message_as_a_wrong_password(seeded_db):
    """No account enumeration: both failures look identical to the caller."""
    with pytest.raises(InvalidCredentials) as unknown:
        login("nobody@example.com", "password123")
    with pytest.raises(InvalidCredentials) as bad_password:
        login("john@example.com", "wrong-password")
    assert str(unknown.value) == str(bad_password.value)


def test_passwords_are_stored_as_hashes_not_plaintext(seeded_db):
    conn = sqlite3.connect(get_settings().database_path)
    rows = conn.execute("SELECT password_hash FROM students").fetchall()
    conn.close()
    assert rows
    for (stored,) in rows:
        assert stored != "password123"
        assert stored.startswith("$2")  # bcrypt
    assert verify_password("password123", rows[0][0])


def test_hashing_is_salted_so_identical_passwords_differ():
    assert hash_password("password123") != hash_password("password123")


def test_token_round_trips_to_the_student_id():
    assert verify_access_token(create_access_token("STUDENT-002")) == "STUDENT-002"


def test_tampered_token_is_rejected():
    token = create_access_token("STUDENT-001")
    with pytest.raises(TokenError):
        verify_access_token(token[:-4] + "aaaa")


def test_token_carries_no_pii():
    import jwt

    claims = jwt.decode(
        create_access_token("STUDENT-001"),
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    assert set(claims) == {"sub", "exp"}


def test_chat_endpoint_requires_a_token(seeded_db):
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/enrollment/chat",
            json={"session_id": "S1", "message": "hello"},
        )
    assert response.status_code == 401


def test_chat_endpoint_rejects_a_garbage_token(seeded_db):
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/enrollment/chat",
            json={"session_id": "S1", "message": "hello"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert response.status_code == 401


def test_login_route_returns_401_on_bad_credentials(seeded_db):
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "john@example.com", "password": "nope"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_health_endpoint(seeded_db):
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_seeding_is_idempotent(seeded_db):
    student_repository.init_db()
    conn = sqlite3.connect(get_settings().database_path)
    count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    conn.close()
    assert count == 3
