import hashlib
import secrets


PBKDF2_ITERATIONS = 260000


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Mot de passe vide interdit")

    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()

    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${password_hash}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_hash = stored_hash.split("$", 3)
        iterations = int(iterations_text)

        if algorithm != "pbkdf2_sha256":
            return False

        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()

        return secrets.compare_digest(password_hash, expected_hash)
    except Exception:
        return False


if __name__ == "__main__":
    demo_hash = hash_password("test1234")
    print("Hash créé :", demo_hash)
    print("Bon mot de passe :", verify_password("test1234", demo_hash))
    print("Mauvais mot de passe :", verify_password("erreur", demo_hash))
