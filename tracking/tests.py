import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import CVForm
from .models import (
    ApiToken,
    Canal,
    Candidature,
    JobSite,
    MotifCloture,
    Source,
    Statut,
)
from .statistics import compute_stats


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
        self.assertContains(resp, "Installer l'extension")

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
