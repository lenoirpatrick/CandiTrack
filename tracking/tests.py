import json
import urllib.error
from unittest import mock

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from . import ai
from .forms import CandidatureForm, CVForm, JobSiteForm
from .models import (
    AIConfig,
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


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class AIConfigViewTests(TestCase):
    """Issue #33 — enregistrement / suppression de la config depuis l'aide."""

    def test_help_page_shows_ai_section(self):
        resp = self.client.get(reverse("tracking:help"))
        self.assertContains(resp, "Coaching IA")
        self.assertContains(resp, "Clé API Gemini")

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

    @mock.patch("tracking.coaching.ai.generate", return_value="## Conseil\nFonce.")
    def test_returns_generated_text(self, gen):
        self._configure()
        resp = self.client.post(reverse("tracking:ai_coaching"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertIn("Conseil", resp.json()["text"])
        self.assertTrue(gen.called)

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

    @mock.patch("tracking.coaching.ai.generate", return_value="Objet : relance\n…")
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
    def test_extracts_text(self, urlopen):
        urlopen.return_value = self._response(
            {"candidates": [{"content": {"parts": [{"text": "Bonjour"}]}}]}
        )
        out = ai.generate("hi", api_key="k", model="m")
        self.assertEqual(out, "Bonjour")

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


class MistralClientTests(TestCase):
    """Issue #34 — client HTTP Mistral (parsing et aiguillage), réseau simulé."""

    def _response(self, payload):
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return cm

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_extracts_message_content(self, urlopen):
        urlopen.return_value = self._response(
            {"choices": [{"message": {"content": "Salut"}}]}
        )
        out = ai.generate("hi", api_key="k", model="mistral-small-latest", provider="mistral")
        self.assertEqual(out, "Salut")
        # L'URL appelée est bien celle de Mistral.
        called_url = urlopen.call_args.args[0].full_url
        self.assertIn("api.mistral.ai", called_url)

    @mock.patch("tracking.ai.urllib.request.urlopen")
    def test_empty_choices_raise(self, urlopen):
        urlopen.return_value = self._response({"choices": []})
        with self.assertRaises(ai.AIError):
            ai.generate("hi", api_key="k", model="m", provider="mistral")


@override_settings(CANDITRACK_FERNET_KEY=TEST_FERNET_KEY)
class CoachingProviderTests(TestCase):
    """Issue #34 — le fournisseur configuré est transmis au client IA."""

    @mock.patch("tracking.ai.generate", return_value="ok")
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


def io_bytes(data):
    """Petit helper : un flux binaire lisible pour simuler HTTPError.read()."""
    import io
    return io.BytesIO(data)
