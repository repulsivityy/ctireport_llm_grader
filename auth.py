"""
Identity resolution and authentication for the CTI Report Grader.

Supports:
  1. Streamlit Native Google OAuth (st.login / st.logout, st.user).
  2. Google Identity-Aware Proxy (IAP) signed headers when behind IAP.
  3. Local development fallback (ALLOW_INSECURE_LOCAL_AUTH=true).
"""

import os
from typing import Optional

import streamlit as st

_IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
_IAP_JWT_HEADER = "X-Goog-IAP-JWT-Assertion"
_IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


def setup_streamlit_auth():
    """
    Ensures .streamlit/secrets.toml exists if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
    are supplied via environment variables, enabling st.login() / st.logout().
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("REDIRECT_URI", "").strip()
    cookie_secret = os.getenv("COOKIE_SECRET", "cti-grader-secure-cookie-key-32chars").strip()

    if client_id and client_secret:
        root_dir = os.path.dirname(__file__)
        streamlit_dir = os.path.join(root_dir, ".streamlit")
        os.makedirs(streamlit_dir, exist_ok=True)
        secrets_path = os.path.join(streamlit_dir, "secrets.toml")

        if not redirect_uri:
            redirect_uri = "https://cti-report-grader-5bemo556hq-as.a.run.app/oauth2callback"

        toml_content = f"""[auth]
redirect_uri = "{redirect_uri}"
cookie_secret = "{cookie_secret}"

[auth.google]
client_id = "{client_id}"
client_secret = "{client_secret}"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
"""
        with open(secrets_path, "w", encoding="utf-8") as f:
            f.write(toml_content)


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
    # 1. First check Streamlit native OIDC auth (st.user)
    oidc_email = _email_from_streamlit_oidc()
    if oidc_email:
        return oidc_email

    # 2. Check IAP headers if running behind Google Cloud IAP
    headers = _request_headers()
    if _IAP_JWT_HEADER.lower() in headers:
        verified = _email_from_verified_jwt(headers)
        if verified:
            return verified
        if not os.getenv("IAP_JWT_AUDIENCE", "").strip():
            header_email = _email_from_iap_header(headers)
            if header_email:
                return header_email
        return None

    return _email_from_iap_header(headers)
