"""KPI computation for the statistics page (issue #367).

Everything is derived from :class:`Candidature` and its
:class:`StatusHistory` so the funnel reflects statuses *ever reached*, not just
the current one (a candidature that had an interview then a refusal still
counts in the interview funnel).
"""

from django.db.models import Count
from django.db.models.functions import TruncMonth

from .models import Canal, Candidature, JobSite, MotifCloture, Statut, StatusHistory

# A reply from the company = it reacted to the application in any way.
RESPONSE_STATUSES = {
    Statut.ENTRETIEN_PLANIFIE,
    Statut.ENTRETIEN_PASSE,
    Statut.REFUS,
    Statut.OFFRE,
}
INTERVIEW_STATUSES = {Statut.ENTRETIEN_PLANIFIE, Statut.ENTRETIEN_PASSE, Statut.OFFRE}
# Still waiting for any reply.
PENDING_STATUSES = {Statut.ENVOYEE, Statut.RELANCEE, Statut.SANS_REPONSE}


# Couleurs du graphique circulaire par source (issue #15), accordées à la
# palette du projet (voir docs/palette.md) tout en restant distinguables.
SOURCE_COLORS = [
    "#5BC0BE", "#3A506B", "#6FB1FC", "#E9C46A",
    "#E76F51", "#9B8CFF", "#2A9D8F",
]


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else 0.0


def _donut_segments(rows):
    """Annotate breakdown rows with circular-chart geometry (issue #15).

    Uses an SVG circle of ``pathLength=100`` so ``stroke-dasharray`` values
    are percentages and segments chain via ``stroke-dashoffset``.
    """
    total = sum(r["count"] for r in rows)
    cumulative = 0.0
    for i, r in enumerate(rows):
        pct = (100 * r["count"] / total) if total else 0.0
        r["percent"] = round(pct, 1)
        r["color"] = SOURCE_COLORS[i % len(SOURCE_COLORS)]
        r["dash"] = round(pct, 3)
        r["gap"] = round(100 - pct, 3)
        r["offset"] = round(25 - cumulative, 3)
        cumulative += pct
    return total


def _ever_reached(statuses):
    """Set of candidature ids whose current OR historical status is in ``statuses``."""
    ids = set(
        Candidature.objects.filter(statut__in=statuses).values_list("id", flat=True)
    )
    ids |= set(
        StatusHistory.objects.filter(statut__in=statuses).values_list(
            "candidature_id", flat=True
        )
    )
    return ids


def _average_response_delay():
    """Average number of days between sending and the first reply, or None."""
    delays = []
    candidatures = Candidature.objects.filter(
        date_envoi__isnull=False
    ).prefetch_related("status_history")
    for c in candidatures:
        reply_dates = [
            h.date for h in c.status_history.all() if h.statut in RESPONSE_STATUSES
        ]
        if reply_dates:
            delta = (min(reply_dates).date() - c.date_envoi).days
            if delta >= 0:
                delays.append(delta)
    if not delays:
        return None
    return round(sum(delays) / len(delays), 1)


def compute_stats():
    qs = Candidature.objects.all()
    total = qs.count()

    responded = len(_ever_reached(RESPONSE_STATUSES))
    interviewed = len(_ever_reached(INTERVIEW_STATUSES))
    offers = qs.filter(statut=Statut.OFFRE).count()
    rejected = qs.filter(statut=Statut.REFUS).count()
    pending = qs.filter(statut__in=PENDING_STATUSES).count()

    kpis = {
        "total": total,
        "responded": responded,
        "response_rate": _pct(responded, total),
        "interviewed": interviewed,
        "interview_rate": _pct(interviewed, total),
        "offers": offers,
        "offer_rate": _pct(offers, total),
        "rejected": rejected,
        "pending": pending,
        "avg_response_delay": _average_response_delay(),
    }

    # Breakdown by status (ordered by the canonical status order).
    status_counts = {
        row["statut"]: row["count"]
        for row in qs.values("statut").annotate(count=Count("id"))
    }
    by_status = [
        {"label": label, "count": status_counts.get(value, 0)}
        for value, label in Statut.choices
        if status_counts.get(value, 0)
    ]

    # Breakdown by source site (issue #52) : la source est un JobSite ; les
    # candidatures sans source sont regroupées sous « Non précisée ».
    by_source = [
        {"label": row["source__name"] or "Non précisée", "count": row["count"]}
        for row in (
            qs.values("source__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if row["count"]
    ]
    source_total = _donut_segments(by_source)

    # Breakdown by source site type (issue #55) : ESN / Direct / Généraliste.
    # Les candidatures sans source (donc sans type) sont regroupées à part.
    type_labels = dict(JobSite.Type.choices)
    by_type = [
        {
            "label": type_labels.get(row["source__type"], "Non précisé"),
            "count": row["count"],
        }
        for row in (
            qs.values("source__type")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if row["count"]
    ]
    type_total = _donut_segments(by_type)

    # Breakdown by closing reason (motif de clôture) : uniquement les
    # candidatures clôturées (motif renseigné), proportions en donut.
    motif_labels = dict(MotifCloture.choices)
    by_motif = [
        {
            "label": motif_labels.get(row["motif_cloture"], row["motif_cloture"]),
            "count": row["count"],
        }
        for row in (
            qs.exclude(motif_cloture="")
            .values("motif_cloture")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if row["count"]
    ]
    motif_total = _donut_segments(by_motif)

    # Breakdown by sending channel / mode de canal entrant (issue #56), ordonné
    # selon l'ordre canonique des canaux.
    canal_counts = {
        row["canal_envoi"]: row["count"]
        for row in qs.values("canal_envoi").annotate(count=Count("id"))
    }
    by_canal = [
        {"label": label, "count": canal_counts.get(value, 0)}
        for value, label in Canal.choices
        if canal_counts.get(value, 0)
    ]

    # Applications per month (chronological).
    by_month = [
        {"month": row["m"], "count": row["count"]}
        for row in (
            qs.filter(date_envoi__isnull=False)
            .annotate(m=TruncMonth("date_envoi"))
            .values("m")
            .annotate(count=Count("id"))
            .order_by("m")
        )
    ]

    return {
        "kpis": kpis,
        "by_status": by_status,
        "by_source": by_source,
        "by_type": by_type,
        "by_motif": by_motif,
        "by_canal": by_canal,
        "by_month": by_month,
        "source_total": source_total,
        "type_total": type_total,
        "motif_total": motif_total,
        "max_status": max((r["count"] for r in by_status), default=0),
        "max_source": max((r["count"] for r in by_source), default=0),
        "max_canal": max((r["count"] for r in by_canal), default=0),
        "max_month": max((r["count"] for r in by_month), default=0),
    }
