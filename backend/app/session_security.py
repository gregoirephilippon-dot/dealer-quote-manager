import base64
import hashlib
import hmac
import time

import app_config as config


SESSION_COOKIE_NAME = "dealer_quote_session"
SESSION_DURATION_SECONDS = 8 * 60 * 60


def _get_secret_key() -> bytes:
    secret = config.SECRET_KEY or "dev-secret-change-me"
    return secret.encode("utf-8")


def create_session_token(email: str) -> str:
    email = email.lower().strip()
    expires_at = int(time.time()) + SESSION_DURATION_SECONDS

    payload = f"{email}|{expires_at}"
    signature = hmac.new(
        _get_secret_key(),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    raw_token = f"{payload}|{signature}"
    return base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("utf-8")


def verify_session_token(token: str) -> str | None:
    try:
        raw_token = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        email, expires_text, signature = raw_token.split("|", 2)

        payload = f"{email}|{expires_text}"
        expected_signature = hmac.new(
            _get_secret_key(),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return None

        if int(expires_text) < int(time.time()):
            return None

        return email.lower().strip()
    except Exception:
        return None
