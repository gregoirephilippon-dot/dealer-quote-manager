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


def _current_password_fingerprint(email: str) -> str | None:
    """HMAC of stored password hash; no secret/password hash is exposed in the cookie."""
    try:
        import server_user_model as identity
        user = identity.get_user_by_email(email)
        if user is None or user["status"] != "active":
            return None
        # get_user_by_email intentionally excludes password_hash.
        # Read it separately without altering users or their passwords.
        with identity.get_connection() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ? AND status = 'active'",
                (user["id"],),
            ).fetchone()
        password_hash = row["password_hash"] if row else None
        if not password_hash:
            return None
        return hmac.new(
            _get_secret_key(),
            b"session-password-v2\0" + str(password_hash).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    except Exception:
        return None


def create_session_token(email: str) -> str:
    email = email.lower().strip()
    fingerprint = _current_password_fingerprint(email)
    if not fingerprint:
        raise ValueError("Compte non disponible pour la connexion")
    expires_at = int(time.time()) + SESSION_DURATION_SECONDS
    payload = f"v2|{email}|{expires_at}|{fingerprint}"
    signature = hmac.new(_get_secret_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw_token = f"{payload}|{signature}"
    return base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("utf-8")


def verify_session_token(token: str) -> str | None:
    try:
        raw_token = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        version, email, expires_text, fingerprint, signature = raw_token.split("|", 4)
        if version != "v2" or not email or len(email) > 320:
            return None
        email = email.lower().strip()
        payload = f"v2|{email}|{expires_text}|{fingerprint}"
        expected_signature = hmac.new(_get_secret_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        if int(expires_text) < int(time.time()):
            return None
        current_fingerprint = _current_password_fingerprint(email)
        if not current_fingerprint or not hmac.compare_digest(fingerprint, current_fingerprint):
            return None
        return email
    except Exception:
        return None
