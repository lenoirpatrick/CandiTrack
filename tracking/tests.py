import json
import tempfile
import urllib.error
from unittest import mock

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from . import ai, coaching, cv_export, views
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
    Source,
    Statut,
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
            libelle="Alpha", entreprise="Alpha", poste="Backend",
            envoyee=True, traitee=True,
        )
        self.beta = Candidature.objects.create(
            libelle="Beta", entreprise="Beta", poste="Frontend",
        )
        self.zeta = Candidature.objects.create(
            libelle="Zeta", entreprise="Zeta", poste="DevOps",
            motif_cloture=MotifCloture.REFUS_CANDIDAT,
        )

    def test_search_filters(self):
        resp = self.client.get(reverse("tracking:candidature_list"), {"q": "beta"})
        self.assertContains(resp, "Beta")
        self.assertNotContains(resp, ">Alpha<")

    def test_closed_row_last_despite_sort(self):
        resp = self.client.get(
            reverse("tracking:candidature_list"), {"sort": "poste", "dir": "asc"}
        )
        order = list(resp.context["candidatures"])
        # Alpha/Beta sorted by poste; Zeta (closed) always last.
        self.assertEqual(order[-1], self.zeta)

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
                "poste": "Dev", "libelle": "Test", "source": Statut.ENVOYEE,
                "statut": Statut.ENVOYEE, "canal_envoi": "email",
                "source": "autre",
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
            libelle="L", entreprise="ACME", poste="Dev", source=Source.LINKEDIN
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
        Candidature.objects.create(poste="a", source=Source.LINKEDIN)
        Candidature.objects.create(poste="b", source=Source.LINKEDIN)
        Candidature.objects.create(poste="c", source=Source.INDEED)
        ctx = compute_stats()
        rows = ctx["by_source"]
        self.assertEqual(ctx["source_total"], 3)
        self.assertAlmostEqual(sum(r["percent"] for r in rows), 100, delta=0.5)
        for r in rows:
            self.assertTrue(r["color"].startswith("#"))
            self.assertAlmostEqual(r["dash"] + r["gap"], 100, delta=0.01)

    def test_stats_page_renders_svg(self):
        Candidature.objects.create(poste="a", source=Source.LINKEDIN)
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "<svg")
        self.assertContains(resp, "donut")
        self.assertContains(resp, "stroke-dasharray")


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
        qs = CandidatureForm().fields["site"].queryset
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

    def test_logo_manuel_respecte(self):
        form = JobSiteForm(data={
            "name": "Exemple",
            "url": "https://www.exemple.fr/",
            "logo_url": "https://cdn.exemple.fr/logo.png",
        })
        self.assertTrue(form.is_valid(), form.errors)
        site = form.save()
        self.assertEqual(site.logo_url, "https://cdn.exemple.fr/logo.png")

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
            "source": Source.AUTRE,
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
    """Issue #33 — endpoint de mail de relance IA."""

    def setUp(self):
        self.cand = Candidature.objects.create(entreprise="ACME", poste="Dev")
        config = AIConfig.load()
        config.gemini_api_key = "k"
        config.save()

    @mock.patch(
        "tracking.coaching.ai.generate",
        return_value=ai.GenerationResult("Objet : relance\n…", 5, 8, 13),
    )
    def test_returns_email(self, gen):
        resp = self.client.post(reverse("tracking:ai_relance", args=[self.cand.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("relance", resp.json()["text"])
        # Le prompt envoyé mentionne l'entreprise de la candidature.
        self.assertIn("ACME", gen.call_args.args[0])

    def test_unknown_candidature_404(self):
        resp = self.client.post(reverse("tracking:ai_relance", args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_detail_page_shows_relance_button(self):
        resp = self.client.get(
            reverse("tracking:candidature_detail", args=[self.cand.pk])
        )
        self.assertContains(resp, "Mail de relance (IA)")
        self.assertContains(resp, "openAiModal")


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
        Candidature.objects.create(poste="Dev", source=Source.LINKEDIN, statut=Statut.ENVOYEE)
        resp = self.client.get(reverse("tracking:stats"))
        self.assertContains(resp, "js-bar")
        self.assertContains(resp, "js-seg")
        self.assertContains(resp, "data-dash")
