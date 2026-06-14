"""Coaching IA : collecte du contexte et construction des prompts (issue #33).

Sépare la logique métier (ce qu'on demande à l'IA, à partir de quelles données)
du client HTTP brut (:mod:`tracking.ai`). Deux usages :

- :func:`coaching_advice` — un bilan global à partir du CV, des postes visés et
  des retours reçus (volume de candidatures, motifs de refus…).
- :func:`relance_email` — un brouillon de mail de relance pour une candidature.
"""

from django.db.models import Count

from . import ai
from .models import CV, AIConfig, Candidature, MotifCloture, Statut
from .statistics import compute_stats

# Taille max du CV joint (octets) : au-delà, on s'abstient pour ne pas alourdir
# l'appel (un CV dépasse rarement quelques centaines de Ko).
MAX_CV_BYTES = 5 * 1024 * 1024


def _latest_cv_attachment():
    """Renvoie ``(mime_type, bytes)`` du dernier CV, ou ``None``."""
    cv = CV.objects.order_by("-uploaded_at").first()
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

    return ai.generate(
        prompt,
        provider=config.provider,
        api_key=config.api_key,
        model=config.model,
        attachments=[attachment] if attachment else None,
    )


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

    return ai.generate(
        prompt, provider=config.provider, api_key=config.api_key, model=config.model
    )
