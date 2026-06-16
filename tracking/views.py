import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.db.models import Case, IntegerField, Q, When
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import coaching
from . import cv_export as cv_exporters
from .ai import AIError
from .forms import CandidatureForm, CVForm, JobSiteForm, ReferenceForm
from .models import (
    CV,
    AIConfig,
    AIUsage,
    ApiToken,
    Candidature,
    JobSite,
    Reference,
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
    "entreprise": "entreprise",
    "poste": "poste",
    "statut": "statut",
    "date": "date_envoi",
}


@require_GET
def candidature_list(request):
    candidatures = Candidature.objects.select_related("source")

    # Recherche plein texte sur les principaux champs (issue #11).
    query = (request.GET.get("q") or "").strip()
    if query:
        candidatures = candidatures.filter(
            Q(entreprise__icontains=query)
            | Q(poste__icontains=query)
            | Q(notes__icontains=query)
        )

    # Candidatures « archivées » = abouties à 100 % : clôturées (motif) ou
    # acceptées (issue #52). On les sépare de la liste active via un bouton.
    archived_q = ~Q(motif_cloture="") | Q(acceptation=True)
    show_archived = request.GET.get("archivees") == "1"
    archived_count = candidatures.filter(archived_q).count()
    if show_archived:
        candidatures = candidatures.filter(archived_q)
    else:
        candidatures = candidatures.exclude(archived_q)

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

    return render(
        request,
        "tracking/candidature_list.html",
        {
            "candidatures": candidatures,
            "q": query,
            "sort": sort,
            "dir": direction,
            "show_archived": show_archived,
            "archived_count": archived_count,
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
        Candidature.objects.select_related("source", "cv"), pk=pk
    )
    # Origine du calcul de trajet : adresse du CV par défaut (issue #52).
    default_cv = CV.default()
    return render(
        request,
        "tracking/candidature_detail.html",
        {
            "candidature": candidature,
            "home_location": default_cv.home_location if default_cv else "",
            "default_cv": default_cv,
        },
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
    """Issue #368 — liste des CV chargés (analyse IA optionnelle, issue #44)."""
    cvs = CV.objects.all()
    return render(
        request,
        "tracking/cv_list.html",
        {
            "cvs": [cv for cv in cvs if cv.actif],
            "cvs_archives": [cv for cv in cvs if not cv.actif],
            "export_formats": cv_exporters.EXPORT_LABELS,
        },
    )


@require_POST
def cv_toggle_active(request, pk):
    """Archive ou réactive un CV (issue #48)."""
    cv = get_object_or_404(CV, pk=pk)
    cv.actif = not cv.actif
    cv.save(update_fields=["actif"])
    etat = "réactivé" if cv.actif else "archivé"
    messages.success(request, f"CV « {cv.label} » {etat}.")
    # On ne redirige vers « next » que s'il pointe vers ce site (anti open-redirect).
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("tracking:cv_list")


@require_POST
def cv_set_default(request, pk):
    """Désigne (ou retire) le CV par défaut, origine des trajets (issue #52)."""
    cv = get_object_or_404(CV, pk=pk)
    if cv.par_defaut:
        cv.par_defaut = False
        cv.save(update_fields=["par_defaut"])
        messages.success(request, f"CV « {cv.label} » n'est plus le CV par défaut.")
    else:
        cv.set_as_default()
        messages.success(request, f"CV « {cv.label} » défini comme CV par défaut.")
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("tracking:cv_list")


def _cv_localisations(cv):
    """Points du parcours (lieu + société + type) pour la carte des lieux (issue #44)."""
    if not cv.is_analyzed:
        return []
    analysis = cv.analysis
    points = []
    for exp in analysis.get("experiences", []):
        if exp.get("lieu"):
            points.append(
                {"type": "exp", "lieu": exp["lieu"], "societe": exp.get("entreprise", "")}
            )
    for form in analysis.get("formations", []):
        if form.get("lieu"):
            points.append(
                {
                    "type": "form",
                    "lieu": form["lieu"],
                    "societe": form.get("etablissement", ""),
                }
            )
    return points


@require_GET
def cv_detail(request, pk):
    """Détail d'un CV et de son analyse IA (issue #44)."""
    cv = get_object_or_404(CV, pk=pk)
    return render(
        request,
        "tracking/cv_detail.html",
        {
            "cv": cv,
            "ai_config": AIConfig.load(),
            "localisations": _cv_localisations(cv),
            "export_formats": cv_exporters.EXPORT_LABELS,
        },
    )


@require_GET
def cv_export(request, pk, fmt):
    """Exporte l'analyse d'un CV vers un format standard (issue #44)."""
    cv = get_object_or_404(CV, pk=pk)
    exporter = cv_exporters.EXPORTERS.get(fmt)
    if not cv.is_analyzed or exporter is None:
        raise Http404("Export indisponible pour ce CV.")
    payload = json.dumps(exporter(cv), ensure_ascii=False, indent=2)
    filename = f"{slugify(cv.label) or 'cv'}-{fmt}.json"
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_GET
def cv_print(request, pk):
    """Vue d'impression d'un CV (PDF via l'impression navigateur, issue #44)."""
    cv = get_object_or_404(CV, pk=pk)
    if not cv.is_analyzed:
        raise Http404("Ce CV n'a pas encore été analysé.")
    return render(request, "tracking/cv_print.html", {"cv": cv})


def _analyze_cv_safely(request, cv):
    """Analyse un CV en convertissant les erreurs en messages (issue #44)."""
    try:
        coaching.analyze_cv(cv)
    except AIError as exc:
        messages.warning(request, f"CV chargé, mais l'analyse IA a échoué : {exc}")
        return
    if cv.analysis_error:
        messages.warning(
            request, f"CV chargé, mais l'analyse n'a pu aboutir : {cv.analysis_error}"
        )
    else:
        messages.success(request, "CV chargé et analysé par l'IA.")


def cv_create(request):
    config = AIConfig.load()
    if request.method == "POST":
        form = CVForm(request.POST, request.FILES)
        if form.is_valid():
            cv = form.save()
            # Analyse IA optionnelle, si une IA est configurée et acceptée (issue #44).
            if config.is_configured and request.POST.get("analyser"):
                _analyze_cv_safely(request, cv)
            else:
                messages.success(request, "CV chargé.")
            return redirect("tracking:cv_list")
    else:
        form = CVForm()
    return render(
        request,
        "tracking/cv_form.html",
        {"form": form, "title": "Charger un CV", "ai_config": config},
    )


@require_POST
def cv_analyze(request, pk):
    """(Ré)analyse un CV à la demande (issue #44)."""
    cv = get_object_or_404(CV, pk=pk)
    config = AIConfig.load()
    if not config.is_configured:
        messages.error(
            request, "Aucune clé IA configurée. Renseignez-la dans Options → IA."
        )
    else:
        _analyze_cv_safely(request, cv)
    return redirect("tracking:cv_detail", pk=pk)


def cv_edit(request, pk):
    """Édition manuelle des sections de l'analyse d'un CV (issue #61).

    Permet de corriger/compléter les informations extraites par l'IA — ou d'en
    saisir de toutes pièces si le CV n'a pas été analysé. Les données arrivent
    sérialisées en JSON (construit côté client) puis sont normalisées comme une
    analyse IA pour garantir une structure stable.
    """
    cv = get_object_or_404(CV, pk=pk)
    if request.method == "POST":
        raw = request.POST.get("analysis", "")
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            data = None
        if not isinstance(data, dict):
            messages.error(request, "Données d'analyse invalides.")
        else:
            cv.analysis = coaching.normalize_cv_analysis(data)
            cv.analysis_error = ""
            # Un CV jamais analysé devient « analysé » dès la première saisie.
            if not cv.analyzed_at:
                cv.analyzed_at = timezone.now()
            cv.save(update_fields=["analysis", "analysis_error", "analyzed_at"])
            messages.success(request, "Analyse du CV mise à jour.")
            return redirect("tracking:cv_detail", pk=cv.pk)
    return render(
        request,
        "tracking/cv_edit.html",
        {
            "cv": cv,
            "analysis_json": json.dumps(cv.analysis or {}, ensure_ascii=False),
        },
    )


def reference_create(request, cv_pk):
    """Ajoute une référence rattachée à un CV (issue #62)."""
    cv = get_object_or_404(CV, pk=cv_pk)
    if request.method == "POST":
        form = ReferenceForm(request.POST, cv=cv)
        if form.is_valid():
            reference = form.save(commit=False)
            reference.cv = cv
            reference.save()
            messages.success(request, "Référence ajoutée.")
            return redirect("tracking:cv_detail", pk=cv.pk)
    else:
        form = ReferenceForm(cv=cv)
    return render(
        request,
        "tracking/reference_form.html",
        {"form": form, "cv": cv, "title": "Ajouter une référence"},
    )


def reference_update(request, pk):
    """Modifie une référence existante (issue #62)."""
    reference = get_object_or_404(Reference, pk=pk)
    cv = reference.cv
    if request.method == "POST":
        form = ReferenceForm(request.POST, instance=reference, cv=cv)
        if form.is_valid():
            form.save()
            messages.success(request, "Référence mise à jour.")
            return redirect("tracking:cv_detail", pk=cv.pk)
    else:
        form = ReferenceForm(instance=reference, cv=cv)
    return render(
        request,
        "tracking/reference_form.html",
        {"form": form, "cv": cv, "title": "Modifier la référence"},
    )


@require_POST
def reference_delete(request, pk):
    """Supprime une référence (issue #62)."""
    reference = get_object_or_404(Reference, pk=pk)
    cv_pk = reference.cv_id
    reference.delete()
    messages.success(request, "Référence supprimée.")
    return redirect("tracking:cv_detail", pk=cv_pk)


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
            _clear_ai_key(request, AIConfig.load())
        return redirect("tracking:help")

    config = AIConfig.load()
    return render(
        request,
        "tracking/help.html",
        {
            "tokens": ApiToken.objects.all(),
            "settings_token": settings.CANDITRACK_API_TOKEN,
            "ai_config": config,
            "ai_providers": _ai_providers_context(config),
        },
    )


def _provider_usage(provider, limit):
    """Consommation du mois courant d'un fournisseur, vs sa limite (issue #36)."""
    summary = AIUsage.month_summary(provider)
    tokens = summary["tokens"]
    percent = round(100 * tokens / limit) if limit else 0
    return {
        "calls": summary["calls"],
        "tokens": tokens,
        "limit": limit,
        "percent": min(percent, 100),
        "reached": bool(limit) and tokens >= limit,
    }


def _ai_providers_context(config):
    """Données par fournisseur pour la page Options → IA (issues #34, #36, #39)."""
    providers = []
    for value, label in AIConfig.Provider.choices:
        model = getattr(config, f"{value}_model")
        models = AIConfig.MODELS_BY_PROVIDER[value]
        limit = getattr(config, f"{value}_monthly_limit")
        providers.append({
            "value": value,
            "label": label,
            "active": config.provider == value,
            "key_set": bool(getattr(config, f"{value}_api_key")),
            "key_field": f"{value}_api_key",
            "model_field": f"{value}_model",
            "limit_field": f"{value}_monthly_limit",
            "model": model,
            "models": models,
            "model_in_choices": model in dict(models),
            "monthly_limit": limit,
            "usage": _provider_usage(value, limit),
            "info": AIConfig.PROVIDER_INFO.get(value, {}),
        })
    return providers


def _save_ai_config(request):
    """Enregistre la config IA (issues #33, #34, #36, #39).

    Le fournisseur actif, les modèles et les limites sont mis à jour pour tous
    les fournisseurs ; chaque clé n'est remplacée que si une valeur non vide est
    fournie (on conserve sinon la clé déjà saisie pour chaque fournisseur).
    """
    config = AIConfig.load()
    provider = (request.POST.get("provider") or "").strip()
    if provider in AIConfig.Provider.values:
        config.provider = provider
    for value, _ in AIConfig.Provider.choices:
        model = (request.POST.get(f"{value}_model") or "").strip()
        setattr(config, f"{value}_model", model or AIConfig.DEFAULTS[value])
        setattr(
            config, f"{value}_monthly_limit",
            _positive_int(request.POST.get(f"{value}_monthly_limit")),
        )
        key = (request.POST.get(f"{value}_api_key") or "").strip()
        if key:
            setattr(config, f"{value}_api_key", key)
    config.save()
    messages.success(request, "Configuration IA enregistrée.")


def _positive_int(value):
    """Entier positif depuis un champ de formulaire, 0 par défaut (issue #36)."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _clear_ai_key(request, config):
    """Supprime la clé du fournisseur actif (issues #34, #39)."""
    field = f"{config.provider}_api_key"
    setattr(config, field, "")
    config.save(update_fields=[field, "updated_at"])
    messages.success(request, f"Clé {config.get_provider_display()} supprimée.")


# --- Coaching IA (issue #33) ----------------------------------------------


def _ai_endpoint(request, build_response):
    """Fabrique commune aux endpoints IA : vérifie la config puis appelle l'IA.

    ``build_response`` renvoie le texte généré. On encapsule la gestion de la
    configuration manquante et des erreurs d'appel en réponses JSON.
    """
    config = AIConfig.load()
    if not config.is_configured:
        return JsonResponse(
            {"error": "Aucune clé IA configurée. Renseignez-la dans Options → IA."},
            status=400,
        )
    try:
        text = build_response()
    except AIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    # Indiquer l'IA et le modèle ayant produit le texte (issue #37).
    payload = {
        "ok": True,
        "text": text,
        "provider": config.get_provider_display(),
        "model": config.model,
    }
    warning = _quota_warning(config)
    if warning:
        payload["warning"] = warning
    return JsonResponse(payload)


def _quota_warning(config):
    """Message d'alerte si la limite mensuelle du fournisseur actif est atteinte.

    Limite souple (issue #36) : on avertit sans bloquer l'appel.
    """
    limit = config.monthly_limit
    if not limit:
        return None
    tokens = AIUsage.month_summary(config.provider)["tokens"]
    if tokens >= limit:
        return (
            f"Limite mensuelle atteinte pour {config.get_provider_display()} : "
            f"{tokens} / {limit} tokens utilisés ce mois-ci."
        )
    return None


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


# Codes de source envoyés par l'extension -> nom du JobSite équivalent (issue #52).
EXTENSION_SOURCE_NAMES = {
    "france_travail": "France Travail",
    "apec": "APEC",
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "monster": "Monster",
    "cadremploi": "Cadremploi",
}


def _resolve_source_site(code, url):
    """Associe la candidature à un JobSite actif (issue #52).

    On tente d'abord par le code de source de l'extension (LinkedIn, Indeed…),
    puis par le domaine de l'URL de l'offre ; faute de correspondance, ``None``.
    """
    code = (code or "").strip().lower()
    name = EXTENSION_SOURCE_NAMES.get(code)
    if name:
        site = JobSite.objects.filter(actif=True, name__iexact=name).first()
        if site:
            return site
    # Correspondance par domaine avec un site connu (couvre les sites custom).
    domain = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
    if domain:
        for site in JobSite.objects.filter(actif=True).exclude(url=""):
            site_domain = urlparse(site.url).netloc.lower().removeprefix("www.")
            if site_domain and site_domain == domain:
                return site
    return None


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
    localisation = (data.get("localisation") or "").strip()
    source = _resolve_source_site(data.get("source"), url)
    if not (entreprise or url):
        return JsonResponse({"error": "empty payload"}, status=400)

    # Le plugin enregistre une annonce : il ne renseigne ni l'intitulé du poste
    # ni la date d'envoi (laissés vides, à compléter ensuite dans CandiTrack).
    candidature = Candidature.objects.create(
        entreprise=entreprise,
        poste="",
        url_offre=url,
        localisation=localisation,
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
