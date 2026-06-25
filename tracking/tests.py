import json
import tempfile
import urllib.error
from unittest import mock

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from datetime import timedelta

from . import ai, coaching, cv_export, mailing, views
from .forms import CandidatureForm, CVForm, JobSiteForm
from .models import (
    CV,
    AIConfig,
    AIUsage,
    ApiToken,
    Canal,
    Candidature,
    JobSite,
    MotifCloture,
    Reference,
    ReminderConfig,
    Statut,
    StatusHistory,
)
from .statistics import compute_stats

# Clé Fernet de test pour chiffrer la clé API IA en base (issue #33).
TEST_FERNET_KEY = Fernet.generate_key().decode()


class EtapeCouranteTests(TestCase):
    """Issue #12 — the list status reflects the furthest reached step."""

    def test_nouvelle(self):
        c = Candidature(poste="X")
        self.assertEqual(c.etape_courante(), "Nouvelle")

    def test_short_labels(self):
        c = Candidature(poste="X", envoyee=True, traitee=True)
        self.assertEqual(c.etape_courante(), "Traitée")
        c.entretien_programme = True
        self.assertEqual(c.etape_courante(), "Entretien")
        c.offre_soumise = True
        self.assertEqual(c.etape_courante(), "Offre")

    def test_cloturee(self):
        c = Candidature(poste="X", motif_cloture=MotifCloture.REFUS_CANDIDAT)
        self.assertEqual(c.etape_courante(), "Terminée")


class ProgressionColorTests(TestCase):
    """Issue #10 — bar colour advances, and is red when stopped."""

    def test_gradient_when_open(self):
        c = Candidature(poste="X", envoyee=True, traitee=True)
        self.assertTrue(c.progression()["color"].startswith("hsl("))

    def test_red_when_closed(self):
        c = Candidature(poste="X", motif_cloture=MotifCloture.POSTE_POURVU)
        p = c.progression()
        self.assertEqual(p["color"], "#e0584b")
        self.assertEqual(p["percent"], 100)
        self.assertTrue(p["closed"])


class CandidatureListTests(TestCase):
    """Issues #10, #11 — search, sorting, closed rows sink to the bottom."""

    def setUp(self):
        self.alpha = Candidature.objects.create(
            entreprise="Alpha", poste="Backend",
            envoyee=True, traitee=True,
        )
        self.beta = Candidature.objects.create(
            entreprise="Beta", poste="Frontend",
        )
        self.zeta = Candidature.objects.create(
            entreprise="Zeta", poste="DevOps",
            motif_cloture=MotifCloture.REFUS_CANDIDAT,
        )

    def test_search_filters(self):
        resp = self.client.get(reverse("tracking:candidature_list"), {"q": "beta"})
        self.assertContains(resp, "Beta")
        self.assertNotContains(resp, ">Alpha<")

    def test_closed_excluded_from_active_list(self):
        # Les candidatures clôturées (100 %) ne figurent plus dans la liste
        # active : elles basculent dans la vue archivée (issue #52).
        resp = self.client.get(
            reverse("tracking:candidature_list"), {"sort": "poste", "dir": "asc"}
        )
        order = list(resp.context["candidatures"])
        self.assertNotIn(self.zeta, order)
        self.assertEqual(order, [self.alpha, self.beta])

    def test_closed_row_marked(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "closed-row")

    def test_invalid_sort_falls_back(self):
        resp = self.client.get(
            reverse("tracking:candidature_list"), {"sort": "bogus"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["sort"], "date")


class ToastTests(TestCase):
    """Issue #13 — actions surface as toasts, not the old message list."""

    def test_no_legacy_message_list(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "toast-container")
        self.assertNotContains(resp, 'class="messages"')

    def test_action_emits_toast_payload(self):
        resp = self.client.post(
            reverse("tracking:candidature_create"),
            {
                "poste": "Dev",
                "statut": Statut.ENVOYEE, "canal_envoi": "email",
            },
            follow=True,
        )
        # Message survives the redirect and is rendered into the toast payload.
        self.assertContains(resp, "toast-data")
        self.assertContains(resp, "Candidature créée")


class AdminDisabledTests(TestCase):
    """L'admin Django est désactivé : aucun lien ni route /admin/."""

    def test_no_admin_link(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertNotContains(resp, 'href="/admin/"')

    def test_admin_route_returns_404(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)


class ListSourceColumnTests(TestCase):
    """Issue #8 — entreprise + source site (with logo) shown in the list."""

    def test_entreprise_and_source_logo(self):
        site, _ = JobSite.objects.get_or_create(name="LinkedIn")
        site.logo_url = "https://x/li.png"
        site.save()
        Candidature.objects.create(
            entreprise="ACME", poste="Dev", source=site
        )
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "Entreprise")
        self.assertContains(resp, "Site source")
        self.assertContains(resp, "ACME")
        self.assertContains(resp, "https://x/li.png")

    def test_entreprise_is_sortable(self):
        resp = self.client.get(
            reverse("tracking:candidature_list"), {"sort": "entreprise"}
        )
        self.assertEqual(resp.context["sort"], "entreprise")


class HelpPageTests(TestCase):
    """Issue #6 — help page, API key generation, extension download."""

    def test_page_loads(self):
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "Clé API")
        self.assertContains(resp, "Plugin Chrome")

    def test_options_categories(self):
        """Issue #34 — la page Options est découpée en catégories."""
        resp = self.client.get(reverse("tracking:help"))
        for label in ("Interface", "Extensions", "IA"):
            self.assertContains(resp, label)
        self.assertContains(resp, 'class="options-tab')
        self.assertContains(resp, 'id="panel-interface"')
        self.assertContains(resp, 'id="panel-extensions"')
        self.assertContains(resp, 'id="panel-ia"')

    def test_generate_and_revoke_token(self):
        self.client.post(reverse("tracking:help"), {"action": "generate", "label": "PC"})
        self.assertEqual(ApiToken.objects.count(), 1)
        tok = ApiToken.objects.get()
        self.assertTrue(tok.token)
        self.client.post(reverse("tracking:help"), {"action": "revoke", "token_id": tok.pk})
        self.assertEqual(ApiToken.objects.count(), 0)

    def test_extension_download_is_zip(self):
        resp = self.client.get(reverse("tracking:extension_download"))
        self.assertEqual(resp["Content-Type"], "application/zip")
        self.assertGreater(len(resp.content), 0)


@override_settings(CANDITRACK_API_TOKEN="")
class ApiTokenAuthTests(TestCase):
    """Issue #6 — the API endpoint accepts a stored ApiToken."""

    def test_stored_token_authorizes(self):
        tok = ApiToken.objects.create(token=ApiToken.new_token(), label="PC")
        resp = self.client.post(
            reverse("tracking:api_candidature_create"),
            data=json.dumps({"entreprise": "ACME", "url": "https://x/job"}),
            content_type="application/json",
            HTTP_X_API_TOKEN=tok.token,
        )
        self.assertEqual(resp.status_code, 201)

    def test_unknown_token_rejected(self):
        resp = self.client.post(
            reverse("tracking:api_candidature_create"),
            data=json.dumps({"entreprise": "ACME"}),
            content_type="application/json",
            HTTP_X_API_TOKEN="nope",
        )
        self.assertEqual(resp.status_code, 401)


class MenuIconTests(TestCase):
    """Issue #14 — Canal and Motif menu labels carry an icon."""

    def test_canal_labels_have_icon(self):
        # Each label starts with a non-ASCII glyph (emoji).
        for value, label in Canal.choices:
            self.assertFalse(label.isascii(), f"{value} sans icône")

    def test_motif_labels_have_icon(self):
        for value, label in MotifCloture.choices:
            self.assertFalse(label.isascii(), f"{value} sans icône")


class SourceDonutTests(TestCase):
    """Issue #15 — source breakdown drives a circular (donut) chart."""

    def test_segments_geometry(self):
        li, _ = JobSite.objects.get_or_create(name="LinkedIn")
        ind, _ = JobSite.objects.get_or_create(name="Indeed")
        Candidature.objects.create(poste="a", source=li)
        Candidature.objects.create(poste="b", source=li)
        Candidature.objects.create(poste="c", source=ind)
        ctx = compute_stats()
        rows = ctx["by_source"]
        self.assertEqual(ctx["source_total"], 3)
        self.assertAlmostEqual(sum(r["percent"] for r in rows), 100, delta=0.5)
        for r in rows:
            self.assertTrue(r["color"].startswith("#"))
            self.assertAlmostEqual(r["dash"] + r["gap"], 100, delta=0.01)

    def test_stats_page_renders_svg(self):
        li, _ = JobSite.objects.get_or_create(name="LinkedIn")
        Candidature.objects.create(poste="a", source=li)
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "<svg")
        self.assertContains(resp, "donut")
        self.assertContains(resp, "stroke-dasharray")


class SiteTypeTests(TestCase):
    """Issue #55 — type des sites (Généraliste / ESN / Direct)."""

    def test_default_type_generaliste(self):
        site = JobSite.objects.create(name="Exemple", url="https://exemple.fr/")
        self.assertEqual(site.type, JobSite.Type.GENERALISTE)

    def test_form_defaults_to_generaliste_when_omitted(self):
        form = JobSiteForm(data={"name": "Exemple", "url": "https://exemple.fr/"})
        self.assertTrue(form.is_valid(), form.errors)
        site = form.save()
        self.assertEqual(site.type, JobSite.Type.GENERALISTE)

    def test_form_accepts_chosen_type(self):
        form = JobSiteForm(
            data={"name": "Acme", "url": "https://acme.fr/", "type": "esn"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().type, JobSite.Type.ESN)

    def test_type_shown_in_site_list(self):
        JobSite.objects.create(name="Acme", type=JobSite.Type.ESN)
        resp = self.client.get(reverse("tracking:site_list"))
        self.assertContains(resp, "ESN")

    def test_stats_breakdown_by_type(self):
        esn = JobSite.objects.create(name="Acme", type=JobSite.Type.ESN)
        direct = JobSite.objects.create(name="Globex", type=JobSite.Type.DIRECT)
        Candidature.objects.create(poste="a", source=esn)
        Candidature.objects.create(poste="b", source=esn)
        Candidature.objects.create(poste="c", source=direct)
        ctx = compute_stats()
        labels = {r["label"]: r["count"] for r in ctx["by_type"]}
        self.assertEqual(labels.get("ESN"), 2)
        self.assertEqual(labels.get("Direct"), 1)
        self.assertEqual(ctx["type_total"], 3)


class CanalBreakdownTests(TestCase):
    """Issue #56 — graphique de répartition par canal d'envoi."""

    def test_breakdown_by_canal(self):
        Candidature.objects.create(poste="a", canal_envoi=Canal.EMAIL)
        Candidature.objects.create(poste="b", canal_envoi=Canal.EMAIL)
        Candidature.objects.create(poste="c", canal_envoi=Canal.COOPTATION)
        ctx = compute_stats()
        counts = {r["label"]: r["count"] for r in ctx["by_canal"]}
        self.assertEqual(counts.get(Canal.EMAIL.label), 2)
        self.assertEqual(counts.get(Canal.COOPTATION.label), 1)

    def test_stats_page_shows_canal_chart(self):
        Candidature.objects.create(poste="a", canal_envoi=Canal.EMAIL)
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "Répartition par canal d'envoi")


