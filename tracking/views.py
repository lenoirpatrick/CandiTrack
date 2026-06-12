from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CandidatureForm, CVForm, JobSiteForm
from .logos import fetch_logo_url
from .models import CV, Candidature, JobSite, StatusHistory
from .statistics import compute_stats


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
    """Issue #366 — list of job sites with manual management."""
    sites = JobSite.objects.all()
    return render(request, "tracking/site_list.html", {"sites": sites})


def site_create(request):
    if request.method == "POST":
        form = JobSiteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Site ajouté.")
            return redirect("tracking:site_list")
    else:
        form = JobSiteForm()
    return render(
        request,
        "tracking/site_form.html",
        {"form": form, "title": "Ajouter un site"},
    )


def site_update(request, pk):
    site = get_object_or_404(JobSite, pk=pk)
    if request.method == "POST":
        form = JobSiteForm(request.POST, instance=site)
        if form.is_valid():
            form.save()
            messages.success(request, "Site mis à jour.")
            return redirect("tracking:site_list")
    else:
        form = JobSiteForm(instance=site)
    return render(
        request,
        "tracking/site_form.html",
        {"form": form, "title": f"Modifier {site.name}", "site": site},
    )


def site_delete(request, pk):
    site = get_object_or_404(JobSite, pk=pk)
    if request.method == "POST":
        site.delete()
        messages.success(request, "Site supprimé.")
        return redirect("tracking:site_list")
    return render(request, "tracking/site_confirm_delete.html", {"site": site})


def site_refresh_logo(request, pk):
    """Re-fetch the logo from the site URL (issue #366)."""
    site = get_object_or_404(JobSite, pk=pk)
    if request.method == "POST":
        if site.url:
            site.logo_url = fetch_logo_url(site.url)
            site.save(update_fields=["logo_url", "updated_at"])
            messages.success(request, f"Logo de {site.name} mis à jour.")
        else:
            messages.error(request, f"{site.name} n'a pas d'URL.")
    return redirect("tracking:site_list")


def stats(request):
    """Issue #367 — statistics dashboard with KPIs."""
    return render(request, "tracking/stats.html", compute_stats())


def cv_list(request):
    """Issue #368 — list uploaded CVs (reformat/LinkedIn import come later)."""
    cvs = CV.objects.all()
    return render(request, "tracking/cv_list.html", {"cvs": cvs})


def cv_create(request):
    if request.method == "POST":
        form = CVForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "CV chargé.")
            return redirect("tracking:cv_list")
    else:
        form = CVForm()
    return render(
        request,
        "tracking/cv_form.html",
        {"form": form, "title": "Charger un CV"},
    )


def cv_delete(request, pk):
    cv = get_object_or_404(CV, pk=pk)
    if request.method == "POST":
        # Remove the file from storage, then the record.
        cv.file.delete(save=False)
        cv.delete()
        messages.success(request, "CV supprimé.")
        return redirect("tracking:cv_list")
    return render(request, "tracking/cv_confirm_delete.html", {"cv": cv})
