"""Coaching IA : collecte du contexte et construction des prompts (issue #33).

Sépare la logique métier (ce qu'on demande à l'IA, à partir de quelles données)
du client HTTP brut (:mod:`tracking.ai`). Deux usages :

- :func:`coaching_advice` — un bilan global à partir du CV, des postes visés et
  des retours reçus (volume de candidatures, motifs de refus…).
- :func:`relance_email` — un brouillon de mail de relance pour une candidature.
- :func:`analyze_cv` — extraction des informations principales d'un CV (issue #44).
"""

import json

from django.db.models import Count
from django.utils import timezone

from . import ai
from .models import CV, AIConfig, AIUsage, Candidature, MotifCloture, Statut
from .statistics import compute_stats

# Taille max du CV joint (octets) : au-delà, on s'abstient pour ne pas alourdir
# l'appel (un CV dépasse rarement quelques centaines de Ko).
MAX_CV_BYTES = 5 * 1024 * 1024


def cv_attachment(cv):
    """``(mime_type, bytes)`` d'un CV donné pour Gemini, ou ``None``."""
    if not cv or not cv.file:
        return None
    mime = ai.guess_mime(cv.file.name)
    if not mime:
        return None
    try:
        if cv.file.size > MAX_CV_BYTES:
            return None
        with cv.file.open("rb") as handle:
            return (mime, handle.read())
    except (OSError, ValueError):
        return None


def _latest_cv_attachment():
    """Renvoie ``(mime_type, bytes)`` du dernier CV, ou ``None``."""
    return cv_attachment(CV.objects.order_by("-uploaded_at").first())


def _cv_text(cv):
    """Texte brut d'un CV au format texte (fournisseurs autres que Gemini)."""
    if not cv or not cv.file:
        return ""
    mime = ai.guess_mime(cv.file.name) or ""
    if not mime.startswith("text/"):
        return ""
    try:
        with cv.file.open("rb") as handle:
            raw = handle.read(MAX_CV_BYTES)
    except (OSError, ValueError):
        return ""
    return raw.decode("utf-8", errors="replace").strip()


def _run(config, prompt, attachments=None):
    """Appelle l'IA, journalise la consommation (issue #36) et renvoie le texte."""
    result = ai.generate(
        prompt,
        provider=config.provider,
        api_key=config.api_key,
        model=config.model,
        attachments=attachments,
    )
    AIUsage.record(config.provider, config.model, result)
    return result.text