class MotifClotureBreakdownTests(TestCase):
    """Graphique de répartition par motif de clôture."""

    def test_breakdown_excludes_open_candidatures(self):
        Candidature.objects.create(poste="open")  # sans motif -> exclue
        Candidature.objects.create(
            poste="a", motif_cloture=MotifCloture.POSTE_POURVU
        )
        Candidature.objects.create(
            poste="b", motif_cloture=MotifCloture.POSTE_POURVU
        )
        Candidature.objects.create(
            poste="c", motif_cloture=MotifCloture.REFUS_SALAIRE
        )
        ctx = compute_stats()
        counts = {r["label"]: r["count"] for r in ctx["by_motif"]}
        self.assertEqual(ctx["motif_total"], 3)
        self.assertEqual(counts.get(MotifCloture.POSTE_POURVU.label), 2)
        self.assertEqual(counts.get(MotifCloture.REFUS_SALAIRE.label), 1)

    def test_stats_page_shows_motif_chart(self):
        Candidature.objects.create(
            poste="a", motif_cloture=MotifCloture.POSTE_POURVU
        )
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "Répartition par motif de clôture")


class CandidatureLibelleMergeTests(TestCase):
    """Issue #57 — fusion : plus de champ libellé, titre = entreprise — poste."""

    def test_no_libelle_field_on_model(self):
        self.assertFalse(hasattr(Candidature(), "libelle"))

    def test_str_composes_entreprise_poste(self):
        cand = Candidature.objects.create(entreprise="ACME", poste="Dev")
        self.assertEqual(str(cand), "ACME — Dev")

    def test_str_falls_back_when_empty(self):
        self.assertEqual(str(Candidature.objects.create()), "Candidature")

    def test_form_has_no_libelle_field(self):
        self.assertNotIn("libelle", CandidatureForm().fields)


class CandidatureEditPrefillTests(TestCase):
    """Issue #3 — les champs sont bien repris à l'édition (dates au format ISO)."""

    def test_dates_rendered_in_iso_for_date_input(self):
        import datetime
        c = Candidature(
            entreprise="ACME", poste="Dev",
            date_envoi=datetime.date(2026, 6, 1),
            date_entretien_1=datetime.date(2026, 6, 10),
        )
        form = CandidatureForm(instance=c)
        # <input type="date"> n'affiche la valeur que si elle est en AAAA-MM-JJ.
        self.assertIn('value="2026-06-01"', str(form["date_envoi"]))
        self.assertIn('value="2026-06-10"', str(form["date_entretien_1"]))

    def test_localisation_prefilled(self):
        c = Candidature(entreprise="ACME", poste="Dev", localisation="Lyon")
        form = CandidatureForm(instance=c)
        self.assertIn('value="Lyon"', str(form["localisation"]))


class CandidatureCreatedAtTests(TestCase):
    """Issue #58 — la date de création est visible sur le descriptif."""

    def test_creation_date_shown_on_detail(self):
        cand = Candidature.objects.create(poste="Dev")
        resp = self.client.get(
            reverse("tracking:candidature_detail", args=[cand.pk])
        )
        self.assertContains(resp, "Date de création")
        from django.utils import timezone
        self.assertContains(
            resp, timezone.localtime(cand.created_at).strftime("%d/%m/%Y")
        )


class CVUploadLimitTests(TestCase):
    """Issue #19 — un CV de plus de 5 Mo est refusé."""

    def _form(self, size):
        upload = SimpleUploadedFile(
            "cv.pdf", b"x" * size, content_type="application/pdf"
        )
        return CVForm(data={"label": "Mon CV"}, files={"file": upload})

    def test_rejette_au_dela_de_5mo(self):
        form = self._form(CVForm.MAX_UPLOAD_SIZE + 1)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_accepte_en_deca(self):
        form = self._form(1024)
        self.assertTrue(form.is_valid())


class FooterTests(TestCase):
    """Issue #20 — pied de page créditant l'auteur et Claude Code."""

    def test_footer_present(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "site-footer")
        self.assertContains(resp, "Patrick Lenoir")
        self.assertContains(resp, "Claude Code")


class CandidatureDeleteTests(TestCase):
    """Issue #21 — suppression d'une candidature."""

    def test_post_supprime(self):
        c = Candidature.objects.create(poste="Dev")
        resp = self.client.post(reverse("tracking:candidature_delete", args=[c.pk]))
        self.assertRedirects(resp, reverse("tracking:candidature_list"))
        self.assertFalse(Candidature.objects.filter(pk=c.pk).exists())

    def test_get_affiche_confirmation(self):
        c = Candidature.objects.create(poste="Dev")
        resp = self.client.get(reverse("tracking:candidature_delete", args=[c.pk]))
        self.assertContains(resp, "Supprimer définitivement")


