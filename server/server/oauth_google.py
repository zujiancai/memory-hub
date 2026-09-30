"""Small Google OAuth 2.0 (PKCE) helper.

Phase 1 handles the authorization-code + PKCE dance for the SPA. Two
functions matter:

- ``build_authorization_url``: given a PKCE verifier the caller generates,
  return the Google consent URL and the code_challenge to send to the SPA.
- ``exchange_code_for_userinfo``: given ``{code, code_verifier}`` from the
  SPA, exchange with Google, then fetch userinfo. Returns
  ``(google_sub, email, name)``.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Tuple

import requests

AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def generate_pkce_pair() -> Tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorization_url(client_id: str, redirect_uri: str, code_challenge: str, state: str) -> str:
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}"


def exchange_code_for_userinfo(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> Tuple[str, str, str]:
    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        timeout=15,
    )
    resp.raise_for_status()
    token_response = resp.json()
    access_token = token_response.get("access_token")
    if not access_token:
        raise RuntimeError("Google token response missing access_token")

    info_resp = requests.get(
        USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    info_resp.raise_for_status()
    payload = info_resp.json()
    return (
        str(payload["sub"]),
        payload.get("email", ""),
        payload.get("name", "") or payload.get("email", ""),
    )
