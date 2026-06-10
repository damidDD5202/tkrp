"""Pytest: isolated SQLite DB before server import."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_fd, _TEST_DB = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["PARKING_EYE_DB"] = _TEST_DB


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    import server as srv

    return TestClient(srv.app)


@pytest.fixture()
def user_client(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "ivan", "password": "user123"},
    )
    assert r.status_code == 200, r.text
    return client


@pytest.fixture()
def admin_client(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    return client
