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
    claims = {k: v for k, v in claims.items() if v is not None}  # None removes a claim
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
    for claims in (
        {"email_verified": False, "firebase": {"sign_in_provider": "password"}},
        {"email_verified": None, "firebase": {"sign_in_provider": "password"}},  # claim missing
    ):
        tok = _token(keypair[0], email="u@example.com", **claims)
        r = client.post("/api/v1/auth/firebase", json={"id_token": tok})
        assert r.status_code == 403 and "verify" in r.json()["detail"].lower()
        assert client.get("/api/v1/auth/me").json()["user"] is None  # no session issued


def test_verified_password_user_is_not_admin(client, keypair):
    tok = _token(
        keypair[0], email="u@example.com", sub="u2", firebase={"sign_in_provider": "password"}
    )
    r = client.post("/api/v1/auth/firebase", json={"id_token": tok})
    assert r.status_code == 200 and r.json()["user"]["is_admin"] is False
    assert r.json()["user"]["provider"] == "firebase:password"
    assert client.get("/api/v1/me/runs").status_code == 200  # authenticated: allowed
    assert client.get("/api/v1/admin/overview").status_code == 403  # not authorised


def test_google_user_without_verified_claim_allowed(client, keypair):
    tok = _token(keypair[0], email="g@example.com", sub="g1", email_verified=None)
    assert client.post("/api/v1/auth/firebase", json={"id_token": tok}).status_code == 200
