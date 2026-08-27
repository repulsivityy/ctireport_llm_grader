"""
Identity resolution for the CTI Report Grader.

The grader is designed to run behind Google Identity-Aware Proxy (IAP). The user's
identity is taken ONLY from a trusted source - never from a form field - so that a
student cannot unlock the instructor gradebook by typing an instructor's address.

Resolution order:
  1. IAP: the signed ``X-Goog-IAP-JWT-Assertion`` header (verified if IAP_JWT_AUDIENCE
     is configured), otherwise the ``X-Goog-Authenticated-User-Email`` header that IAP
     sets after it has authenticated the caller.
  2. Streamlit native OIDC auth (``st.user`` / ``st.experimental_user``).
  3. Local development only: if ALLOW_INSECURE_LOCAL_AUTH=true, fall back to a manually
     entered address. This must never be set in a deployed environment.

If none of these yield an address the app must refuse to render (fail closed).
"""

import os
from typing import Optional

import streamlit as st

_IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
_IAP_JWT_HEADER = "X-Goog-IAP-JWT-Assertion"
_IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


def allow_insecure_local_auth() -> bool:
    return os.getenv("ALLOW_INSECURE_LOCAL_AUTH", "").strip().lower() in ("1", "true", "yes")


def _clean(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    # IAP prefixes the identity provider, e.g. "accounts.google.com:user@example.com".
    if ":" in email:
        email = email.split(":", 1)[1]
    email = email.strip().lower()
    return email or None


def _request_headers() -> dict:
    """Return request headers with lower-cased keys (HTTP header names are case-insensitive)."""
    try:
        return {str(k).lower(): v for k, v in dict(st.context.headers).items()}  # Streamlit >= 1.37
    except Exception:
        return {}


def _email_from_verified_jwt(headers: dict) -> Optional[str]:
    """Verify the IAP JWT assertion when an expected audience is configured."""
    audience = os.getenv("IAP_JWT_AUDIENCE", "").strip()
    assertion = headers.get(_IAP_JWT_HEADER.lower())
    if not audience or not assertion:
        return None
    try:
        from google.auth.transport import requests as ga_requests
        from google.oauth2 import id_token

        payload = id_token.verify_token(
            assertion,
            ga_requests.Request(),
            audience=audience,
            certs_url=_IAP_CERTS_URL,
        )
        return _clean(payload.get("email"))
    except Exception:
        # A present-but-invalid assertion is a hard failure, not a fall-through.
        return None


def _email_from_iap_header(headers: dict) -> Optional[str]:
    return _clean(headers.get(_IAP_EMAIL_HEADER.lower()))


def _email_from_streamlit_oidc() -> Optional[str]:
    user = getattr(st, "user", None) or getattr(st, "experimental_user", None)
    if user is None:
        return None
    try:
        if not getattr(user, "is_logged_in", False):
            return None
        return _clean(getattr(user, "email", None))
    except Exception:
        return None


def get_authenticated_email() -> Optional[str]:
    """Return the trusted, verified caller address, or None if unauthenticated."""
    headers = _request_headers()

    if _IAP_JWT_HEADER.lower() in headers:
        verified = _email_from_verified_jwt(headers)
        if verified:
            return verified
        # JWT present: only trust the companion header if we were not asked to verify.
        if not os.getenv("IAP_JWT_AUDIENCE", "").strip():
            header_email = _email_from_iap_header(headers)
            if header_email:
                return header_email
        return None

    return _email_from_iap_header(headers) or _email_from_streamlit_oidc()
