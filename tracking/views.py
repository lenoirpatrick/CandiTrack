import io
import json
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Case, IntegerField, Q, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import coaching
from .ai import AIError
from .forms import CandidatureForm, CVForm, JobSiteForm
from .models import (
    CV,
    AIConfig,
    ApiToken,
    Candidature,
    JobSite,
    Source,
    Statut,
    StatusHistory,
)
from .statistics import compute_stats


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


# Nom de route vers la liste des sites, factorisé pour les redirections (issue #29).
SITE_LIST_ROUTE = "tracking:site_list"


# Champs triables depuis la liste (issue #11) : clé d'URL -> champ modèle.
CANDIDATURE_SORTS = {
    "candidature": "libelle",
    "entreprise": "entreprise",
    "poste": "poste",
    "statut": "statut",
    "date": "date_envoi",
}


def _source_logos():
    """Map a Source value to a JobSite logo URL (issue #8).

    The source enum mirrors the built-in job sites by display name, so we
    can surface the source site's logo in the list.
    """
    sites = {s.name.lower(): s.logo_url for s in JobSite.objects.all() if s.logo_url}
    return {
        value: sites[label.lower()]
        for value, label in Source.choices
        if label.lower() in sites
    }


@require_GET
def candidature_list(request):
    candidatures = Candidature.objects.select_related("site")

    # Recherche plein texte sur les principaux champs (issue #11).
    query = (request.GET.get("q") or "").strip()
    if query:
        candidatures = candidatures.filter(
            Q(libelle__icontains=query)
            | Q(entreprise__icontains=query)
            | Q(poste__icontains=query)
            | Q(notes__icontains=query)
        )

    # Tri par colonne (issue #11).
    sort = request.GET.get("sort")
    if sort not in CANDIDATURE_SORTS:
        sort = "date"
    direction = "asc" if request.GET.get("dir") == "asc" else "desc"
    field = CANDIDATURE_SORTS[sort]
    prefix = "" if direction == "asc" else "-"

    # Les candidatures clôturées sont toujours reléguées en bas (issue #10).
    candidatures = candidatures.annotate(
        _closed=Case(
            When(motif_cloture="", then=0), default=1, output_field=IntegerField()
        )
    ).order_by("_closed", f"{prefix}{field}", "-created_at")

    # Logo du site source pour chaque candidature (issue #8).
    logos = _source_logos()
    candidatures = list(candidatures)
    for c in candidatures:
        c.source_logo = logos.get(c.source, "")

    return render(
        request,
        "tracking/candidature_list.html",
        {
            "candidatures": candidatures,
            "q": query,
            "sort": sort,
            "dir": direction,
        },
    )


def _celebrer_acceptation(request):
    """Easter egg (issue #23) : message marqué pour déclencher les confettis.

    Le tag ``confetti`` est lu côté client (base.html) pour lancer l'animation.
    """
    messages.success(
        request,
        "🎉 Offre acceptée — félicitations !",
        extra_tags="confetti",
    )


@require_GET
def candidature_detail(request, pk):
    candidature = get_object_or_404(
        Candidature.objects.select_related("site"), pk=pk
    )
    return render(
        request,
        "tracking/candidature_detail.html",
        {"candidature": candidature},
    )


def _render_candidature_form(request, form, title, action, status=200):
    """Render the form: just the partial for AJAX (modal), full page otherwise."""
    template = (
        "tracking/_candidature_form.html"
        if _is_ajax(request)
        else "tracking/candidature_form.html"
    )
    return render(
        request,
        template,
        {"form": form, "title": title, "action": action},
        status=status,
    )


def candidature_create(request):
    action = request.path
    if request.method == "POST":
        form = CandidatureForm(request.POST)
        if form.is_valid():
            candidature = form.save()
            StatusHistory.objects.create(
                candidature=candidature, statut=candidature.statut
            )
            messages.success(request, "Candidature créée.")
            if candidature.acceptation:
                _celebrer_acceptation(request)
            if _is_ajax(request):
                return JsonResponse({"ok": True, "redirect": candidature.get_absolute_url()})
            return redirect(candidature)
        # Invalid: re-render the form (422 so the modal shows the errors).
        return _render_candidature_form(
            request, form, "Nouvelle candidature", action, status=422
        )
    return _render_candidature_form(
        request, CandidatureForm(), "Nouvelle candidature", action
    )


