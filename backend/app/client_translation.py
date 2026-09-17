import json
import os
import urllib.error
import urllib.request

from database import get_connection


_CACHE_READY = False
_DEEPL_UNAVAILABLE = False


def _ensure_cache():
    global _CACHE_READY

    if _CACHE_READY:
        return

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS client_translation_cache (
                source_text TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                detected_source_language TEXT,
                translated_text TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source_text, target_lang)
            )
            """
        )
        conn.commit()

    _CACHE_READY = True


def _translate_with_deepl(source_text):
    global _DEEPL_UNAVAILABLE

    if _DEEPL_UNAVAILABLE:
        return None

    api_key = os.getenv("DEEPL_API_KEY", "").strip()

    if not api_key:
        return None

    payload = json.dumps(
        {
            "text": [source_text],
            "target_lang": "FR",
        }
    ).encode("utf-8")

    endpoints = (
        "https://api-free.deepl.com/v2/translate",
        "https://api.deepl.com/v2/translate",
    )

    for endpoint in endpoints:
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"DeepL-Auth-Key {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "DealerQuoteManager/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            translation = data["translations"][0]

            detected_language = str(
                translation.get("detected_source_language") or ""
            ).upper()

            translated_text = str(
                translation.get("text") or source_text
            ).strip()

            return detected_language, translated_text

        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                continue

            _DEEPL_UNAVAILABLE = True
            return None

        except Exception:
            _DEEPL_UNAVAILABLE = True
            return None

    _DEEPL_UNAVAILABLE = True
    return None


def translate_service_name_for_client(value):
    source_text = str(value or "").strip()

    if not source_text:
        return source_text

    _ensure_cache()

    with get_connection() as conn:
        cached = conn.execute(
            """
            SELECT translated_text
            FROM client_translation_cache
            WHERE source_text = ?
              AND target_lang = 'FR'
            """,
            (source_text,),
        ).fetchone()

    if cached is not None:
        return cached["translated_text"]

    result = _translate_with_deepl(source_text)

    if result is None:
        return source_text

    detected_language, translated_text = result

    if detected_language == "EN":
        result_text = translated_text
    else:
        result_text = source_text

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO client_translation_cache (
                source_text,
                target_lang,
                detected_source_language,
                translated_text,
                updated_at
            )
            VALUES (?, 'FR', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_text, target_lang)
            DO UPDATE SET
                detected_source_language = excluded.detected_source_language,
                translated_text = excluded.translated_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source_text,
                detected_language,
                result_text,
            ),
        )
        conn.commit()

    return result_text