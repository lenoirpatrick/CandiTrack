"""Clients minimaux pour les API d'IA générative (issues #33, #34).

Le module de coaching appelle, au choix, l'API Gemini de Google ou l'API
Mistral, en HTTP direct (stdlib uniquement, comme :mod:`tracking.logos`), pour
éviter une dépendance lourde. La clé et le modèle proviennent de
:class:`tracking.models.AIConfig` (saisis par l'utilisateur depuis la page
d'options) ; :func:`generate` aiguille vers le bon fournisseur.

Gemini accepte des pièces jointes « inline » (CV en PDF/image/texte) via
``inline_data`` ; Mistral fonctionne en texte seul ici.
"""

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from dataclasses import dataclass

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# Types de pièces jointes que Gemini sait lire directement (issue #33).
SUPPORTED_MIME_PREFIXES = ("application/pdf", "image/", "text/")

# Délai max d'un appel (le coaching analyse parfois un CV : laisser de la marge).
TIMEOUT = 60


class AIError(Exception):
    """Erreur d'appel à l'IA, avec un message présentable à l'utilisateur."""


@dataclass
class GenerationResult:
    """Texte généré et consommation de tokens associée (issue #36)."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


def guess_mime(filename):
    """Type MIME d'une pièce jointe, ``None`` si non géré par Gemini."""
    mime, _ = mimetypes.guess_type(filename)
    if mime and mime.startswith(SUPPORTED_MIME_PREFIXES):
        return mime
    return None


def generate(prompt, *, api_key, model, provider="gemini", attachments=None):
    """Appelle le fournisseur ``provider`` et renvoie un :class:`GenerationResult`.

    ``attachments`` (liste de tuples ``(mime_type, bytes)``) n'est exploité que
    par Gemini. Lève :class:`AIError` sur tout problème (clé invalide, réseau,
    réponse vide…).
    """
    if not api_key:
        raise AIError("Aucune clé API configurée.")
    if provider == "mistral":
        return _mistral_generate(prompt, api_key=api_key, model=model)
    return _gemini_generate(
        prompt, api_key=api_key, model=model, attachments=attachments
    )


def _request_json(url, headers, payload):
    """POST JSON commun aux fournisseurs : renvoie le corps parsé."""
    request = urllib.request.Request(
        url, data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AIError(_http_error_message(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AIError(
            "Impossible de joindre l'API IA (réseau ou délai dépassé)."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AIError("Réponse illisible de l'API IA.") from exc


def _gemini_generate(prompt, *, api_key, model, attachments=None):
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
        {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.7}}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    body = _request_json(GEMINI_URL.format(model=model), headers, payload)
    return _parse_gemini(body)


def _mistral_generate(prompt, *, api_key, model):
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = _request_json(MISTRAL_URL, headers, payload)
    return _parse_mistral(body)


def _http_error_message(exc):
    """Message lisible à partir d'une erreur HTTP de l'API."""
    detail = ""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        error = body.get("error", body)
        if isinstance(error, dict):
            detail = error.get("message", "")
        else:
            detail = str(error)
    except (ValueError, OSError):
        pass
    if exc.code in (400, 401, 403):
        return f"Clé API refusée ou requête invalide. {detail}".strip()
    if exc.code == 404:
        return f"Modèle introuvable. {detail}".strip()
    if exc.code == 429:
        return "Quota dépassé : réessayez plus tard."
    return f"Erreur de l'API IA (HTTP {exc.code}). {detail}".strip()


def _parse_gemini(body):
    """Texte + tokens de la première réponse Gemini (issue #36)."""
    candidates = body.get("candidates") or []
    if not candidates:
        reason = body.get("promptFeedback", {}).get("blockReason")
        if reason:
            raise AIError(f"Réponse bloquée par l'IA ({reason}).")
        raise AIError("L'IA n'a renvoyé aucune réponse.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise AIError("L'IA a renvoyé une réponse vide.")
    usage = body.get("usageMetadata", {})
    return GenerationResult(
        text=text,
        prompt_tokens=usage.get("promptTokenCount", 0),
        completion_tokens=usage.get("candidatesTokenCount", 0),
        total_tokens=usage.get("totalTokenCount", 0),
    )


def _parse_mistral(body):
    """Texte + tokens du premier message de la réponse Mistral (issue #36)."""
    choices = body.get("choices") or []
    if not choices:
        raise AIError("L'IA n'a renvoyé aucune réponse.")
    text = (choices[0].get("message", {}).get("content") or "").strip()
    if not text:
        raise AIError("L'IA a renvoyé une réponse vide.")
    usage = body.get("usage", {})
    return GenerationResult(
        text=text,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )
