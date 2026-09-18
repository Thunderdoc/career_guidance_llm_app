"""Authentication: Google OAuth 2.0 + email magic link, signed session cookie.

- Google: standard authorization-code flow (no client library needed).
- Magic link: token e-mailed via SMTP; if SMTP is not configured the link is
  logged and (in non-production) returned in the response for local testing.
- Session: HttpOnly cookie carrying a signed, time-limited user id.
- Admin: any user whose e-mail is listed in ``ADMIN_EMAILS`` (or promoted
  from the admin UI) gets ``role=admin``.

Anonymous usage keeps working everywhere; only ``/me/*`` and ``/admin/*``
require a session.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, EmailStr

from backend.firebase import FirebaseVerifier
from career_guidance.users import User, UserStore

logger = logging.getLogger("career_guidance.auth")

COOKIE = "cg_session"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days


@dataclass(frozen=True)
class AuthSettings:
    secret: str
    google_client_id: str
    google_client_secret: str
    public_url: str
    admin_emails: set[str]
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    app_env: str
    firebase_project_id: str = ""

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host)

    def base_url(self, request: Request) -> str:
        """PUBLIC_URL if configured, else derived from the (forwarded) request."""
        if self.public_url:
            return self.public_url
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if not host or host.startswith(("127.0.0.1", "localhost", "0.0.0.0")):
            return ""  # root-relative links/redirects; the browser fills in the origin
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{proto}://{host}"


def load_auth_settings() -> AuthSettings:
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        secret = "dev-insecure-secret-change-me"
        if os.getenv("APP_ENV", "development") == "production":
            logger.error("SESSION_SECRET is not set in production!")
    return AuthSettings(
        secret=secret,
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        public_url=os.getenv("PUBLIC_URL", "").rstrip("/"),
        admin_emails={e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e},
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "no-reply@localhost")),
        app_env=os.getenv("APP_ENV", "development"),
        firebase_project_id=os.getenv("FIREBASE_PROJECT_ID", ""),
    )


class Auth:
    """Bundles settings, user store and session (de)serialisation."""

    def __init__(self, settings: AuthSettings, store: UserStore) -> None:
        self.settings = settings
        self.store = store
        self._sessions = URLSafeTimedSerializer(settings.secret, salt="session")
        self._states = URLSafeTimedSerializer(settings.secret, salt="oauth-state")
        self.firebase = FirebaseVerifier(settings.firebase_project_id)

    # ---- sessions ----
    def issue(self, response: Response, user: User, request: Request | None = None) -> None:
        base = self.settings.base_url(request) if request else self.settings.public_url
        response.set_cookie(
            COOKIE,
            self._sessions.dumps(user.id),
            max_age=SESSION_TTL,
            httponly=True,
            samesite="lax",
            secure=base.startswith("https://"),
            path="/",
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(COOKIE, path="/")

    def user_from(self, request: Request) -> User | None:
        raw = request.cookies.get(COOKIE)
        if not raw:
            return None
        try:
            uid = self._sessions.loads(raw, max_age=SESSION_TTL)
        except (BadSignature, SignatureExpired):
            return None
        user = self.store.get(uid)
        if user and user.disabled:
            return None
        return user

    # ---- mail ----
    def send_magic_link(self, email: str, link: str) -> bool:
        s = self.settings
        if not s.smtp_enabled:
            logger.warning("SMTP not configured; magic link for %s: %s", email, link)
            return False
        msg = EmailMessage()
        msg["Subject"] = "Your Career Guidance AI sign-in link"
        msg["From"] = s.smtp_from
        msg["To"] = email
        msg.set_content(
            "Click to sign in (valid 15 minutes):\n\n"
            f"{link}\n\nIf you did not request this, ignore this e-mail."
        )
        try:
            if s.smtp_port == 465:
                with smtplib.SMTP_SSL(
                    s.smtp_host, s.smtp_port, context=ssl.create_default_context()
                ) as srv:
                    if s.smtp_user:
                        srv.login(s.smtp_user, s.smtp_password)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as srv:
                    srv.starttls(context=ssl.create_default_context())
                    if s.smtp_user:
                        srv.login(s.smtp_user, s.smtp_password)
                    srv.send_message(msg)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("magic-link e-mail failed")
            return False

    # ---- google ----
    def google_redirect(self, next_path: str, base: str) -> str:
        state = self._states.dumps({"next": next_path, "base": base})
        params = {
            "client_id": self.settings.google_client_id,
            "redirect_uri": f"{base}/api/v1/auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    def google_exchange(self, code: str, state: str) -> tuple[dict, str, str]:
        try:
            data = self._states.loads(state, max_age=600)
        except (BadSignature, SignatureExpired) as e:
            raise HTTPException(400, "Invalid OAuth state.") from e
        base = data.get("base", self.settings.public_url)
        token = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "redirect_uri": f"{base}/api/v1/auth/google/callback",
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        if token.status_code != 200:
            raise HTTPException(400, "Google token exchange failed.")
        info = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            timeout=15,
        )
        if info.status_code != 200:
            raise HTTPException(400, "Could not read Google profile.")
        profile = info.json()
        if not profile.get("email_verified", True):
            raise HTTPException(403, "Google e-mail is not verified.")
        return profile, data.get("next", "/"), base


# ----------------------------------------------------------------------------- #
# Router factory
# ----------------------------------------------------------------------------- #


class FirebaseTokenRequest(BaseModel):
    id_token: str


class MagicLinkRequest(BaseModel):
    email: EmailStr
    next: str = "/"


def _safe_next(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else "/"


def build_router(auth: Auth) -> tuple[APIRouter, object, object]:
    """Return (router, current_user_dep, admin_dep)."""
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    def current_user(request: Request) -> User:
        user = auth.user_from(request)
        if not user:
            raise HTTPException(401, "Sign in required.")
        return user

    def optional_user(request: Request) -> User | None:
        return auth.user_from(request)

    def admin_user(user: User = Depends(current_user)) -> User:  # noqa: B008
        if not user.is_admin:
            raise HTTPException(403, "Admin only.")
        return user

    @router.get("/providers")
    def providers() -> dict:
        fb = auth.firebase.enabled
        return {
            "firebase": fb,
            "google": auth.settings.google_enabled,
            # Magic link stays available as a no-dependency fallback when Firebase is off.
            "magic_link": not fb or auth.settings.app_env != "production",
            "email_delivery": auth.settings.smtp_enabled,
        }

    @router.post("/firebase")
    def firebase_login(body: FirebaseTokenRequest, request: Request, response: Response) -> dict:
        if not auth.firebase.enabled:
            raise HTTPException(503, "Firebase is not configured (FIREBASE_PROJECT_ID).")
        try:
            claims = auth.firebase.verify(body.id_token)
        except ValueError as e:
            raise HTTPException(401, str(e)) from e
        email = (claims.get("email") or "").lower()
        if not email:
            raise HTTPException(400, "Firebase account has no e-mail address.")
        sign_in_provider = claims.get("firebase", {}).get("sign_in_provider", "unknown")
        # Google (and other federated IdPs) already verified the address. For
        # email/password we REQUIRE Firebase's email_verified — never trust the client.
        if sign_in_provider == "password" and claims.get("email_verified") is not True:
            raise HTTPException(
                403,
                "Please verify your email address before signing in. "
                "Check your inbox for the verification link.",
            )
        provider = f"firebase:{sign_in_provider}"
        user = auth.store.upsert_login(
            email, provider, claims.get("name", ""), claims.get("picture", "")
        )
        if user.disabled:
            raise HTTPException(403, "This account has been disabled.")
        auth.issue(response, user, request)
        auth.store.audit(user.email, "login", provider)
        return {"user": user.public()}

    @router.get("/me")
    def me(user: User | None = Depends(optional_user)) -> dict:  # noqa: B008
        return {"user": user.public() if user else None}

    @router.post("/logout")
    def logout(response: Response) -> dict:
        auth.clear(response)
        return {"ok": True}

    @router.post("/magic-link")
    def magic_link(body: MagicLinkRequest, request: Request) -> dict:
        token = auth.store.create_magic_link(body.email)
        link = f"{auth.settings.public_url}/api/v1/auth/magic-link/verify?" + urlencode(
            {"token": token, "next": _safe_next(body.next)}
        )
        sent = auth.send_magic_link(body.email, link)
        out: dict = {"sent": sent}
        if not sent and auth.settings.app_env != "production":
            out["dev_link"] = link  # local testing only; never in production
        return out

    @router.get("/magic-link/verify")
    def magic_verify(request: Request, token: str, next: str = "/"):  # noqa: A002
        base = auth.settings.base_url(request)
        email = auth.store.consume_magic_link(token)
        if not email:
            return RedirectResponse(f"{base}/?auth=expired", 303)
        user = auth.store.upsert_login(email, "magic-link")
        if user.disabled:
            return RedirectResponse(f"{base}/?auth=disabled", 303)
        resp = RedirectResponse(f"{base}{_safe_next(next)}", 303)
        auth.issue(resp, user, request)
        auth.store.audit(user.email, "login", "magic-link")
        return resp

    @router.get("/google")
    def google(request: Request, next: str = "/"):  # noqa: A002
        if not auth.settings.google_enabled:
            raise HTTPException(503, "Google sign-in is not configured.")
        base = auth.settings.base_url(request)
        if not base:
            raise HTTPException(503, "Set PUBLIC_URL so Google can redirect back to this app.")
        return RedirectResponse(auth.google_redirect(_safe_next(next), base), 302)

    @router.get("/google/callback")
    def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if error or not code:
            return RedirectResponse(f"{auth.settings.base_url(request)}/?auth=cancelled", 303)
        profile, next_path, base = auth.google_exchange(code, state)
        user = auth.store.upsert_login(
            profile["email"], "google", profile.get("name", ""), profile.get("picture", "")
        )
        if user.disabled:
            return RedirectResponse(f"{base}/?auth=disabled", 303)
        resp = RedirectResponse(f"{base}{next_path}", 303)
        auth.issue(resp, user, request)
        auth.store.audit(user.email, "login", "google")
        return resp

    return router, current_user, admin_user