def candidature_update(request, pk):
    candidature = get_object_or_404(Candidature, pk=pk)
    action = request.path
    previous_statut = candidature.statut
    previous_acceptation = candidature.acceptation
    if request.method == "POST":
        form = CandidatureForm(request.POST, instance=candidature)
        if form.is_valid():
            candidature = form.save()
            if candidature.statut != previous_statut:
                StatusHistory.objects.create(
                    candidature=candidature, statut=candidature.statut
                )
            messages.success(request, "Candidature mise à jour.")
            if candidature.acceptation and not previous_acceptation:
                _celebrer_acceptation(request)
            if _is_ajax(request):
                return JsonResponse({"ok": True, "redirect": candidature.get_absolute_url()})
            return redirect(candidature)
        return _render_candidature_form(
            request, form, "Modifier la candidature", action, status=422
        )
    return _render_candidature_form(
        request, CandidatureForm(instance=candidature), "Modifier la candidature", action
    )


def candidature_delete(request, pk):
    """Issue #21 — supprimer définitivement une candidature."""
    candidature = get_object_or_404(Candidature, pk=pk)
    if request.method == "POST":
        candidature.delete()
        messages.success(request, "Candidature supprimée.")
        return redirect("tracking:candidature_list")
    return render(
        request,
        "tracking/candidature_confirm_delete.html",
        {"candidature": candidature},
    )


# --- Placeholder pages (enriched in later iterations) ---------------------


@require_GET
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
            return redirect(SITE_LIST_ROUTE)
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
            return redirect(SITE_LIST_ROUTE)
    else:
        form = JobSiteForm(instance=site)
    return render(
        request,
        "tracking/site_form.html",
        {"form": form, "title": f"Modifier {site.name}", "site": site},
    )


def site_delete(request, pk):
    site = get_object_or_404(JobSite, pk=pk)
    # Les sites par défaut ne se suppriment pas : on les désactive (issue #22).
    if site.is_builtin:
        messages.error(
            request,
            f"« {site.name} » est un site par défaut : désactivez-le plutôt que de le supprimer.",
        )
        return redirect(SITE_LIST_ROUTE)
    if request.method == "POST":
        site.delete()
        messages.success(request, "Site supprimé.")
        return redirect(SITE_LIST_ROUTE)
    return render(request, "tracking/site_confirm_delete.html", {"site": site})


def site_toggle_active(request, pk):
    """Issue #22 — activer/désactiver un site (surtout les sites par défaut)."""
    site = get_object_or_404(JobSite, pk=pk)
    if request.method == "POST":
        site.actif = not site.actif
        site.save(update_fields=["actif", "updated_at"])
        etat = "activé" if site.actif else "désactivé"
        messages.success(request, f"Site « {site.name} » {etat}.")
    return redirect(SITE_LIST_ROUTE)


@require_GET
def stats(request):
    """Issue #367 — statistics dashboard with KPIs."""
    return render(request, "tracking/stats.html", compute_stats())


@require_GET
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


# --- Help / extension config (issue #6) -----------------------------------


def help_page(request):
    """Help page: install the extension, manage API keys and AI config (issue #6, #33)."""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "generate":
            ApiToken.objects.create(
                token=ApiToken.new_token(),
                label=(request.POST.get("label") or "").strip(),
            )
            messages.success(request, "Nouveau jeton API généré.")
        elif action == "revoke":
            ApiToken.objects.filter(pk=request.POST.get("token_id")).delete()
            messages.success(request, "Jeton révoqué.")
        elif action == "ai_save":
            _save_ai_config(request)
        elif action == "ai_clear":
            config = AIConfig.load()
            config.api_key = ""
            config.save(update_fields=["api_key", "updated_at"])
            messages.success(request, "Clé Gemini supprimée.")
        return redirect("tracking:help")

    return render(
        request,
        "tracking/help.html",
        {
            "tokens": ApiToken.objects.all(),
            "settings_token": settings.CANDITRACK_API_TOKEN,
            "ai_config": AIConfig.load(),
        },
    )


