"""Firebase Authentication: verify ID tokens issued by Firebase Auth.

No Admin SDK / service account needed — tokens are RS256 JWTs signed with
Google's published x509 certificates, which we fetch and cache. Only the
project id (``FIREBASE_PROJECT_ID``) is required.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx
import jwt
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger("career_guidance.firebase")

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)


class FirebaseVerifier:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._keys: dict[str, object] = {}
        self._expires = 0.0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.project_id)

    # Test hook: inject public keys (kid -> PEM) without network access.
    def set_keys(self, pems: dict[str, str], ttl: float = 3600) -> None:
        self._keys = {
            kid: serialization.load_pem_public_key(pem.encode()) for kid, pem in pems.items()
        }
        self._expires = time.time() + ttl

    def _refresh(self) -> None:
        resp = httpx.get(CERTS_URL, timeout=10)
        resp.raise_for_status()
        from cryptography import x509

        keys = {}
        for kid, pem in resp.json().items():
            cert = x509.load_pem_x509_certificate(pem.encode())
            keys[kid] = cert.public_key()
        max_age = 3600
        for part in resp.headers.get("cache-control", "").split(","):
            part = part.strip()
            if part.startswith("max-age="):
                max_age = int(part.split("=", 1)[1])
        self._keys = keys
        self._expires = time.time() + max_age

    def _key(self, kid: str):
        with self._lock:
            if time.time() > self._expires or kid not in self._keys:
                try:
                    self._refresh()
                except Exception:  # noqa: BLE001
                    logger.exception("could not refresh Firebase certificates")
            return self._keys.get(kid)

    def verify(self, id_token: str) -> dict:
        """Return the decoded claims or raise ``ValueError``."""
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as e:
            raise ValueError("Malformed token.") from e
        key = self._key(header.get("kid", ""))
        if key is None:
            raise ValueError("Unknown signing key.")
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self.project_id,
                issuer=f"https://securetoken.google.com/{self.project_id}",
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid token: {e}") from e
        if not claims.get("sub"):
            raise ValueError("Token has no subject.")
        return claims
