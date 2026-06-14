"""Client minimal pour l'API Gemini (issue #33).

Le module de coaching appelle l'API « generateContent » de Google Generative
Language en HTTP direct (stdlib uniquement, comme :mod:`tracking.logos`), pour
éviter une dépendance lourde. La clé et le modèle proviennent de
:class:`tracking.models.AIConfig` (saisis par l'utilisateur depuis la page d'aide).

L'appel accepte des pièces jointes « inline » (CV en PDF/image/texte) que Gemini
sait analyser nativement via ``inline_data``.
"""

import base64
import json
import mimetypes
import urllib.error
import urllib.request

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Types de pièces jointes que Gemini sait lire directement (issue #33).
SUPPORTED_MIME_PREFIXES = ("application/pdf", "image/", "text/")

# Délai max d'un appel (le coaching analyse parfois un CV : laisser de la marge).
TIMEOUT = 60


class AIError(Exception):
    """Erreur d'appel à l'IA, avec un message présentable à l'utilisateur."""


def guess_mime(filename):
    """Type MIME d'une pièce jointe, ``None`` si non géré par Gemini."""
    mime, _ = mimetypes.guess_type(filename)
    if mime and mime.startswith(SUPPORTED_MIME_PREFIXES):
        return mime
    return None


def generate(prompt, *, api_key, model, attachments=None):
    """Appelle Gemini et renvoie le texte généré.

    ``attachments`` est une liste de tuples ``(mime_type, bytes)`` jointes au
    prompt (ex. un CV). Lève :class:`AIError` sur tout problème (clé invalide,
    réseau, réponse vide…).
    """
    if not api_key:
        raise AIError("Aucune clé API Gemini configurée.")

    parts = [{"text": prompt}]
    for mime_type, data in attachments or []:
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(data).decode("ascii"),
                }
            }
        )

    payload = json.dumps(
        {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.7},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        API_URL.format(model=model),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AIError(_http_error_message(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AIError(
            "Impossible de joindre l'API Gemini (réseau ou délai dépassé)."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AIError("Réponse illisible de l'API Gemini.") from exc

    return _extract_text(body)


def _http_error_message(exc):
    """Message lisible à partir d'une erreur HTTP de l'API."""
    detail = ""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        detail = body.get("error", {}).get("message", "")
    except (ValueError, OSError):
        pass
    if exc.code in (400, 403):
        return f"Clé API Gemini refusée ou requête invalide. {detail}".strip()
    if exc.code == 404:
        return f"Modèle Gemini introuvable. {detail}".strip()
    if exc.code == 429:
        return "Quota Gemini dépassé : réessayez plus tard."
    return f"Erreur Gemini (HTTP {exc.code}). {detail}".strip()


def _extract_text(body):
    """Concatène le texte des parts de la première réponse."""
    candidates = body.get("candidates") or []
    if not candidates:
        # Réponse bloquée par les filtres de sécurité, ou vide.
        reason = body.get("promptFeedback", {}).get("blockReason")
        if reason:
            raise AIError(f"Réponse bloquée par Gemini ({reason}).")
        raise AIError("L'IA n'a renvoyé aucune réponse.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise AIError("L'IA a renvoyé une réponse vide.")
    return text
