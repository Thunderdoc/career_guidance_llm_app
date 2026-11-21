"""Kaam-Vaani Stage 1: feature flags, roles, migration v11, kv_voice status.

Covers: Settings flag defaults (ON in dev, OFF in production, explicit
env wins), the flags helper module, migration v11 (phone columns + role
index, idempotent), role validation + employer/coordinator deps (403s),
the admin role endpoint accepting the new roles, and the kv_voice status
route mounting only when KV_VOICE is on (404 otherwise).
"""

from __future__ import annotations

import importlib
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.auth import Auth, AuthSettings
from backend.auth import build_router as build_auth_router
from career_guidance import kaamvaani
from career_guidance.config import Settings, load_settings
from career_guidance.kaamvaani import flags as kv_flags
from career_guidance.migrations import LATEST_VERSION, applied_versions, migrate
from career_guidance.users import User, UserStore, validate_role

KV_ENV_VARS = (
    "KV_VOICE",
    "KV_RAG",
    "KV_EMPLOYERS",
    "KV_CONSENT",
    "KV_VIDEO_CHECK",
    "KV_PILOT",
)


def _clear_kv_env(monkeypatch) -> None:
    for var in KV_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _user(role: str) -> User:
    return User(
        id=f"u-{role}",
        email=f"{role}@example.com",
        name=role,
        picture="",
        provider="test",
        role=role,
        created_at="",
        last_login_at="",
    )


# --------------------------------------------------------------------------- #
# Settings flag defaults
# --------------------------------------------------------------------------- #


def test_kv_flags_default_on_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    _clear_kv_env(monkeypatch)
    settings = load_settings()
    assert settings.kv_voice is True
    assert settings.kv_rag is True
    assert settings.kv_employers is True
    assert settings.kv_consent is True
    assert settings.kv_video_check is True
    assert settings.kv_pilot is True


def test_kv_flags_default_off_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    _clear_kv_env(monkeypatch)
    settings = load_settings()
    assert settings.kv_voice is False
    assert settings.kv_rag is False
    assert settings.kv_employers is False
    assert settings.kv_consent is False
    assert settings.kv_video_check is False
    assert settings.kv_pilot is False


def test_kv_flags_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    _clear_kv_env(monkeypatch)
    monkeypatch.setenv("KV_VOICE", "false")
    monkeypatch.setenv("KV_RAG", "0")
    assert load_settings().kv_voice is False
    assert load_settings().kv_rag is False

    monkeypatch.setenv("APP_ENV", "production")
    _clear_kv_env(monkeypatch)
    monkeypatch.setenv("KV_VOICE", "true")
    monkeypatch.setenv("KV_PILOT", "1")
    settings = load_settings()
    assert settings.kv_voice is True
    assert settings.kv_pilot is True
    assert settings.kv_rag is False  # still default-off in production