def _context_summary():
    """Synthèse texte des candidatures pour nourrir le prompt de coaching."""
    stats = compute_stats()
    kpis = stats["kpis"]

    lines = [
        f"- Total de candidatures : {kpis['total']}",
        f"- Réponses reçues : {kpis['responded']} ({kpis['response_rate']} %)",
        f"- Entretiens obtenus : {kpis['interviewed']} ({kpis['interview_rate']} %)",
        f"- Offres : {kpis['offers']} · Refus : {kpis['rejected']} · "
        f"En attente : {kpis['pending']}",
    ]
    if kpis["avg_response_delay"] is not None:
        lines.append(f"- Délai moyen de réponse : {kpis['avg_response_delay']} jours")

    # Postes visés (distincts, non vides).
    postes = list(
        Candidature.objects.exclude(poste="")
        .values_list("poste", flat=True)
        .distinct()
    )
    if postes:
        lines.append("- Postes visés : " + ", ".join(sorted(set(postes))[:30]))

    # Motifs de refus / clôture, du plus fréquent au moins fréquent.
    motifs = (
        Candidature.objects.exclude(motif_cloture="")
        .values("motif_cloture")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    labels = dict(MotifCloture.choices)
    motif_lines = [
        f"{labels.get(row['motif_cloture'], row['motif_cloture'])} ({row['count']})"
        for row in motifs
    ]
    if motif_lines:
        lines.append("- Motifs de clôture : " + ", ".join(motif_lines))

    return "\n".join(lines)


def coaching_advice(config=None):
    """Demande un bilan de coaching à l'IA et renvoie le texte (Markdown)."""
    config = config or AIConfig.load()
    # Seul Gemini analyse le CV en pièce jointe ; Mistral reste en texte seul.
    attachment = None
    if config.provider == AIConfig.Provider.GEMINI:
        attachment = _latest_cv_attachment()
    cv_note = (
        "Le CV de la personne est joint à ce message ; appuie-toi dessus."
        if attachment
        else "Aucun CV exploitable n'est disponible : raisonne sur les statistiques."
    )

    prompt = (
        "Tu es un coach en recherche d'emploi bienveillant et concret, qui "
        "s'adresse en français et tutoie la personne.\n\n"
        "Voici le bilan chiffré de sa recherche d'emploi :\n"
        f"{_context_summary()}\n\n"
        f"{cv_note}\n\n"
        "Rédige un retour structuré en Markdown, avec ces trois sections :\n"
        "1. **Positionnement** — adapter son positionnement et/ou les postes "
        "visés au regard du CV et des retours reçus.\n"
        "2. **Actions à réaliser** — des actions concrètes et priorisées "
        "(notamment les relances pertinentes).\n"
        "3. **Encouragement** — un mot bref et motivant.\n\n"
        "Reste synthétique (pas de blabla), factuel et actionnable."
    )

    return _run(config, prompt, attachments=[attachment] if attachment else None)


def relance_email(candidature, config=None):
    """Génère un brouillon de mail de relance pour une candidature."""
    config = config or AIConfig.load()

    infos = [
        f"- Entreprise : {candidature.entreprise or 'non précisée'}",
        f"- Poste : {candidature.poste or 'non précisé'}",
        f"- Statut actuel : {candidature.get_statut_display()}",
        f"- Canal d'envoi : {candidature.get_canal_envoi_display()}",
    ]
    if candidature.date_envoi:
        infos.append(f"- Date d'envoi de la candidature : {candidature.date_envoi:%d/%m/%Y}")
    if candidature.notes:
        infos.append(f"- Notes personnelles : {candidature.notes}")

    prompt = (
        "Tu es un assistant qui rédige des mails de relance professionnels en "
        "français, polis, concis et personnalisés.\n\n"
        "Rédige un mail de relance pour la candidature suivante :\n"
        + "\n".join(infos)
        + "\n\nConsignes :\n"
        "- Ton courtois et professionnel, sans servilité.\n"
        "- Rappelle brièvement la candidature et réaffirme la motivation.\n"
        "- Termine par une formule d'ouverture (disponibilité pour un échange).\n"
        "- Propose un objet de mail puis le corps. N'invente aucune information "
        "factuelle absente ci-dessus (laisse des crochets [à compléter] au besoin)."
    )

    return _run(config, prompt)


# --- Analyse de CV (issue #44) --------------------------------------------

# Schéma JSON attendu de l'IA. On l'impose dans le prompt et on normalise la
# réponse pour que le gabarit puisse l'afficher sans surprise.
CV_ANALYSIS_PROMPT = (
    "Tu es un assistant RH qui analyse des CV. À partir du CV fourni, extrais "
    "les informations principales et renvoie UNIQUEMENT un objet JSON valide, "
    "sans texte autour ni balises de code, avec exactement ces clés :\n"
    '- "titre_profil" : chaîne (intitulé/poste principal du profil) ;\n'
    '- "experiences" : liste d\'objets '
    '{"poste", "entreprise", "periode", "description"} ;\n'
    '- "formations" : liste d\'objets {"intitule", "etablissement", "periode"} ;\n'
    '- "competences" : liste de chaînes ;\n'
    '- "langues" : liste de chaînes ;\n'
    '- "infos" : chaîne (informations diverses : contact, certifications, '
    "centres d'intérêt…).\n"
    "Utilise une liste vide ou une chaîne vide quand l'information est absente. "
    "N'invente rien. Réponds en français."
)


def _as_text(value):
    """Chaîne nettoyée à partir d'une valeur JSON quelconque."""
    return str(value).strip() if value is not None else ""


def _as_str_list(value):
    """Liste de chaînes non vides à partir d'une valeur JSON."""
    if not isinstance(value, list):
        return []
    return [_as_text(item) for item in value if _as_text(item)]


def _as_dict_list(value, keys):
    """Liste de dictionnaires restreints à ``keys`` (entrées vides ignorées)."""
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row = {key: _as_text(item.get(key)) for key in keys}
        if any(row.values()):
            rows.append(row)
    return rows


def _normalize_cv_analysis(data):
    """Structure stable de l'analyse, quel que soit le détail renvoyé par l'IA."""
    return {
        "titre_profil": _as_text(data.get("titre_profil")),
        "experiences": _as_dict_list(
            data.get("experiences"),
            ["poste", "entreprise", "periode", "description"],
        ),
        "formations": _as_dict_list(
            data.get("formations"), ["intitule", "etablissement", "periode"]
        ),
        "competences": _as_str_list(data.get("competences")),
        "langues": _as_str_list(data.get("langues")),
        "infos": _as_text(data.get("infos")),
    }


def _parse_cv_analysis(text):
    """Parse la réponse de l'IA en dict normalisé, ou ``None`` si illisible."""
    cleaned = text.strip()
    # Retire d'éventuelles clôtures Markdown (```json … ```), tolérées en sortie.
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_cv_analysis(data)


def analyze_cv(cv, config=None):
    """Analyse un CV via l'IA et enregistre les infos extraites (issue #44).

    L'analyse est remise à zéro avant chaque passe. Le CV est joint en pièce
    jointe pour Gemini ; pour les autres fournisseurs, seul un CV au format
    texte peut être lu. Lève :class:`ai.AIError` si l'appel échoue ; en cas de
    réponse non exploitable ou de format illisible, enregistre un message
    d'erreur sur le CV (sans interrompre le chargement).
    """
    config = config or AIConfig.load()
    cv.reset_analysis()

    attachments = None
    extra = ""
    if config.provider == AIConfig.Provider.GEMINI:
        attachment = cv_attachment(cv)
        if attachment:
            attachments = [attachment]
            extra = "\n\nLe CV est joint à ce message ; analyse-le."
    if attachments is None:
        text = _cv_text(cv)
        if not text:
            cv.analysis_error = (
                "Ce format de CV ne peut être lu que par Google Gemini. "
                "Choisis Gemini dans Options → IA, ou charge un CV au format texte."
            )
            cv.save(update_fields=cv.ANALYSIS_FIELDS)
            return cv
        extra = "\n\nVoici le contenu texte du CV :\n" + text

    result = ai.generate(
        CV_ANALYSIS_PROMPT + extra,
        provider=config.provider,
        api_key=config.api_key,
        model=config.model,
        attachments=attachments,
    )
    AIUsage.record(config.provider, config.model, result)

    data = _parse_cv_analysis(result.text)
    if data is None:
        cv.analysis_error = "L'IA n'a pas renvoyé d'analyse exploitable."
    else:
        cv.analysis = data
        cv.analyzed_at = timezone.now()
        cv.analysis_provider = config.provider
        cv.analysis_model = config.model
    cv.save(update_fields=cv.ANALYSIS_FIELDS)
    return cv
