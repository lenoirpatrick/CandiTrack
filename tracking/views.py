from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CandidatureForm
from .models import CV, Candidature, JobSite, Statut, StatusHistory


def candidature_list(request):
    candidatures = Candidature.objects.select_related("site").all()
    return render(
        request,
        "tracking/candidature_list.html",
        {"candidatures": candidatures},
    )


def candidature_detail(request, pk):
    candidature = get_object_or_404(
        Candidature.objects.select_related("site"), pk=pk
    )
    return render(
        request,
        "tracking/candidature_detail.html",
        {"candidature": candidature},
    )


def candidature_create(request):
    if request.method == "POST":
        form = CandidatureForm(request.POST)
        if form.is_valid():
            candidature = form.save()
            StatusHistory.objects.create(
                candidature=candidature, statut=candidature.statut
            )
            messages.success(request, "Candidature créée.")
            return redirect(candidature)
    else:
        form = CandidatureForm()
    return render(
        request,
        "tracking/candidature_form.html",
        {"form": form, "title": "Nouvelle candidature"},
    )


def candidature_update(request, pk):
    candidature = get_object_or_404(Candidature, pk=pk)
    previous_statut = candidature.statut
    if request.method == "POST":
        form = CandidatureForm(request.POST, instance=candidature)
        if form.is_valid():
            candidature = form.save()
            if candidature.statut != previous_statut:
                StatusHistory.objects.create(
                    candidature=candidature, statut=candidature.statut
                )
            messages.success(request, "Candidature mise à jour.")
            return redirect(candidature)
    else:
        form = CandidatureForm(instance=candidature)
    return render(
        request,
        "tracking/candidature_form.html",
        {"form": form, "title": "Modifier la candidature"},
    )


# --- Placeholder pages (enriched in later iterations) ---------------------


def site_list(request):
    """Issue #366 — full UI (add form, dynamic logo) comes later."""
    sites = JobSite.objects.all()
    return render(request, "tracking/site_list.html", {"sites": sites})


def stats(request):
    """Issue #367 — basic aggregate now, full KPIs later."""
    total = Candidature.objects.count()
    by_status = (
        Candidature.objects.values("statut")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    label_map = dict(Statut.choices)
    by_status = [
        {"label": label_map.get(row["statut"], row["statut"]), "count": row["count"]}
        for row in by_status
    ]
    return render(
        request,
        "tracking/stats.html",
        {"total": total, "by_status": by_status},
    )


def cv_list(request):
    """Issue #368 — upload/reformat UI comes later."""
    cvs = CV.objects.all()
    return render(request, "tracking/cv_list.html", {"cvs": cvs})