def test_kv_flag_env_parsing_variants(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    _clear_kv_env(monkeypatch)
    for raw, expected in (
        ("yes", True),
        ("on", True),
        ("TRUE", True),
        (" 1 ", True),
        ("no", False),
        ("off", False),
        ("maybe", False),
        ("", False),  # empty = unset = production default (off)
    ):
        monkeypatch.setenv("KV_VOICE", raw)
        assert load_settings().kv_voice is expected, raw


def test_kv_provider_defaults(monkeypatch):
    _clear_kv_env(monkeypatch)
    monkeypatch.delenv("KV_STT_PROVIDER", raising=False)
    monkeypatch.delenv("KV_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("KV_SHARE_PROVIDER", raising=False)
    settings = load_settings()
    assert settings.kv_stt_provider == "browser"
    assert settings.kv_tts_provider == "browser"
    assert settings.kv_share_provider == ""


def test_kv_provider_env_overrides(monkeypatch):
    monkeypatch.setenv("KV_STT_PROVIDER", "Whisper")
    monkeypatch.setenv("KV_TTS_PROVIDER", "")
    monkeypatch.setenv("KV_SHARE_PROVIDER", "WhatsApp")
    settings = load_settings()
    assert settings.kv_stt_provider == "whisper"
    assert settings.kv_tts_provider == "browser"  # empty falls back to browser
    assert settings.kv_share_provider == "whatsapp"


# --------------------------------------------------------------------------- #
# flags helper module
# --------------------------------------------------------------------------- #


def test_flags_is_enabled_maps_every_flag():
    settings = Settings(
        kv_voice=True,
        kv_rag=False,
        kv_employers=True,
        kv_consent=False,
        kv_video_check=True,
        kv_pilot=False,
    )
    assert kv_flags.is_enabled(settings, "voice") is True
    assert kv_flags.is_enabled(settings, "rag") is False
    assert kv_flags.is_enabled(settings, "employers") is True
    assert kv_flags.is_enabled(settings, "consent") is False
    assert kv_flags.is_enabled(settings, "video_check") is True
    assert kv_flags.is_enabled(settings, "pilot") is False
    assert set(kv_flags.FEATURE_FLAGS) == {
        "voice",
        "rag",
        "employers",
        "consent",
        "video_check",
        "pilot",
    }


def test_flags_unknown_name_raises():
    with pytest.raises(ValueError, match="Unknown Kaam-Vaani flag"):
        kv_flags.is_enabled(Settings(), "teleport")


def test_flags_describe_reports_all():
    settings = Settings(kv_voice=True, kv_rag=False)
    described = kv_flags.describe(settings)
    assert described == {
        "voice": True,
        "rag": False,
        "employers": True,
        "consent": True,
        "video_check": True,
        "pilot": True,
    }


def test_kaamvaani_package_importable():
    assert kaamvaani is not None


# --------------------------------------------------------------------------- #
# Migration v11
# --------------------------------------------------------------------------- #


def test_migration_v11_applies_and_is_idempotent(tmp_path):
    db = str(tmp_path / "kv11.db")
    applied = migrate(db)
    assert 11 in applied
    assert LATEST_VERSION >= 11  # Stage 2 added v12; later stages may add more
    assert 11 in applied_versions(db)

    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert "phone_e164" in cols
        assert "phone_verified_at" in cols
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(users)")}
        assert "idx_users_role" in indexes
        row = conn.execute("SELECT name FROM schema_migrations WHERE version = 11").fetchone()
        assert row and "kaam-vaani" in row[0]

    # Second run: nothing to apply, and existing rows survive.
    store = UserStore(db)
    user = store.upsert_login("keep@example.com", "test")
    assert migrate(db) == []
    assert store.get(user.id) is not None
    assert store.get(user.id).email == "keep@example.com"


# --------------------------------------------------------------------------- #
# Roles: validation, properties, phone scaffolding
# --------------------------------------------------------------------------- #


def test_validate_role_accepts_all_roles_and_normalises():
    assert validate_role("employer") == "employer"
    assert validate_role("coordinator") == "coordinator"
    assert validate_role("  ADMIN ") == "admin"
    assert validate_role("user") == "user"


def test_validate_role_rejects_unknown():
    for bad in ("superuser", "root", "", "employer "[:8] + "x"):
        with pytest.raises(ValueError, match="Unknown role"):
            validate_role(bad)


def test_set_role_accepts_new_roles_and_rejects_bad(tmp_path):
    store = UserStore(str(tmp_path / "roles.db"))
    user = store.upsert_login("r@example.com", "test")
    store.set_role(user.id, "employer")
    assert store.get(user.id).role == "employer"
    assert store.get(user.id).is_employer is True
    assert store.get(user.id).is_coordinator is False
    store.set_role(user.id, "coordinator")
    assert store.get(user.id).is_coordinator is True
    assert store.get(user.id).is_employer is False
    with pytest.raises(ValueError, match="Unknown role"):
        store.set_role(user.id, "superuser")
    assert store.get(user.id).role == "coordinator"  # unchanged after rejection


def test_user_role_properties():
    assert _user("admin").is_admin is True
    assert _user("employer").is_employer is True
    assert _user("employer").is_admin is False
    assert _user("coordinator").is_coordinator is True
    assert _user("user").is_employer is False
    assert _user("user").is_coordinator is False
    assert _user("user").phone_verified is False


def test_set_phone_verified_stores_e164_and_timestamp(tmp_path):
    store = UserStore(str(tmp_path / "phone.db"))
    user = store.upsert_login("p@example.com", "test")
    updated = store.set_phone_verified(user.id, "+919876543210")
    assert updated.phone_e164 == "+919876543210"
    assert updated.phone_verified_at != ""
    assert updated.phone_verified is True
    assert store.get(user.id).phone_verified is True


def test_set_phone_verified_rejects_malformed(tmp_path):
    store = UserStore(str(tmp_path / "phone2.db"))
    user = store.upsert_login("p2@example.com", "test")
    for bad in ("9876543210", "+1", "++919876543210", "", "+91 98765 43210"):
        with pytest.raises(ValueError, match="E.164"):
            store.set_phone_verified(user.id, bad)
    assert store.get(user.id).phone_verified is False


def test_set_phone_verified_missing_user_raises(tmp_path):
    store = UserStore(str(tmp_path / "phone3.db"))
    with pytest.raises(ValueError, match="User not found"):
        store.set_phone_verified("no-such-user", "+919876543210")


# --------------------------------------------------------------------------- #
# Role dependencies (employer / coordinator)
# --------------------------------------------------------------------------- #


def _auth_deps(tmp_path):
    store = UserStore(str(tmp_path / "auth.db"))
    settings = AuthSettings(
        secret="test-secret",
        google_client_id="",
        google_client_secret="",
        public_url="http://testserver",
        admin_emails=set(),
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        app_env="development",
    )
    auth = Auth(settings, store)
    return build_auth_router(auth)


def test_auth_router_returns_five_deps(tmp_path):
    parts = _auth_deps(tmp_path)
    assert len(parts) == 5
    router, current_user, admin_user, employer_user, coordinator_user = parts
    assert router.prefix == "/api/v1/auth"
    assert callable(current_user) and callable(admin_user)
    assert callable(employer_user) and callable(coordinator_user)


def test_employer_dep_allows_employer_only(tmp_path):
    *_, employer_user, _coordinator = _auth_deps(tmp_path)
    assert employer_user(user=_user("employer")).role == "employer"
    for role in ("user", "admin", "coordinator"):
        with pytest.raises(HTTPException) as exc:
            employer_user(user=_user(role))
        assert exc.value.status_code == 403


def test_coordinator_dep_allows_coordinator_only(tmp_path):
    *_, _employer, coordinator_user = _auth_deps(tmp_path)
    assert coordinator_user(user=_user("coordinator")).role == "coordinator"
    for role in ("user", "admin", "employer"):
        with pytest.raises(HTTPException) as exc:
            coordinator_user(user=_user(role))
        assert exc.value.status_code == 403


# --------------------------------------------------------------------------- #
# Admin role endpoint accepts the new roles
# --------------------------------------------------------------------------- #


def test_admin_can_assign_employer_and_coordinator_roles(client):
    from tests.conftest import login

    worker = login(client, "worker@example.com")
    login(client, "boss@example.com")  # ADMIN_EMAILS in the fixture
    r = client.patch(f"/api/v1/admin/users/{worker['id']}/role", json={"role": "employer"})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/v1/admin/users/{worker['id']}/role", json={"role": "coordinator"})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/v1/admin/users/{worker['id']}/role", json={"role": "bogus"})
    assert r.status_code == 422
    r = client.patch(f"/api/v1/admin/users/{worker['id']}/role", json={"role": "user"})
    assert r.status_code == 200, r.text


def test_admin_cannot_demote_self_to_employer(admin_client):
    me = admin_client.get("/api/v1/auth/me").json()["user"]
    r = admin_client.patch(f"/api/v1/admin/users/{me['id']}/role", json={"role": "employer"})
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# kv_voice status route: mounted when the flag is on, 404 when off
# --------------------------------------------------------------------------- #


def test_kv_voice_status_when_flag_on(client):
    r = client.get("/api/v1/kv/voice/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["stt"] == "browser"
    assert body["tts"] == "browser"
    assert body["extraction"] == "deterministic"
    assert body["languages"] == ["en", "hi", "ta"]


@pytest.fixture()
def app_module_kv_voice_off(tmp_path, monkeypatch):
    """backend.main reloaded with KV_VOICE=false (dev otherwise)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("KV_VOICE", "false")
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_voice_status_404_when_flag_off(app_module_kv_voice_off):
    with TestClient(app_module_kv_voice_off.app) as c:
        r = c.get("/api/v1/kv/voice/status")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        # The rest of the app is unaffected by the flag being off.
        assert c.get("/api/v1/health").status_code == 200


def test_unknown_api_paths_404_as_json_not_spa_html(client):
    """Regression: the SPA catch-all must never swallow /api/* paths.

    With a built frontend/out present, an unmatched /api path used to
    answer 200 with index.html — which would also have masked a
    flag-off kv route as "up". Unknown API paths 404 as JSON.
    """
    r = client.get("/api/v1/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["detail"] == "Not found."


@pytest.fixture()
def app_module_production(tmp_path, monkeypatch):
    """backend.main reloaded as production with NO KV_* vars set: all flags
    default off, so no kv route is mounted."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("APP_ENV", "production")
    _clear_kv_env(monkeypatch)
    monkeypatch.delenv("PUBLIC_APP", raising=False)
    import backend.main as main

    importlib.reload(main)
    return main


def test_kv_routes_off_by_default_in_production(app_module_production):
    with TestClient(app_module_production.app) as c:
        assert c.get("/api/v1/kv/voice/status").status_code == 404
        assert c.get("/api/v1/health").status_code == 200
