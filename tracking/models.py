"""Data models for CandiTrack.

The schema anticipates the four board issues:
- #365 master plan: Candidature, StatusHistory, Reminder, Interview, Contact
- #366 job sites:   JobSite (with an encrypted password)
- #367 statistics:  built on top of Candidature aggregates
- #368 CV upload:   CV
"""

from django.db import models
from django.urls import reverse
from django.utils import timezone

from .fields import EncryptedCharField


class JobSite(models.Model):
    """A job board where applications are submitted (issue #366).

    Credentials are optional; when a password is provided it is stored
    encrypted at rest via :class:`EncryptedCharField`.
    """

    name = models.CharField("nom", max_length=100, unique=True)
    url = models.URLField("URL", blank=True)
    username = models.CharField("identifiant", max_length=200, blank=True)
    password = EncryptedCharField("mot de passe", blank=True, default="")
    logo_url = models.URLField("URL du logo", blank=True)
    is_builtin = models.BooleanField("site par défaut", default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site d'emploi"
        verbose_name_plural = "sites d'emploi"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Source(models.TextChoices):
    FRANCE_TRAVAIL = "france_travail", "France Travail"
    APEC = "apec", "APEC"
    LINKEDIN = "linkedin", "LinkedIn"
    INDEED = "indeed", "Indeed"
    MONSTER = "monster", "Monster"
    CADREMPLOI = "cadremploi", "Cadremploi"
    AUTRE = "autre", "Autre"


class Canal(models.TextChoices):
    EMAIL = "email", "Email direct"
    FORMULAIRE = "formulaire", "Formulaire site"
    EASY_APPLY = "easy_apply", "LinkedIn Easy Apply"
    COOPTATION = "cooptation", "Cooptation"
    AUTRE = "autre", "Autre"


class Statut(models.TextChoices):
    ENVOYEE = "envoyee", "Envoyée"
    RELANCEE = "relancee", "Relancée"
    ENTRETIEN_PLANIFIE = "entretien_planifie", "Entretien planifié"
    ENTRETIEN_PASSE = "entretien_passe", "Entretien passé"
    REFUS = "refus", "Refus"
    OFFRE = "offre", "Offre reçue"
    SANS_REPONSE = "sans_reponse", "Sans réponse"
    ABANDONNEE = "abandonnee", "Abandonnée"


class Candidature(models.Model):
    """A single job application and its current state (issue #365)."""

    entreprise = models.CharField("entreprise", max_length=200)
    poste = models.CharField("poste", max_length=200)
    site = models.ForeignKey(
        JobSite,
        verbose_name="site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidatures",
    )
    source = models.CharField(
        "source", max_length=20, choices=Source.choices, default=Source.AUTRE
    )
    url_offre = models.URLField("URL de l'offre", blank=True)
    date_envoi = models.DateField("date d'envoi", default=timezone.localdate)
    canal_envoi = models.CharField(
        "canal d'envoi", max_length=20, choices=Canal.choices, default=Canal.EMAIL
    )
    statut = models.CharField(
        "statut", max_length=20, choices=Statut.choices, default=Statut.ENVOYEE
    )
    notes = models.TextField("notes", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "candidature"
        verbose_name_plural = "candidatures"
        ordering = ["-date_envoi", "-created_at"]

    def __str__(self):
        return f"{self.entreprise} — {self.poste}"

    def get_absolute_url(self):
        return reverse("tracking:candidature_detail", args=[self.pk])


class StatusHistory(models.Model):
    """Audit trail of status changes for a candidature (issue #365)."""

    candidature = models.ForeignKey(
        Candidature,
        verbose_name="candidature",
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    statut = models.CharField("statut", max_length=20, choices=Statut.choices)
    date = models.DateTimeField("date", default=timezone.now)

    class Meta:
        verbose_name = "historique de statut"
        verbose_name_plural = "historiques de statut"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.candidature} → {self.get_statut_display()} ({self.date:%Y-%m-%d})"


class Reminder(models.Model):
    """A reminder to follow up on a candidature (issue #365 — stub for now)."""

    candidature = models.ForeignKey(
        Candidature,
        verbose_name="candidature",
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    date_prevue = models.DateField("date prévue")
    effectuee = models.BooleanField("effectuée", default=False)
    note = models.CharField("note", max_length=255, blank=True)

    class Meta:
        verbose_name = "relance"
        verbose_name_plural = "relances"
        ordering = ["date_prevue"]

    def __str__(self):
        return f"Relance {self.candidature} le {self.date_prevue:%Y-%m-%d}"


class Interview(models.Model):
    """An interview tied to a candidature (issue #365 — stub for now)."""

    class Type(models.TextChoices):
        TELEPHONE = "telephone", "Téléphone"
        VISIO = "visio", "Visio"
        PRESENTIEL = "presentiel", "Présentiel"

    candidature = models.ForeignKey(
        Candidature,
        verbose_name="candidature",
        on_delete=models.CASCADE,
        related_name="interviews",
    )
    date = models.DateTimeField("date")
    type = models.CharField(
        "type", max_length=20, choices=Type.choices, default=Type.VISIO
    )
    notes = models.TextField("notes", blank=True)

    class Meta:
        verbose_name = "entretien"
        verbose_name_plural = "entretiens"
        ordering = ["date"]

    def __str__(self):
        return f"Entretien {self.candidature} ({self.date:%Y-%m-%d %H:%M})"


class Contact(models.Model):
    """A recruiter / HR contact (issue #365 référentiel)."""

    nom = models.CharField("nom", max_length=200)
    email = models.EmailField("email", blank=True)
    entreprise = models.CharField("entreprise", max_length=200, blank=True)
    notes = models.TextField("notes", blank=True)

    class Meta:
        verbose_name = "contact"
        verbose_name_plural = "contacts"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


def cv_upload_path(instance, filename):
    return f"cv/{filename}"


class CV(models.Model):
    """An uploaded CV (issue #368). Reformatting/import is a later iteration."""

    label = models.CharField("libellé", max_length=200)
    file = models.FileField("fichier", upload_to=cv_upload_path)
    uploaded_at = models.DateTimeField("ajouté le", auto_now_add=True)

    class Meta:
        verbose_name = "CV"
        verbose_name_plural = "CV"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.label