def _save_ai_config(request):
    """Enregistre la config IA (issue #33). Une clé vide ne l'écrase pas."""
    config = AIConfig.load()
    config.model = (request.POST.get("model") or "").strip() or AIConfig.DEFAULT_MODEL
    new_key = (request.POST.get("api_key") or "").strip()
    if new_key:
        config.api_key = new_key
    config.save()
    messages.success(request, "Configuration IA enregistrée.")


# --- Coaching IA (issue #33) ----------------------------------------------


def _ai_endpoint(request, build_response):
    """Fabrique commune aux endpoints IA : vérifie la config puis appelle l'IA.

    ``build_response`` renvoie le texte généré. On encapsule la gestion de la
    configuration manquante et des erreurs d'appel en réponses JSON.
    """
    if not AIConfig.load().is_configured:
        return JsonResponse(
            {"error": "Aucune clé Gemini configurée. Renseignez-la sur la page d'aide."},
            status=400,
        )
    try:
        return JsonResponse({"ok": True, "text": build_response()})
    except AIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)


@require_POST
def ai_coaching(request):
    """Renvoie un bilan de coaching IA à partir du CV et des statistiques."""
    return _ai_endpoint(request, coaching.coaching_advice)


@require_POST
def ai_relance(request, pk):
    """Renvoie un brouillon de mail de relance IA pour une candidature."""
    candidature = get_object_or_404(Candidature, pk=pk)
    return _ai_endpoint(request, lambda: coaching.relance_email(candidature))


@require_GET
def extension_download(request):
    """Serve the chrome-extension/ folder as a zip the user can install (issue #6)."""
    ext_dir = Path(settings.BASE_DIR) / "chrome-extension"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ext_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(ext_dir.parent))
    resp = HttpResponse(buffer.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="canditrack-extension.zip"'
    return resp


# --- API for the Chrome extension (issue #2) ------------------------------


# @csrf_exempt est sûr ici (hotspot SonarCloud csrf/S4502, issue #29) :
# l'endpoint est authentifié par un jeton dans l'en-tête custom X-Api-Token,
# jamais par un cookie de session. Le CSRF n'exploite que l'envoi automatique
# des cookies par le navigateur ; un en-tête custom ne peut pas être posé en
# cross-origin sans préflight CORS (non autorisé). Aucune donnée d'auth n'est
# donc rejouable par un site tiers.
@csrf_exempt
@require_POST
def api_candidature_create(request):
    """Create a candidature from the Chrome extension.

    Authenticated with a shared token sent in the ``X-Api-Token`` header
    (CSRF-exempt because it is token- rather than cookie-authenticated).
    """
    provided = request.headers.get("X-Api-Token", "")
    expected = settings.CANDITRACK_API_TOKEN
    settings_ok = bool(expected) and provided == expected
    stored_ok = bool(provided) and ApiToken.objects.filter(token=provided).exists()
    if not (settings_ok or stored_ok):
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid json"}, status=400)

    url = (data.get("url") or "").strip()
    entreprise = (data.get("entreprise") or "").strip()
    source = (data.get("source") or "").strip()
    if source not in Source.values:
        source = Source.AUTRE
    if not (entreprise or url):
        return JsonResponse({"error": "empty payload"}, status=400)

    # Le plugin enregistre une annonce : il ne renseigne ni l'intitulé du poste
    # ni la date d'envoi (laissés vides, à compléter ensuite dans CandiTrack).
    libelle = entreprise or "Candidature"
    candidature = Candidature.objects.create(
        libelle=libelle,
        entreprise=entreprise,
        poste="",
        url_offre=url,
        source=source,
        statut=Statut.ENVOYEE,
        date_envoi=None,
    )
    StatusHistory.objects.create(candidature=candidature, statut=candidature.statut)
    return JsonResponse(
        {
            "ok": True,
            "id": candidature.pk,
            "url": request.build_absolute_uri(candidature.get_absolute_url()),
        },
        status=201,
    )
