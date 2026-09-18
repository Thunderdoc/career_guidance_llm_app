"""Firebase ID-token verification and session exchange (offline, self-signed keys)."""

import importlib
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

PROJECT = "career-ai-ecba3"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return key, pub.decode()


def _token(key, **over):
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "uid123",
        "iat": now - 5,
        "exp": now + 3600,
        "email": "Boss@Example.com",
        "email_verified": True,
        "name": "Boss",
        "picture": "https://img/p.png",
        "firebase": {"sign_in_provider": "google.com"},
    }
    claims.update(over)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture()
def client(tmp_path, monkeypatch, keypair):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    import backend.main as main

    importlib.reload(main)
    main._auth.firebase.set_keys({"k1": keypair[1]})
    with TestClient(main.app) as c:
        yield c


def test_providers_advertise_firebase(client):
    assert client.get("/api/v1/auth/providers").json()["firebase"] is True


def test_valid_token_creates_session_and_admin_role(client, keypair):
    r = client.post("/api/v1/auth/firebase", json={"id_token": _token(keypair[0])})
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["email"] == "boss@example.com" and u["is_admin"] and u["name"] == "Boss"
    assert u["provider"] == "firebase:google.com"
    assert client.get("/api/v1/auth/me").json()["user"]["id"] == u["id"]
    assert client.get("/api/v1/admin/overview").status_code == 200


def test_bad_tokens_rejected(client, keypair):
    key = keypair[0]
    for bad in (
        _token(key, aud="other-project"),
        _token(key, iss="https://evil"),
        _token(key, exp=int(time.time()) - 10),
        "not.a.jwt",
    ):
        assert client.post("/api/v1/auth/firebase", json={"id_token": bad}).status_code == 401
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert client.post("/api/v1/auth/firebase", json={"id_token": _token(other)}).status_code == 401


def test_unverified_password_email_blocked(client, keypair):
    tok = _token(keypair[0], email_verified=False, firebase={"sign_in_provider": "password"})
    assert client.post("/api/v1/auth/firebase", json={"id_token": tok}).status_code == 403
