"""KPI computation for the statistics page (issue #367).

Everything is derived from :class:`Candidature` and its
:class:`StatusHistory` so the funnel reflects statuses *ever reached*, not just
the current one (a candidature that had an interview then a refusal still
counts in the interview funnel).
"""

from django.db.models import Count
from django.db.models.functions import TruncMonth

from .models import Candidature, Source, Statut, StatusHistory

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


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else 0.0


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

    # Breakdown by source.
    source_counts = {
        row["source"]: row["count"]
        for row in qs.values("source").annotate(count=Count("id"))
    }
    by_source = [
        {"label": label, "count": source_counts.get(value, 0)}
        for value, label in Source.choices
        if source_counts.get(value, 0)
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
        "by_month": by_month,
        "max_status": max((r["count"] for r in by_status), default=0),
        "max_source": max((r["count"] for r in by_source), default=0),
        "max_month": max((r["count"] for r in by_month), default=0),
    }