class SiteDisableDeleteTests(TestCase):
    """Issue #22 — désactiver les sites par défaut, supprimer les manuels."""

    def test_site_par_defaut_non_supprimable(self):
        s = JobSite.objects.create(name="Défaut", is_builtin=True)
        resp = self.client.post(reverse("tracking:site_delete", args=[s.pk]))
        self.assertRedirects(resp, reverse("tracking:site_list"))
        self.assertTrue(JobSite.objects.filter(pk=s.pk).exists())

    def test_site_manuel_supprimable(self):
        s = JobSite.objects.create(name="Manuel", is_builtin=False)
        resp = self.client.post(reverse("tracking:site_delete", args=[s.pk]))
        self.assertRedirects(resp, reverse("tracking:site_list"))
        self.assertFalse(JobSite.objects.filter(pk=s.pk).exists())

    def test_toggle_desactive_et_reactive(self):
        s = JobSite.objects.create(name="Défaut", is_builtin=True)
        self.client.post(reverse("tracking:site_toggle_active", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.actif)
        self.client.post(reverse("tracking:site_toggle_active", args=[s.pk]))
        s.refresh_from_db()
        self.assertTrue(s.actif)

    def test_site_inactif_absent_du_formulaire(self):
        actif = JobSite.objects.create(name="Actif")
        inactif = JobSite.objects.create(name="Inactif", actif=False)
        qs = CandidatureForm().fields["source"].queryset
        self.assertIn(actif, qs)
        self.assertNotIn(inactif, qs)


class SiteFaviconTests(TestCase):
    """Issue #27 — favicon chargé par défaut, plus de lien « Logo » dans la liste."""

    def test_favicon_par_defaut_a_l_enregistrement(self):
        form = JobSiteForm(data={"name": "Exemple", "url": "https://www.exemple.fr/"})
        self.assertTrue(form.is_valid(), form.errors)
        site = form.save()
        self.assertEqual(
            site.logo_url,
            "https://www.google.com/s2/favicons?domain=www.exemple.fr&sz=64",
        )

    def test_logo_url_non_demande(self):
        """Issue #50 — le champ logo n'est plus proposé ; le favicon prime."""
        self.assertNotIn("logo_url", JobSiteForm().fields)
        # Même si un logo_url est posté, il est ignoré au profit du favicon.
        form = JobSiteForm(data={
            "name": "Exemple",
            "url": "https://www.exemple.fr/",
            "logo_url": "https://cdn.exemple.fr/logo.png",
        })
        self.assertTrue(form.is_valid(), form.errors)
        site = form.save()
        self.assertEqual(
            site.logo_url,
            "https://www.google.com/s2/favicons?domain=www.exemple.fr&sz=64",
        )

    def test_logo_resuit_si_url_modifiee(self):
        """Issue #50 — changer l'URL régénère le logo depuis le nouveau favicon."""
        site = JobSite.objects.create(
            name="Exemple", url="https://www.exemple.fr/",
            logo_url="https://ancien/logo.png",
        )
        form = JobSiteForm(
            data={"name": "Exemple", "url": "https://www.autre.fr/"}, instance=site
        )
        self.assertTrue(form.is_valid(), form.errors)
        site = form.save()
        self.assertEqual(
            site.logo_url,
            "https://www.google.com/s2/favicons?domain=www.autre.fr&sz=64",
        )

    def test_liste_sans_lien_logo(self):
        JobSite.objects.create(name="Exemple", url="https://www.exemple.fr/")
        resp = self.client.get(reverse("tracking:site_list"))
        # La colonne « Logo » subsiste ; seul le bouton d'action est retiré.
        self.assertNotContains(resp, "Logo</button>")


class CandidatureListColumnsTests(TestCase):
    """Issue #28 — la date d'envoi n'apparaît plus dans la liste."""

    def test_pas_de_colonne_date_envoi(self):
        Candidature.objects.create(poste="Dév")
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertNotContains(resp, "Date d'envoi")


class ChoicesTests(TestCase):
    """Issues #30, #31 — nouveaux motifs de clôture et canaux d'envoi."""

    def test_motif_pas_donne_suite(self):
        self.assertEqual(MotifCloture.PAS_DONNE_SUITE.value, "pas_donne_suite")

    def test_canaux_contact_entrant_et_relationnel(self):
        valeurs = [c.value for c in Canal]
        self.assertIn("contact_entrant", valeurs)
        self.assertIn("relationnel", valeurs)


class SiteToggleSwitchTests(TestCase):
    """Issue #32 — le bouton activer/désactiver est un interrupteur."""

    def test_liste_affiche_un_interrupteur(self):
        s = JobSite.objects.create(name="Exemple", actif=True)
        resp = self.client.get(reverse("tracking:site_list"))
        self.assertContains(resp, 'class="switch"')
        self.assertContains(resp, "this.form.submit()")


class AcceptationConfettiTests(TestCase):
    """Issue #23 — acceptation : barre verte à 100 % et confettis."""

    def test_progression_acceptee_verte_100(self):
        c = Candidature(poste="X", acceptation=True)
        p = c.progression()
        self.assertEqual(p["percent"], 100)
        self.assertTrue(p["accepted"])
        self.assertIn("120", p["color"])

    def test_message_confetti_a_l_acceptation(self):
        c = Candidature.objects.create(poste="X", acceptation=False)
        data = {
            "poste": "X",
            "canal_envoi": Canal.EMAIL,
            "statut": Statut.ENVOYEE,
            "acceptation": "on",
        }
        resp = self.client.post(
            reverse("tracking:candidature_update", args=[c.pk]), data, follow=True
        )
        self.assertContains(resp, "confetti")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class AIConfigModelTests(TestCase):
    """Issue #33 — configuration IA : singleton, état, clé chiffrée."""

    def test_load_is_singleton(self):
        a = AIConfig.load()
        b = AIConfig.load()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(AIConfig.objects.count(), 1)

    def test_default_model_and_unconfigured(self):
        config = AIConfig.load()
        self.assertEqual(config.model, AIConfig.DEFAULT_MODEL)
        self.assertFalse(config.is_configured)

    def test_api_key_round_trips_and_configures(self):
        config = AIConfig.load()
        config.gemini_api_key = "secret-gemini-key"
        config.save()
        reloaded = AIConfig.load()
        self.assertEqual(reloaded.api_key, "secret-gemini-key")
        self.assertTrue(reloaded.is_configured)

    def test_api_key_stored_encrypted_in_db(self):
        from django.db import connection

        config = AIConfig.load()
        config.gemini_api_key = "plain-key-123"
        config.save()
        # La valeur brute en base ne contient pas le secret en clair (chiffrée).
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT gemini_api_key FROM tracking_aiconfig WHERE id = %s", [config.pk]
            )
            raw = cursor.fetchone()[0]
        self.assertNotIn("plain-key-123", raw)

    def test_provider_switch_picks_right_key_and_model(self):
        """Issue #34 — fournisseur actif = clé + modèle correspondants."""
        config = AIConfig.load()
        config.gemini_api_key = "g-key"
        config.mistral_api_key = "m-key"
        config.mistral_model = "mistral-large-latest"
        config.provider = AIConfig.Provider.GEMINI
        config.save()
        config = AIConfig.load()
        self.assertEqual(config.api_key, "g-key")
        self.assertEqual(config.model, AIConfig.DEFAULT_GEMINI_MODEL)
        config.provider = AIConfig.Provider.MISTRAL
        config.save()
        config = AIConfig.load()
        self.assertEqual(config.api_key, "m-key")
        self.assertEqual(config.model, "mistral-large-latest")
        self.assertTrue(config.is_configured)

    def test_mistral_default_model(self):
        self.assertEqual(AIConfig.DEFAULT_MISTRAL_MODEL, "mistral-small-latest")

    def test_all_providers_available(self):
        """Issue #39 — ChatGPT, Claude et Perplexity s'ajoutent à Gemini/Mistral."""
        values = AIConfig.Provider.values
        for provider in ("gemini", "mistral", "openai", "anthropic", "perplexity"):
            self.assertIn(provider, values)
            self.assertIn(provider, AIConfig.MODELS_BY_PROVIDER)
            self.assertIn(provider, AIConfig.PROVIDER_INFO)

    def test_openai_provider_active_key_and_model(self):
        config = AIConfig.load()
        config.provider = AIConfig.Provider.OPENAI
        config.openai_api_key = "sk-test"
        config.save()
        config = AIConfig.load()
        self.assertEqual(config.api_key, "sk-test")
        self.assertEqual(config.model, AIConfig.DEFAULTS["openai"])
        self.assertTrue(config.is_configured)


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class AIConfigViewTests(TestCase):
    """Issue #33 — enregistrement / suppression de la config depuis l'aide."""

    def test_help_page_shows_ai_section(self):
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "Coaching IA")
        self.assertContains(resp, "Google Gemini")

    def test_default_model_is_25_flash(self):
        self.assertEqual(AIConfig.DEFAULT_MODEL, "gemini-2.5-flash")

    def test_help_page_has_provider_and_model_dropdowns(self):
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, '<select id="provider" name="provider">')
        self.assertContains(resp, '<select id="gemini_model" name="gemini_model">')
        self.assertContains(resp, '<select id="mistral_model" name="mistral_model">')
        self.assertContains(resp, "gemini-2.5-flash")
        self.assertContains(resp, "mistral-small-latest")
        self.assertContains(resp, "Mistral AI")

    def test_help_page_shows_new_providers(self):
        """Issue #39 — OpenAI, Anthropic et Perplexity et leurs liens doc."""
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "OpenAI (ChatGPT)")
        self.assertContains(resp, "Anthropic (Claude)")
        self.assertContains(resp, "Perplexity")
        self.assertContains(resp, "platform.openai.com/docs/guides/rate-limits")
        self.assertContains(resp, "platform.claude.com/docs/en/api/rate-limits")
        self.assertContains(resp, "docs.perplexity.ai")

    def test_ai_save_anthropic_provider(self):
        self.client.post(
            reverse("tracking:help"),
            {
                "action": "ai_save", "provider": "anthropic",
                "anthropic_api_key": "sk-ant", "anthropic_model": "claude-opus-4-8",
            },
        )
        config = AIConfig.load()
        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.api_key, "sk-ant")
        self.assertEqual(config.model, "claude-opus-4-8")

    def test_options_page_has_theme_picker(self):
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "Options")
        self.assertContains(resp, "theme-picker")
        self.assertContains(resp, 'data-theme-choice="dark"')
        # Thème LinkedIn (issue #68).
        self.assertContains(resp, 'data-theme-choice="linkedin"')

    def test_ai_save_sets_gemini_key_and_model(self):
        self.client.post(
            reverse("tracking:help"),
            {
                "action": "ai_save", "provider": "gemini",
                "gemini_api_key": "k-123", "gemini_model": "gemini-2.5-pro",
            },
        )
        config = AIConfig.load()
        self.assertEqual(config.provider, "gemini")
        self.assertEqual(config.api_key, "k-123")
        self.assertEqual(config.model, "gemini-2.5-pro")

    def test_ai_save_sets_mistral_provider_and_key(self):
        self.client.post(
            reverse("tracking:help"),
            {
                "action": "ai_save", "provider": "mistral",
                "mistral_api_key": "m-key", "mistral_model": "mistral-large-latest",
            },
        )
        config = AIConfig.load()
        self.assertEqual(config.provider, "mistral")
        self.assertEqual(config.api_key, "m-key")
        self.assertEqual(config.model, "mistral-large-latest")
        self.assertTrue(config.is_configured)

    def test_ai_save_keeps_other_provider_key(self):
        """Basculer de fournisseur ne perd pas la clé du précédent (issue #34)."""
        config = AIConfig.load()
        config.gemini_api_key = "g-key"
        config.save()
        self.client.post(
            reverse("tracking:help"),
            {"action": "ai_save", "provider": "mistral", "mistral_api_key": "m-key"},
        )
        config = AIConfig.load()
        self.assertEqual(config.gemini_api_key, "g-key")
        self.assertEqual(config.mistral_api_key, "m-key")

    def test_ai_save_empty_key_keeps_existing(self):
        config = AIConfig.load()
        config.gemini_api_key = "keep-me"
        config.save()
        self.client.post(
            reverse("tracking:help"),
            {"action": "ai_save", "provider": "gemini", "gemini_api_key": ""},
        )
        self.assertEqual(AIConfig.load().api_key, "keep-me")

    def test_ai_save_blank_model_falls_back_to_default(self):
        self.client.post(
            reverse("tracking:help"),
            {"action": "ai_save", "provider": "gemini", "gemini_api_key": "k", "gemini_model": "  "},
        )
        self.assertEqual(AIConfig.load().model, AIConfig.DEFAULT_GEMINI_MODEL)

    def test_ai_clear_removes_active_key(self):
        config = AIConfig.load()
        config.gemini_api_key = "to-remove"
        config.save()
        self.client.post(reverse("tracking:help"), {"action": "ai_clear"})
        self.assertFalse(AIConfig.load().is_configured)


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class AICoachingViewTests(TestCase):
    """Issue #33 — endpoint de coaching IA."""

    def _configure(self):
        config = AIConfig.load()
        config.gemini_api_key = "k"
        config.save()

    def test_requires_configuration(self):
        resp = self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_get_not_allowed(self):
        resp = self.client.get(reverse("tracking:ai_coaching"))
        self.assertEqual(resp.status_code, 405)

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("## Conseil\nFonce.", 10, 20, 30),
    )
    def test_returns_generated_text(self, gen):
        self._configure()
        resp = self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertIn("Conseil", resp.json()["text"])
        self.assertTrue(gen.called)

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("ok", 1, 1, 2),
    )
    def test_response_includes_provider_and_model(self, _gen):
        """Issue #37 — la réponse indique l'IA et le modèle utilisés."""
        config = AIConfig.load()
        config.gemini_api_key = "k"
        config.gemini_model = "gemini-2.5-pro"
        config.save()
        data = self.client.post(reverse("tracking:ai_coaching")).json()
        self.assertIn("Gemini", data["provider"])
        self.assertEqual(data["model"], "gemini-2.5-pro")

    @mock.patch(
        "tracking.coaching.ai.generate", side_effect=ai.AIError("Clé refusée")
    )
    def test_ai_error_returns_502(self, _gen):
        self._configure()
        resp = self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"], "Clé refusée")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class AIRelanceViewTests(TestCase):
    """Issues #33, #67 — génération du mail de relance IA (objet + corps)."""

    def setUp(self):
        self.cand = Candidature.objects.create(entreprise="ACME", poste="Dev")
        config = AIConfig.load()
        config.gemini_api_key = "k"
        config.save()

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult(
            '{"objet": "Relance ACME", "corps": "Bonjour,\\nje me permets…"}', 5, 8, 13
        ),
    )
    def test_returns_objet_and_corps(self, gen):
        resp = self.client.post(
            reverse("tracking:ai_relance_message", args=[self.cand.pk])
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["objet"], "Relance ACME")
        self.assertIn("Bonjour", data["corps"])
        # Le prompt envoyé mentionne l'entreprise de la candidature.
        self.assertIn("ACME", gen.call_args.args[0])

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("Texte libre non JSON", 5, 8, 13),
    )
    def test_non_json_falls_back_to_body(self, gen):
        resp = self.client.post(
            reverse("tracking:ai_relance_message", args=[self.cand.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["corps"], "Texte libre non JSON")

    def test_unknown_candidature_404(self):
        resp = self.client.post(reverse("tracking:ai_relance_message", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_detail_page_shows_relance_button(self):
        resp = self.client.get(
            reverse("tracking:candidature_detail", args=[self.cand.pk])
        )
        self.assertContains(resp, "🔔 Relancer")
        self.assertContains(resp, "relance-modal")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class RelanceReminderTests(TestCase):
    """Issue #67 — rappel visuel de relance après N jours sans réponse."""

    def _aged_candidature(self, jours, **kwargs):
        """Candidature dont la dernière activité (historique) remonte à N jours."""
        cand = Candidature.objects.create(poste="Dev", **kwargs)
        # On vieillit l'entrée d'historique pour simuler l'absence de réponse.
        old = timezone.now() - timedelta(days=jours)
        history = StatusHistory.objects.create(candidature=cand, statut=cand.statut)
        StatusHistory.objects.filter(pk=history.pk).update(date=old)
        return cand

    def test_relance_due_after_delay(self):
        cand = self._aged_candidature(12, statut=Statut.ENVOYEE)
        self.assertEqual(cand.relance_due_jours(10), 12)

    def test_no_relance_before_delay(self):
        cand = self._aged_candidature(5, statut=Statut.ENVOYEE)
        self.assertIsNone(cand.relance_due_jours(10))

    def test_no_relance_for_non_waiting_status(self):
        cand = self._aged_candidature(30, statut=Statut.OFFRE)
        self.assertIsNone(cand.relance_due_jours(10))

    def test_no_relance_when_closed(self):
        cand = self._aged_candidature(
            30, statut=Statut.ENVOYEE, motif_cloture=MotifCloture.POSTE_POURVU
        )
        self.assertIsNone(cand.relance_due_jours(10))

    def test_zero_delay_disables_reminders(self):
        cand = self._aged_candidature(30, statut=Statut.ENVOYEE)
        self.assertIsNone(cand.relance_due_jours(0))

    def test_list_shows_reminder_badge(self):
        self._aged_candidature(15, entreprise="ACME", statut=Statut.ENVOYEE)
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "🔔 Relance")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class ReminderConfigTests(TestCase):
    """Issue #67 — configuration des relances (délai + Gmail) via Options."""

    def test_save_config(self):
        resp = self.client.post(
            reverse("tracking:help"),
            {
                "action": "relance_save",
                "delai_jours": "7",
                "gmail_email": "moi@gmail.com",
                "gmail_app_password": "abcd efgh ijkl mnop",
            },
        )
        self.assertEqual(resp.status_code, 302)
        config = ReminderConfig.load()
        self.assertEqual(config.delai_jours, 7)
        self.assertEqual(config.gmail_email, "moi@gmail.com")
        self.assertTrue(config.email_configured)

    def test_password_kept_when_blank(self):
        config = ReminderConfig.load()
        config.gmail_email = "moi@gmail.com"
        config.gmail_app_password = "secret"
        config.save()
        self.client.post(
            reverse("tracking:help"),
            {"action": "relance_save", "delai_jours": "9",
             "gmail_email": "moi@gmail.com", "gmail_app_password": ""},
        )
        config = ReminderConfig.load()
        self.assertEqual(config.gmail_app_password, "secret")
        self.assertEqual(config.delai_jours, 9)


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class RelanceSendTests(TestCase):
    """Issue #67 — envoi de l'email de relance via Gmail."""

    def setUp(self):
        self.cand = Candidature.objects.create(
            entreprise="ACME", poste="Dev", statut=Statut.ENVOYEE
        )
        config = ReminderConfig.load()
        config.gmail_email = "moi@gmail.com"
        config.gmail_app_password = "secret"
        config.save()

    @mock.patch("tracking.views.mailing.send_email")
    def test_send_marks_relancee(self, send):
        resp = self.client.post(
            reverse("tracking:candidature_relance_send", args=[self.cand.pk]),
            {"destinataire": "rh@acme.com", "objet": "Relance", "corps": "Bonjour"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        send.assert_called_once()
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.statut, Statut.RELANCEE)
        # Une entrée d'historique réinitialise le compteur de relance.
        self.assertTrue(self.cand.status_history.exists())

    def test_manual_relance_marks_relancee(self):
        resp = self.client.post(
            reverse("tracking:candidature_relance_manual", args=[self.cand.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.statut, Statut.RELANCEE)
        self.assertTrue(self.cand.status_history.exists())

    def test_manual_relance_non_ajax_redirects(self):
        resp = self.client.post(
            reverse("tracking:candidature_relance_manual", args=[self.cand.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.statut, Statut.RELANCEE)

    def test_send_requires_body(self):
        resp = self.client.post(
            reverse("tracking:candidature_relance_send", args=[self.cand.pk]),
            {"destinataire": "rh@acme.com", "objet": "Relance", "corps": "  "},
        )
        self.assertEqual(resp.status_code, 400)

    @mock.patch(
        "tracking.views.mailing.send_email",
        side_effect=mailing.MailError("Connexion Gmail non configurée."),
    )
    def test_send_error_returns_502(self, send):
        resp = self.client.post(
            reverse("tracking:candidature_relance_send", args=[self.cand.pk]),
            {"destinataire": "rh@acme.com", "objet": "x", "corps": "Bonjour"},
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("Gmail", resp.json()["error"])


class MailingTests(TestCase):
    """Issue #67 — module d'envoi Gmail (smtplib)."""

    def test_not_configured_raises(self):
        config = ReminderConfig(gmail_email="", gmail_app_password="")
        with self.assertRaises(mailing.MailError):
            mailing.send_email(config, "rh@acme.com", "Objet", "Corps")

    def test_missing_recipient_raises(self):
        config = ReminderConfig(gmail_email="moi@gmail.com", gmail_app_password="x")
        with self.assertRaises(mailing.MailError):
            mailing.send_email(config, "", "Objet", "Corps")

    @mock.patch("tracking.mailing.smtplib.SMTP")
    def test_sends_via_smtp(self, smtp):
        config = ReminderConfig(gmail_email="moi@gmail.com", gmail_app_password="x")
        mailing.send_email(config, "rh@acme.com", "Objet", "Corps")
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("moi@gmail.com", "x")
        server.send_message.assert_called_once()

    @mock.patch("tracking.mailing.smtplib.SMTP")
    def test_connection_logs_in_without_sending(self, smtp):
        config = ReminderConfig(gmail_email="moi@gmail.com", gmail_app_password="x")
        mailing.test_connection(config)
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("moi@gmail.com", "x")
        server.send_message.assert_not_called()

    def test_connection_not_configured_raises(self):
        with self.assertRaises(mailing.MailError):
            mailing.test_connection(ReminderConfig())


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class RelanceTestConnectionViewTests(TestCase):
    """Issue #67 — endpoint de test de la connexion Gmail."""

    @mock.patch("tracking.views.mailing.test_connection")
    def test_ok_with_form_values(self, test_conn):
        resp = self.client.post(
            reverse("tracking:relance_test_email"),
            {"gmail_email": "moi@gmail.com", "gmail_app_password": "secret"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        # Les valeurs du formulaire sont utilisées pour le test.
        config = test_conn.call_args.args[0]
        self.assertEqual(config.gmail_email, "moi@gmail.com")
        self.assertEqual(config.gmail_app_password, "secret")

    @mock.patch("tracking.views.mailing.test_connection")
    def test_blank_password_falls_back_to_saved(self, test_conn):
        saved = ReminderConfig.load()
        saved.gmail_email = "moi@gmail.com"
        saved.gmail_app_password = "garde"
        saved.save()
        self.client.post(
            reverse("tracking:relance_test_email"),
            {"gmail_email": "moi@gmail.com", "gmail_app_password": ""},
        )
        self.assertEqual(test_conn.call_args.args[0].gmail_app_password, "garde")

    @mock.patch(
        "tracking.views.mailing.test_connection",
        side_effect=mailing.MailError("Échec de la connexion : auth"),
    )
    def test_failure_returns_502(self, test_conn):
        resp = self.client.post(
            reverse("tracking:relance_test_email"),
            {"gmail_email": "moi@gmail.com", "gmail_app_password": "bad"},
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("Échec", resp.json()["error"])


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY, MEDIA_ROOT=tempfile.mkdtemp())
class AIReferencesViewTests(TestCase):
    """Issue #64 — extrait d'email des références via l'IA."""

    def setUp(self):
        self.cv = CV.objects.create(label="CV", file=SimpleUploadedFile("cv.txt", b"x"))
        config = AIConfig.load()
        config.gemini_api_key = "k"
        config.save()

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("Comme demandé, voici mes références.", 5, 8, 13),
    )
    def test_returns_excerpt(self, gen):
        Reference.objects.create(
            cv=self.cv, nom="Durand", prenom="Marie", telephone="0102030405"
        )
        resp = self.client.post(reverse("tracking:ai_references", args=[self.cv.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("références", resp.json()["text"])
        # Le prompt envoyé mentionne la référence et ses coordonnées.
        prompt = gen.call_args.args[0]
        self.assertIn("Durand", prompt)
        self.assertIn("0102030405", prompt)

    def test_sans_reference_erreur_400(self):
        resp = self.client.post(reverse("tracking:ai_references", args=[self.cv.pk]))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("référence", resp.json()["error"])

    def test_unknown_cv_404(self):
        resp = self.client.post(reverse("tracking:ai_references", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_refuse_get(self):
        resp = self.client.get(reverse("tracking:ai_references", args=[self.cv.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_detail_page_shows_button(self):
        Reference.objects.create(cv=self.cv, nom="Durand")
        resp = self.client.get(reverse("tracking:cv_detail", args=[self.cv.pk]))
        self.assertContains(resp, "Extrait pour email (IA)")
        self.assertContains(resp, reverse("tracking:ai_references", args=[self.cv.pk]))


class GeminiClientTests(TestCase):
    """Issue #33 — client HTTP Gemini (parsing et erreurs), réseau simulé."""

    def _response(self, payload):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return cm

    def test_guess_mime(self):
        self.assertEqual(ai.guess_mime("cv.pdf"), "application/pdf")
        self.assertTrue(ai.guess_mime("photo.png").startswith("image/"))
        self.assertIsNone(ai.guess_mime("archive.zip"))

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_extracts_text_and_tokens(self, urlopen):
        urlopen.return_value = self._response(
            {
                "candidates": [{"content": {"parts": [{"text": "Bonjour"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 8,
                    "totalTokenCount": 20,
                },
            }
        )
        out = ai.generate("hi", api_key="k", model="m")
        self.assertEqual(out.text, "Bonjour")
        self.assertEqual(out.total_tokens, 20)
        self.assertEqual(out.prompt_tokens, 12)

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_empty_candidates_raise(self, urlopen):
        urlopen.return_value = self._response({"candidates": []})
        with self.assertRaises(ai.AIError):
            ai.generate("hi", api_key="k", model="m")

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_http_error_becomes_aierror(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "url", 403, "Forbidden", {}, io_bytes(b'{"error":{"message":"bad key"}}')
        )
        with self.assertRaises(ai.AIError) as ctx:
            ai.generate("hi", api_key="k", model="m")
        self.assertIn("refus", str(ctx.exception).lower())

    def test_missing_key_raises(self):
        with self.assertRaises(ai.AIError):
            ai.generate("hi", api_key="", model="m")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class AIUsageQuotaTests(TestCase):
    """Issue #36 — suivi de consommation et limite mensuelle souple."""

    def _configure(self, **kwargs):
        config = AIConfig.load()
        config.gemini_api_key = "k"
        for key, value in kwargs.items():
            setattr(config, key, value)
        config.save()
        return config

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("ok", 10, 15, 25),
    )
    def test_coaching_records_usage(self, _gen):
        self._configure()
        self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(AIUsage.objects.count(), 1)
        usage = AIUsage.objects.get()
        self.assertEqual(usage.provider, "gemini")
        self.assertEqual(usage.total_tokens, 25)

    def test_month_summary_aggregates(self):
        AIUsage.objects.create(provider="gemini", model="m", total_tokens=100)
        AIUsage.objects.create(provider="gemini", model="m", total_tokens=50)
        AIUsage.objects.create(provider="mistral", model="m", total_tokens=999)
        summary = AIUsage.month_summary("gemini")
        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["tokens"], 150)

    def test_save_monthly_limit(self):
        self.client.post(
            reverse("tracking:help"),
            {"action": "ai_save", "provider": "gemini", "gemini_monthly_limit": "5000"},
        )
        self.assertEqual(AIConfig.load().gemini_monthly_limit, 5000)

    def test_invalid_limit_falls_back_to_zero(self):
        self.client.post(
            reverse("tracking:help"),
            {"action": "ai_save", "provider": "gemini", "gemini_monthly_limit": "abc"},
        )
        self.assertEqual(AIConfig.load().gemini_monthly_limit, 0)

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("ok", 10, 15, 25),
    )
    def test_warning_when_limit_reached(self, _gen):
        self._configure(gemini_monthly_limit=10)
        resp = self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(resp.status_code, 200)
        # 25 tokens > limite 10 : avertissement présent, mais appel non bloqué.
        self.assertIn("warning", resp.json())
        self.assertIn("imite mensuelle atteinte", resp.json()["warning"])

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("ok", 1, 1, 2),
    )
    def test_no_warning_under_limit(self, _gen):
        self._configure(gemini_monthly_limit=10000)
        resp = self.client.post(reverse("tracking:ai_coaching"))
        self.assertNotIn("warning", resp.json())

    def test_help_page_shows_usage(self):
        self._configure(gemini_monthly_limit=1000)
        AIUsage.objects.create(provider="gemini", model="m", total_tokens=400)
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "Ce mois-ci")
        self.assertContains(resp, "Limite mensuelle")
        self.assertContains(resp, 'name="gemini_monthly_limit"')

    def test_help_page_shows_quota_doc_links(self):
        """Issue #38 — rappel des quotas du tier gratuit + liens doc."""
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "ai.google.dev/gemini-api/docs/billing")
        self.assertContains(resp, "docs.mistral.ai/admin/user-management-finops/tier")
        self.assertContains(resp, "Documentation officielle")


class MistralClientTests(TestCase):
    """Issue #34 — client HTTP Mistral (parsing et aiguillage), réseau simulé."""

    def _response(self, payload):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return cm

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_extracts_message_content_and_tokens(self, urlopen):
        urlopen.return_value = self._response(
            {
                "choices": [{"message": {"content": "Salut"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            }
        )
        out = ai.generate("hi", api_key="k", model="mistral-small-latest", provider="mistral")
        self.assertEqual(out.text, "Salut")
        self.assertEqual(out.total_tokens, 10)
        # L'URL appelée est bien celle de Mistral.
        called_url = urlopen.call_args.args[0].full_url
        self.assertIn("api.mistral.ai", called_url)

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_empty_choices_raise(self, urlopen):
        urlopen.return_value = self._response({"choices": []})
        with self.assertRaises(ai.AIError):
            ai.generate("hi", api_key="k", model="m", provider="mistral")

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_openai_uses_openai_url(self, urlopen):
        urlopen.return_value = self._response(
            {"choices": [{"message": {"content": "Hello"}}],
             "usage": {"total_tokens": 7}}
        )
        out = ai.generate("hi", api_key="k", model="gpt-4o-mini", provider="openai")
        self.assertEqual(out.text, "Hello")
        self.assertIn("api.openai.com", urlopen.call_args.args[0].full_url)

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_perplexity_uses_perplexity_url(self, urlopen):
        urlopen.return_value = self._response(
            {"choices": [{"message": {"content": "Hi"}}], "usage": {"total_tokens": 3}}
        )
        ai.generate("hi", api_key="k", model="sonar", provider="perplexity")
        self.assertIn("api.perplexity.ai", urlopen.call_args.args[0].full_url)


class AnthropicClientTests(TestCase):
    """Issue #39 — client HTTP Anthropic (API Messages), réseau simulé."""

    def _response(self, payload):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return cm

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_extracts_text_and_tokens(self, urlopen):
        urlopen.return_value = self._response(
            {
                "content": [{"type": "text", "text": "Bonjour"}],
                "usage": {"input_tokens": 7, "output_tokens": 5},
            }
        )
        out = ai.generate("hi", api_key="k", model="claude-haiku-4-5", provider="anthropic")
        self.assertEqual(out.text, "Bonjour")
        self.assertEqual(out.total_tokens, 12)
        # En-tête de version Anthropic + bonne URL.
        req = urlopen.call_args.args[0]
        self.assertIn("api.anthropic.com", req.full_url)
        self.assertEqual(req.headers.get("Anthropic-version"), ai.ANTHROPIC_VERSION)

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_empty_content_raises(self, urlopen):
        urlopen.return_value = self._response({"content": []})
        with self.assertRaises(ai.AIError):
            ai.generate("hi", api_key="k", model="m", provider="anthropic")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class CoachingProviderTests(TestCase):
    """Issue #34 — le fournisseur configuré est transmis au client IA."""

    @mock.patch("tracking.ai.generate", return_value=ai.GenerationResult("ok", 1, 2, 3))
    def test_provider_passed_to_client(self, gen):
        config = AIConfig.load()
        config.provider = AIConfig.Provider.MISTRAL
        config.mistral_api_key = "m-key"
        config.save()
        self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(gen.call_args.kwargs["provider"], "mistral")
        self.assertEqual(gen.call_args.kwargs["api_key"], "m-key")
        # Pas de pièce jointe CV pour Mistral (texte seul).
        self.assertIsNone(gen.call_args.kwargs.get("attachments"))


CV_ANALYSIS_JSON = json.dumps(
    {
        "titre_profil": "Développeur Python",
        "experiences": [
            {
                "poste": "Développeur backend",
                "entreprise": "ACME",
                "periode": "2020-2023",
                "description": "APIs Django",
            }
        ],
        "formations": [
            {"intitule": "Master Informatique", "etablissement": "Univ", "periode": "2018"}
        ],
        "competences": ["Python", "Django"],
        "langues": ["Français", "Anglais"],
        "infos": "Permis B",
    }
)


@override_settings(
    CANDITRACK_FERNET_KEY=TEST_FERNET_KEY, MEDIA_ROOT=tempfile.mkdtemp()
)
class CVAnalysisTests(TestCase):
    """Issue #44 — analyse IA des CV au chargement et à la demande."""

    def _configure_ai(self):
        config = AIConfig.load()
        config.gemini_api_key = "k"
        config.save()
        return config

    def _upload(self, analyser=True, content=b"Contenu du CV"):
        upload = SimpleUploadedFile("cv.txt", content, content_type="text/plain")
        data = {"label": "Mon CV", "file": upload}
        if analyser:
            data["analyser"] = "on"
        return self.client.post(reverse("tracking:cv_create"), data)

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult(CV_ANALYSIS_JSON, 10, 20, 30),
    )
    def test_upload_avec_analyse_stocke_les_infos(self, gen):
        self._configure_ai()
        self._upload(analyser=True)
        self.assertTrue(gen.called)
        cv = CV.objects.get()
        self.assertTrue(cv.is_analyzed)
        self.assertEqual(cv.analysis["titre_profil"], "Développeur Python")
        self.assertEqual(len(cv.analysis["experiences"]), 1)
        self.assertIn("Python", cv.analysis["competences"])
        self.assertEqual(cv.analysis_provider, "gemini")
        # La consommation de tokens est journalisée (issue #36).
        self.assertEqual(AIUsage.objects.count(), 1)

    @mock.patch("tracking.coaching.ai.generate")
    def test_upload_sans_case_cochee_pas_d_analyse(self, gen):
        self._configure_ai()
        self._upload(analyser=False)
        self.assertFalse(gen.called)
        self.assertFalse(CV.objects.get().is_analyzed)

    @mock.patch("tracking.coaching.ai.generate")
    def test_upload_sans_ia_configuree_pas_d_analyse(self, gen):
        self._upload(analyser=True)
        self.assertFalse(gen.called)
        self.assertFalse(CV.objects.get().is_analyzed)

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("ceci n'est pas du JSON", 1, 1, 2),
    )
    def test_reponse_illisible_enregistre_une_erreur(self, _gen):
        self._configure_ai()
        self._upload(analyser=True)
        cv = CV.objects.get()
        self.assertFalse(cv.is_analyzed)
        self.assertTrue(cv.analysis_error)

    @mock.patch("tracking.coaching.ai.generate")
    def test_reanalyse_remet_a_zero_et_met_a_jour(self, gen):
        config = self._configure_ai()
        # Première analyse.
        gen.return_value = ai.GenerationResult(CV_ANALYSIS_JSON, 1, 1, 2)
        self._upload(analyser=True)
        cv = CV.objects.get()
        # Ré-analyse avec un autre contenu.
        autre = json.dumps({"titre_profil": "Chef de projet", "competences": ["Agile"]})
        gen.return_value = ai.GenerationResult(autre, 1, 1, 2)
        self.client.post(reverse("tracking:cv_analyze", args=[cv.pk]))
        cv.refresh_from_db()
        self.assertEqual(cv.analysis["titre_profil"], "Chef de projet")
        self.assertEqual(cv.analysis["experiences"], [])

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult(CV_ANALYSIS_JSON, 1, 1, 2),
    )
    def test_detail_affiche_les_sections(self, _gen):
        self._configure_ai()
        self._upload(analyser=True)
        cv = CV.objects.get()
        resp = self.client.get(reverse("tracking:cv_detail", args=[cv.pk]))
        self.assertContains(resp, "Expériences")
        self.assertContains(resp, "Développeur Python")
        self.assertContains(resp, "Python")

    @mock.patch("tracking.coaching.ai.generate")
    def test_carte_localisations(self, gen):
        """Issue #44 — points de la carte (société + type) ne gardent que les lieux."""
        analyse = json.dumps(
            {
                "experiences": [
                    {"poste": "Dev", "entreprise": "ACME", "lieu": "Paris"},
                    {"poste": "Lead", "entreprise": "Sans lieu"},
                ],
                "formations": [
                    {"intitule": "Master", "etablissement": "Univ", "lieu": "Lyon"}
                ],
            }
        )
        gen.return_value = ai.GenerationResult(analyse, 1, 1, 2)
        self._configure_ai()
        self._upload(analyser=True)
        cv = CV.objects.get()
        points = views._cv_localisations(cv)
        # Seuls les éléments avec un lieu sont retenus.
        self.assertEqual([p["lieu"] for p in points], ["Paris", "Lyon"])
        self.assertEqual(points[0]["type"], "exp")
        self.assertEqual(points[0]["societe"], "ACME")
        self.assertEqual(points[1]["type"], "form")

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult(
            json.dumps(
                {"experiences": [{"poste": "Dev", "entreprise": "ACME", "lieu": "Paris"}]}
            ),
            1, 1, 2,
        ),
    )
    def test_carte_openstreetmap(self, _gen):
        """Issue #44 — carte OpenStreetMap/Leaflet sans clé API."""
        self._configure_ai()
        self._upload(analyser=True)
        cv = CV.objects.get()
        resp = self.client.get(reverse("tracking:cv_detail", args=[cv.pk]))
        self.assertContains(resp, 'id="cv-map"')
        self.assertContains(resp, 'id="cv-localisations-data"')
        # Leaflet + tuiles OSM + données de localisation embarquées.
        self.assertContains(resp, "unpkg.com/leaflet")
        self.assertContains(resp, "tile.openstreetmap.org")
        self.assertContains(resp, "nominatim.openstreetmap.org")
        self.assertContains(resp, "ACME")
        # Plus aucune dépendance à Google Maps.
        self.assertNotContains(resp, "maps.googleapis.com")

    def test_pas_de_carte_sans_localisation(self):
        """Sans lieu géolocalisable, aucune carte n'est rendue (issue #44)."""
        analyse = json.dumps({"titre_profil": "Dev", "competences": ["Python"]})
        with mock.patch(
            "tracking.coaching.ai.generate",
            return_value=ai.GenerationResult(analyse, 1, 1, 2),
        ):
            self._configure_ai()
            self._upload(analyser=True)
        cv = CV.objects.get()
        resp = self.client.get(reverse("tracking:cv_detail", args=[cv.pk]))
        self.assertNotContains(resp, 'id="cv-map"')

    # --- Exports (issue #44) ---------------------------------------------

    EXPORT_ANALYSIS = json.dumps(
        {
            "titre_profil": "Développeur Python",
            "localisation": "Lyon",
            "experiences": [
                {"poste": "Dev", "entreprise": "ACME", "lieu": "Paris",
                 "lien": "https://acme.example", "periode": "2020-2023",
                 "description": "APIs Django"}
            ],
            "formations": [
                {"intitule": "Master", "etablissement": "Univ", "lieu": "Lyon",
                 "periode": "2018"}
            ],
            "competences": ["Python", "Django"],
            "langues": ["Français", "Anglais"],
            "coordonnees": {"adresse": "1 rue X", "telephone": "0600",
                            "email": "a@b.fr", "permis": "Permis B"},
            "loisirs": ["Course"],
            "infos": "Certifié AWS",
        }
    )

    def _upload_analysed(self):
        with mock.patch(
            "tracking.coaching.ai.generate",
            return_value=ai.GenerationResult(self.EXPORT_ANALYSIS, 1, 1, 2),
        ):
            self._configure_ai()
            self._upload(analyser=True)
        return CV.objects.get()

    def test_export_json_resume(self):
        cv = self._upload_analysed()
        resp = self.client.get(
            reverse("tracking:cv_export", args=[cv.pk, "json-resume"])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/json", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        data = json.loads(resp.content)
        self.assertEqual(data["basics"]["label"], "Développeur Python")
        self.assertEqual(data["basics"]["email"], "a@b.fr")
        self.assertEqual(data["work"][0]["position"], "Dev")
        self.assertEqual(data["work"][0]["name"], "ACME")
        self.assertEqual([s["name"] for s in data["skills"]], ["Python", "Django"])
        self.assertEqual(data["interests"][0]["name"], "Course")

    def test_export_europass(self):
        cv = self._upload_analysed()
        resp = self.client.get(reverse("tracking:cv_export", args=[cv.pk, "europass"]))
        data = json.loads(resp.content)
        learner = data["SkillsPassport"]["LearnerInfo"]
        self.assertEqual(learner["Headline"]["Description"]["Label"], "Développeur Python")
        self.assertEqual(learner["WorkExperience"][0]["Position"]["Label"], "Dev")
        self.assertEqual(learner["DrivingLicence"], ["Permis B"])

    def test_export_hr_open(self):
        cv = self._upload_analysed()
        resp = self.client.get(reverse("tracking:cv_export", args=[cv.pk, "hr-open"]))
        data = json.loads(resp.content)
        cand = data["candidate"]
        self.assertEqual(cand["employmentHistory"][0]["positionTitle"], "Dev")
        self.assertEqual(cand["languageCompetencies"][0]["languageName"], "Français")
        self.assertEqual(cand["licenses"][0]["name"], "Permis B")

    def test_export_format_inconnu_404(self):
        cv = self._upload_analysed()
        resp = self.client.get(reverse("tracking:cv_export", args=[cv.pk, "xml"]))
        self.assertEqual(resp.status_code, 404)

    def test_export_cv_non_analyse_404(self):
        self._upload(analyser=False)
        cv = CV.objects.get()
        resp = self.client.get(
            reverse("tracking:cv_export", args=[cv.pk, "json-resume"])
        )
        self.assertEqual(resp.status_code, 404)

    def test_vue_impression_pdf(self):
        cv = self._upload_analysed()
        resp = self.client.get(reverse("tracking:cv_print", args=[cv.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Développeur Python")
        self.assertContains(resp, "window.print()")

    def test_boutons_export_sur_la_fiche(self):
        cv = self._upload_analysed()
        resp = self.client.get(reverse("tracking:cv_detail", args=[cv.pk]))
        self.assertContains(resp, reverse("tracking:cv_export", args=[cv.pk, "europass"]))
        self.assertContains(resp, reverse("tracking:cv_print", args=[cv.pk]))
        self.assertContains(resp, "JSON Resume")

    def test_formulaire_propose_la_case_si_ia_configuree(self):
        self._configure_ai()
        resp = self.client.get(reverse("tracking:cv_create"))
        self.assertContains(resp, 'name="analyser"')

    def test_formulaire_sans_case_si_pas_d_ia(self):
        resp = self.client.get(reverse("tracking:cv_create"))
        self.assertNotContains(resp, 'name="analyser"')

    def test_liste_ne_montre_plus_la_note_future(self):
        resp = self.client.get(reverse("tracking:cv_list"))
        self.assertNotContains(resp, "prochaine itération")

    def test_parse_tolere_les_balises_de_code(self):
        text = "```json\n" + CV_ANALYSIS_JSON + "\n```"
        data = coaching._parse_cv_analysis(text)
        self.assertIsNotNone(data)
        self.assertEqual(data["titre_profil"], "Développeur Python")

    def test_parse_json_invalide_renvoie_none(self):
        self.assertIsNone(coaching._parse_cv_analysis("pas du json"))

    def test_parse_extrait_lieux_et_liens(self):
        """Issue #44 — localisation, lieux et liens des expériences/formations."""
        text = json.dumps(
            {
                "localisation": "Lyon, France",
                "experiences": [
                    {
                        "poste": "Dev",
                        "entreprise": "ACME",
                        "lieu": "Paris",
                        "lien": "acme.example",
                        "periode": "2020",
                    }
                ],
                "formations": [
                    {
                        "intitule": "Master",
                        "etablissement": "Univ",
                        "lieu": "Lyon",
                        "lien": "https://univ.example",
                    }
                ],
            }
        )
        data = coaching._parse_cv_analysis(text)
        self.assertEqual(data["localisation"], "Lyon, France")
        self.assertEqual(data["experiences"][0]["lieu"], "Paris")
        # URL sans schéma → préfixée en https.
        self.assertEqual(data["experiences"][0]["lien"], "https://acme.example")
        self.assertEqual(data["formations"][0]["lien"], "https://univ.example")

    def test_parse_separe_coordonnees_et_loisirs(self):
        """Issue #44 — références (coordonnées) et loisirs en sections distinctes."""
        text = json.dumps(
            {
                "coordonnees": {
                    "adresse": "1 rue X, Paris",
                    "telephone": "0600000000",
                    "email": "a@b.fr",
                    "permis": "Permis B",
                },
                "loisirs": ["Course à pied", "Photographie"],
                "infos": "Certifié AWS",
            }
        )
        data = coaching._parse_cv_analysis(text)
        self.assertEqual(data["coordonnees"]["telephone"], "0600000000")
        self.assertEqual(data["coordonnees"]["permis"], "Permis B")
        self.assertEqual(data["loisirs"], ["Course à pied", "Photographie"])
        self.assertEqual(data["infos"], "Certifié AWS")

    def test_parse_coordonnees_vides_donnent_dict_vide(self):
        """Des coordonnées absentes restent un dict vide (issue #44)."""
        data = coaching._parse_cv_analysis(json.dumps({"titre_profil": "Dev"}))
        self.assertEqual(data["coordonnees"], {})
        self.assertEqual(data["loisirs"], [])

    def test_parse_ecarte_les_liens_dangereux(self):
        """Un schéma non http(s) est écarté (issue #44)."""
        text = json.dumps(
            {
                "experiences": [
                    {"poste": "A", "lien": "javascript:alert(1)"},
                    {"poste": "B", "lien": "ftp://host.example/x"},
                ]
            }
        )
        data = coaching._parse_cv_analysis(text)
        self.assertEqual(data["experiences"][0]["lien"], "")
        self.assertEqual(data["experiences"][1]["lien"], "")

    def test_parse_promeut_les_liens_http_en_https(self):
        """Un lien http est promu en https pour éviter le contenu mixte (issue #44)."""
        text = json.dumps(
            {"experiences": [{"poste": "Dev", "lien": "http://acme.example/x"}]}
        )
        data = coaching._parse_cv_analysis(text)
        self.assertEqual(data["experiences"][0]["lien"], "https://acme.example/x")

    def _docx_bytes(self, text):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document><w:body>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
                "</w:body></w:document>",
            )
        return buf.getvalue()

    def test_extrait_le_texte_d_un_docx(self):
        cv = CV.objects.create(
            label="x",
            file=SimpleUploadedFile("cv.docx", self._docx_bytes("Ingénieur logiciel")),
        )
        self.assertIn("Ingénieur logiciel", coaching._cv_text(cv))

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult(CV_ANALYSIS_JSON, 1, 1, 2),
    )
    def test_analyse_docx_passe_le_texte_dans_le_prompt(self, gen):
        self._configure_ai()  # Gemini par défaut
        cv = CV.objects.create(
            label="x",
            file=SimpleUploadedFile("cv.docx", self._docx_bytes("Ingénieur logiciel")),
        )
        coaching.analyze_cv(cv)
        self.assertTrue(cv.is_analyzed)
        # Word n'est pas joignable : le texte extrait part dans le prompt, sans pièce jointe.
        self.assertIsNone(gen.call_args.kwargs.get("attachments"))
        self.assertIn("Ingénieur logiciel", gen.call_args.args[0])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CVArchiveTests(TestCase):
    """Issue #48 — un CV peut être actif ou archivé."""

    def _make_cv(self, label="CV", actif=True):
        cv = CV.objects.create(
            label=label, file=SimpleUploadedFile(f"{label}.txt", b"x")
        )
        if not actif:
            cv.actif = False
            cv.save(update_fields=["actif"])
        return cv

    def test_cv_actif_par_defaut(self):
        self.assertTrue(self._make_cv().actif)

    def test_archiver_puis_reactiver(self):
        cv = self._make_cv()
        self.client.post(reverse("tracking:cv_toggle_active", args=[cv.pk]))
        cv.refresh_from_db()
        self.assertFalse(cv.actif)
        self.client.post(reverse("tracking:cv_toggle_active", args=[cv.pk]))
        cv.refresh_from_db()
        self.assertTrue(cv.actif)

    def test_liste_separe_actifs_et_archives(self):
        self._make_cv("Actif")
        self._make_cv("Vieux", actif=False)
        resp = self.client.get(reverse("tracking:cv_list"))
        self.assertEqual([c.label for c in resp.context["cvs"]], ["Actif"])
        self.assertEqual([c.label for c in resp.context["cvs_archives"]], ["Vieux"])
        self.assertContains(resp, "CV archivés")

    def test_toggle_refuse_get(self):
        cv = self._make_cv()
        resp = self.client.get(reverse("tracking:cv_toggle_active", args=[cv.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_toggle_next_local_respecte(self):
        cv = self._make_cv()
        cible = reverse("tracking:cv_detail", args=[cv.pk])
        resp = self.client.post(
            reverse("tracking:cv_toggle_active", args=[cv.pk]), {"next": cible}
        )
        self.assertRedirects(resp, cible, fetch_redirect_response=False)

    def test_toggle_next_externe_ignore(self):
        """Un « next » hors site est ignoré (anti open-redirect, S5146)."""
        cv = self._make_cv()
        resp = self.client.post(
            reverse("tracking:cv_toggle_active", args=[cv.pk]),
            {"next": "https://evil.example/phish"},
        )
        self.assertRedirects(resp, reverse("tracking:cv_list"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CVCandidatureLinkTests(TestCase):
    """Issue #49 — lier un CV à une candidature."""

    def _make_cv(self, label="CV", actif=True):
        cv = CV.objects.create(
            label=label, file=SimpleUploadedFile(f"{label}.txt", b"x")
        )
        if not actif:
            CV.objects.filter(pk=cv.pk).update(actif=False)
        return cv

    def test_form_ne_propose_que_les_cv_actifs(self):
        actif = self._make_cv("Actif")
        archive = self._make_cv("Archivé", actif=False)
        choices = list(CandidatureForm().fields["cv"].queryset)
        self.assertIn(actif, choices)
        self.assertNotIn(archive, choices)

    def test_form_conserve_le_cv_archive_deja_lie(self):
        archive = self._make_cv("Archivé", actif=False)
        cand = Candidature.objects.create(poste="Dev", cv=archive)
        self.assertIn(archive, list(CandidatureForm(instance=cand).fields["cv"].queryset))

    def test_creation_lie_le_cv(self):
        cv = self._make_cv()
        self.client.post(reverse("tracking:candidature_create"), {
            "poste": "Dev", "cv": cv.pk,
            "canal_envoi": "email", "statut": Statut.ENVOYEE,
        })
        self.assertEqual(Candidature.objects.get().cv, cv)

    def test_detail_candidature_affiche_le_cv(self):
        cv = self._make_cv("Mon CV")
        cand = Candidature.objects.create(poste="Dev", cv=cv)
        resp = self.client.get(reverse("tracking:candidature_detail", args=[cand.pk]))
        self.assertContains(resp, "Mon CV")

    def test_detail_cv_affiche_les_candidatures(self):
        cv = self._make_cv()
        Candidature.objects.create(entreprise="ACME", poste="Dev", cv=cv)
        resp = self.client.get(reverse("tracking:cv_detail", args=[cv.pk]))
        self.assertContains(resp, "Candidatures liées")
        self.assertContains(resp, "ACME — Dev")

    def test_supprimer_cv_delie_la_candidature(self):
        cv = self._make_cv()
        cand = Candidature.objects.create(poste="Dev", cv=cv)
        cv.delete()  # on_delete=SET_NULL
        cand.refresh_from_db()
        self.assertIsNone(cand.cv)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class LocalisationTrajetTests(TestCase):
    """Issue #52 — localisation des candidatures et CV par défaut."""

    def _make_cv(self, label="CV", **extra):
        cv = CV.objects.create(label=label, file=SimpleUploadedFile(f"{label}.txt", b"x"))
        if extra:
            CV.objects.filter(pk=cv.pk).update(**extra)
            cv.refresh_from_db()
        return cv

    def test_localisation_enregistree_sur_la_candidature(self):
        self.client.post(reverse("tracking:candidature_create"), {
            "poste": "Dev", "localisation": "Lyon",
            "canal_envoi": "email", "statut": Statut.ENVOYEE,
        })
        self.assertEqual(Candidature.objects.get().localisation, "Lyon")

    def test_un_seul_cv_par_defaut(self):
        a = self._make_cv("A")
        b = self._make_cv("B")
        a.set_as_default()
        b.set_as_default()
        a.refresh_from_db()
        self.assertFalse(a.par_defaut)
        self.assertTrue(b.par_defaut)
        self.assertEqual(CV.default(), b)

    def test_set_default_toggle_via_vue(self):
        cv = self._make_cv()
        self.client.post(reverse("tracking:cv_set_default", args=[cv.pk]))
        cv.refresh_from_db()
        self.assertTrue(cv.par_defaut)
        self.client.post(reverse("tracking:cv_set_default", args=[cv.pk]))
        cv.refresh_from_db()
        self.assertFalse(cv.par_defaut)

    def test_set_default_refuse_get(self):
        cv = self._make_cv()
        resp = self.client.get(reverse("tracking:cv_set_default", args=[cv.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_home_location_depuis_analyse(self):
        cv = self._make_cv(analysis={"coordonnees": {"adresse": "1 rue X, Paris"}})
        self.assertEqual(cv.home_location, "1 rue X, Paris")
        cv2 = self._make_cv("C2", analysis={"localisation": "Nantes"})
        self.assertEqual(cv2.home_location, "Nantes")

    def test_detail_affiche_carte_trajet_si_domicile(self):
        self._make_cv("Défaut", par_defaut=True, analysis={"localisation": "Paris"})
        cand = Candidature.objects.create(poste="Dev", localisation="Lyon")
        resp = self.client.get(reverse("tracking:candidature_detail", args=[cand.pk]))
        self.assertContains(resp, "Temps de trajet")
        self.assertContains(resp, "travelmode=transit")

    def test_api_enregistre_la_localisation(self):
        tok = ApiToken.objects.create(token=ApiToken.new_token())
        self.client.post(
            reverse("tracking:api_candidature_create"),
            data=json.dumps({"entreprise": "ACME", "localisation": "Lille"}),
            content_type="application/json",
            HTTP_X_API_TOKEN=tok.token,
        )
        self.assertEqual(Candidature.objects.get().localisation, "Lille")


class SourceSiteTests(TestCase):
    """Issue #52 — la source d'une candidature référence un site actif."""

    def test_form_source_propose_les_sites_actifs(self):
        actif, _ = JobSite.objects.get_or_create(name="LinkedIn", defaults={"actif": True})
        archive = JobSite.objects.create(name="VieuxSite", actif=False)
        qs = list(CandidatureForm().fields["source"].queryset)
        self.assertIn(actif, qs)
        self.assertNotIn(archive, qs)

    def test_form_conserve_la_source_desactivee(self):
        archive = JobSite.objects.create(name="VieuxSite", actif=False)
        cand = Candidature.objects.create(poste="Dev", source=archive)
        self.assertIn(archive, list(CandidatureForm(instance=cand).fields["source"].queryset))

    def test_creation_via_formulaire_lie_le_site_source(self):
        site, _ = JobSite.objects.get_or_create(name="LinkedIn")
        self.client.post(reverse("tracking:candidature_create"), {
            "poste": "Dev", "source": site.pk, "canal_envoi": "email",
            "statut": Statut.ENVOYEE,
        })
        self.assertEqual(Candidature.objects.get().source, site)

    def test_api_resout_la_source_par_code(self):
        site, _ = JobSite.objects.get_or_create(name="LinkedIn")
        tok = ApiToken.objects.create(token=ApiToken.new_token())
        self.client.post(
            reverse("tracking:api_candidature_create"),
            data=json.dumps({"entreprise": "ACME", "source": "linkedin"}),
            content_type="application/json",
            HTTP_X_API_TOKEN=tok.token,
        )
        self.assertEqual(Candidature.objects.get().source, site)

    def test_api_resout_la_source_par_domaine(self):
        site = JobSite.objects.create(name="MonJobBoard", url="https://jobs.example.fr/")
        tok = ApiToken.objects.create(token=ApiToken.new_token())
        self.client.post(
            reverse("tracking:api_candidature_create"),
            data=json.dumps({"entreprise": "ACME", "url": "https://www.jobs.example.fr/offre/42"}),
            content_type="application/json",
            HTTP_X_API_TOKEN=tok.token,
        )
        self.assertEqual(Candidature.objects.get().source, site)

    def test_liste_affiche_le_favicon_de_la_source(self):
        site, _ = JobSite.objects.get_or_create(name="LinkedIn")
        site.logo_url = "https://x/li.png"
        site.save()
        Candidature.objects.create(poste="Dev", source=site)
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "https://x/li.png")


class CandidatureArchiveListTests(TestCase):
    """Issue #52 — les candidatures à 100 % sont séparées dans une vue archivée."""

    def setUp(self):
        self.active = Candidature.objects.create(poste="Active")
        self.cloturee = Candidature.objects.create(
            poste="Close", motif_cloture=MotifCloture.POSTE_POURVU
        )
        self.acceptee = Candidature.objects.create(
            poste="Win", acceptation=True
        )

    def test_liste_active_exclut_les_100pct(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        libelles = [str(c) for c in resp.context["candidatures"]]
        self.assertEqual(libelles, ["Active"])
        self.assertEqual(resp.context["archived_count"], 2)

    def test_vue_archivee_montre_les_100pct(self):
        resp = self.client.get(reverse("tracking:candidature_list"), {"archivees": "1"})
        libelles = sorted(str(c) for c in resp.context["candidatures"])
        self.assertEqual(libelles, ["Close", "Win"])
        self.assertNotIn("Active", libelles)

    def test_bouton_archivees_present(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "Candidatures archivées")
        self.assertContains(resp, "archivees=1")


def io_bytes(data):
    """Petit helper : un flux binaire lisible pour simuler HTTPError.read()."""
    import io
    return io.BytesIO(data)


class SidebarTests(TestCase):
    """Issue #35 — sidebar rétractable, responsive, Options en bas."""

    def test_sidebar_structure(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, 'class="sidebar"')
        self.assertContains(resp, 'id="sidebar-toggle"')
        self.assertContains(resp, "sidebar-nav")
        # Tooltips en mode réduit : libellé porté par data-label.
        self.assertContains(resp, 'data-label="Candidatures"')

    def test_options_pinned_in_footer(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, "sidebar-foot")
        self.assertContains(resp, 'data-label="Options"')

    def test_active_link_marked(self):
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "nav-item active")

    def test_mobile_topbar_present(self):
        resp = self.client.get(reverse("tracking:candidature_list"))
        self.assertContains(resp, 'id="menu-btn"')
        self.assertContains(resp, 'id="sb-backdrop"')


class StatsAnimationTests(TestCase):
    """Issue #35 — hooks d'animation des graphiques de statistiques."""

    def test_chart_animation_hooks(self):
        li, _ = JobSite.objects.get_or_create(name="LinkedIn")
        Candidature.objects.create(poste="Dev", source=li, statut=Statut.ENVOYEE)
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "js-bar")
        self.assertContains(resp, "js-seg")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CVEditTests(TestCase):
    """Issue #61 — édition manuelle des sections de l'analyse d'un CV."""

    def _make_cv(self, **kwargs):
        return CV.objects.create(
            label="CV", file=SimpleUploadedFile("cv.txt", b"x"), **kwargs
        )

    def _post(self, cv, section, value):
        return self.client.post(
            reverse("tracking:cv_edit", args=[cv.pk, section]),
            {"value": json.dumps(value)},
        )

    def test_edition_section_experiences(self):
        cv = self._make_cv()
        resp = self._post(cv, "experiences", [{"poste": "Lead", "entreprise": "Acme"}])
        self.assertRedirects(resp, reverse("tracking:cv_detail", args=[cv.pk]))
        cv.refresh_from_db()
        self.assertTrue(cv.is_analyzed)
        self.assertEqual(len(cv.analysis["experiences"]), 1)

    def test_edition_section_profil(self):
        cv = self._make_cv()
        self._post(cv, "profil", {"titre_profil": "Dev", "localisation": "Lyon"})
        cv.refresh_from_db()
        self.assertEqual(cv.analysis["titre_profil"], "Dev")
        self.assertEqual(cv.analysis["localisation"], "Lyon")

    def test_edition_section_ne_touche_pas_les_autres(self):
        cv = self._make_cv(
            analysis={"titre_profil": "Dev", "competences": ["Python"]},
            analyzed_at=timezone.now(),
        )
        # On ne modifie que les langues : le reste doit être préservé.
        self._post(cv, "langues", ["Anglais"])
        cv.refresh_from_db()
        self.assertEqual(cv.analysis["langues"], ["Anglais"])
        self.assertEqual(cv.analysis["titre_profil"], "Dev")
        self.assertEqual(cv.analysis["competences"], ["Python"])

    def test_section_inconnue_404(self):
        cv = self._make_cv()
        resp = self.client.get(reverse("tracking:cv_edit", args=[cv.pk, "inexistante"]))
        self.assertEqual(resp.status_code, 404)

    def test_edition_marque_le_cv_analyse(self):
        cv = self._make_cv()
        self.assertFalse(cv.is_analyzed)
        self._post(cv, "profil", {"titre_profil": "X"})
        cv.refresh_from_db()
        self.assertIsNotNone(cv.analyzed_at)

    def test_json_invalide_n_ecrase_pas(self):
        cv = self._make_cv(
            analysis={"titre_profil": "Ancien"}, analyzed_at=timezone.now()
        )
        resp = self.client.post(
            reverse("tracking:cv_edit", args=[cv.pk, "profil"]),
            {"value": "{pas du json"},
        )
        self.assertEqual(resp.status_code, 200)
        cv.refresh_from_db()
        self.assertEqual(cv.analysis["titre_profil"], "Ancien")

    def test_page_edition_prefille_la_valeur(self):
        cv = self._make_cv(
            analysis={"titre_profil": "Dev Python"}, analyzed_at=timezone.now()
        )
        resp = self.client.get(reverse("tracking:cv_edit", args=[cv.pk, "profil"]))
        self.assertEqual(resp.status_code, 200)
        # La valeur courante est sérialisée pour pré-remplir l'éditeur JS.
        self.assertContains(resp, "Dev Python")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ReferenceTests(TestCase):
    """Issue #62 — références à fournir, rattachées à un CV."""

    def setUp(self):
        self.cv = CV.objects.create(
            label="CV",
            file=SimpleUploadedFile("cv.txt", b"x"),
            analysis={
                "experiences": [
                    {"poste": "Lead", "entreprise": "Acme"},
                    {"poste": "Dev", "entreprise": "Globex"},
                ]
            },
            analyzed_at=timezone.now(),
        )

    def test_creation_reference(self):
        resp = self.client.post(
            reverse("tracking:reference_create", args=[self.cv.pk]),
            {
                "nom": "Durand",
                "prenom": "Marie",
                "email": "marie@example.com",
                "experience_index": "0",
            },
        )
        self.assertRedirects(resp, reverse("tracking:cv_detail", args=[self.cv.pk]))
        ref = Reference.objects.get()
        self.assertEqual(ref.cv, self.cv)
        self.assertEqual(ref.experience_index, 0)
        self.assertEqual(ref.experience_label, "Lead · Acme")

    def test_reference_sans_experience(self):
        self.client.post(
            reverse("tracking:reference_create", args=[self.cv.pk]),
            {"nom": "Petit", "experience_index": ""},
        )
        ref = Reference.objects.get()
        self.assertIsNone(ref.experience_index)
        self.assertEqual(ref.experience_label, "")

    def test_experience_label_hors_borne(self):
        ref = Reference.objects.create(cv=self.cv, nom="X", experience_index=9)
        self.assertEqual(ref.experience_label, "")

    def test_modification_reference(self):
        ref = Reference.objects.create(cv=self.cv, nom="X")
        self.client.post(
            reverse("tracking:reference_update", args=[ref.pk]),
            {"nom": "Y", "experience_index": "1"},
        )
        ref.refresh_from_db()
        self.assertEqual(ref.nom, "Y")
        self.assertEqual(ref.experience_index, 1)

    def test_suppression_reference(self):
        ref = Reference.objects.create(cv=self.cv, nom="X")
        resp = self.client.post(reverse("tracking:reference_delete", args=[ref.pk]))
        self.assertRedirects(resp, reverse("tracking:cv_detail", args=[self.cv.pk]))
        self.assertEqual(Reference.objects.count(), 0)

    def test_suppression_refuse_get(self):
        ref = Reference.objects.create(cv=self.cv, nom="X")
        resp = self.client.get(reverse("tracking:reference_delete", args=[ref.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_reference_affichee_sur_la_fiche(self):
        Reference.objects.create(
            cv=self.cv, nom="Durand", prenom="Marie", experience_index=0
        )
        resp = self.client.get(reverse("tracking:cv_detail", args=[self.cv.pk]))
        self.assertContains(resp, "Marie Durand")
        self.assertContains(resp, "Lead · Acme")


class ContactDetailTests(TestCase):
    """Issue #63 — section « Contacts » et opportunités associées au détail."""

    def test_nav_et_liste_renommees_en_contacts(self):
        resp = self.client.get(reverse("tracking:site_list"))
        # Libellé de navigation et titre de page renommés.
        self.assertContains(resp, "Contacts")
        self.assertContains(resp, "+ Ajouter un contact")

    def test_liste_lie_vers_le_detail(self):
        site = JobSite.objects.create(name="Acme")
        resp = self.client.get(reverse("tracking:site_list"))
        self.assertContains(resp, reverse("tracking:site_detail", args=[site.pk]))

    def test_detail_liste_les_opportunites_associees(self):
        acme = JobSite.objects.create(name="Acme")
        autre = JobSite.objects.create(name="Globex")
        liee = Candidature.objects.create(poste="Dev", entreprise="Acme", source=acme)
        Candidature.objects.create(poste="Lead", entreprise="Globex", source=autre)
        resp = self.client.get(reverse("tracking:site_detail", args=[acme.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Opportunités associées")
        self.assertContains(resp, str(liee))
        # Une candidature d'un autre contact ne doit pas apparaître.
        self.assertNotContains(resp, "Lead")

    def test_detail_sans_opportunite(self):
        site = JobSite.objects.create(name="Acme")
        resp = self.client.get(reverse("tracking:site_detail", args=[site.pk]))
        self.assertContains(resp, "Aucune opportunité associée")

    def test_message_creation_parle_de_contact(self):
        resp = self.client.post(
            reverse("tracking:site_create"), {"name": "Nouveau"}, follow=True
        )
        self.assertContains(resp, "Contact ajouté.")
