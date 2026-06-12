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


class MotifCloture(models.TextChoices):
    """Reason a candidature is closed/finished (issue #5)."""

    POSTE_POURVU = "poste_pourvu", "Poste pourvu"
    PAS_QUALIFIE = "pas_qualifie", "Pas assez qualifié"
    REFUS_CANDIDAT = "refus_candidat", "Refus candidat"
    NON_ADEQUATION = "non_adequation", "Non adéquation du poste"
    REFUS_SALAIRE = "refus_salaire", "Refus salaire"


class Candidature(models.Model):
    """A single job application and its current state (issue #365)."""

    libelle = models.CharField("libellé", max_length=200, blank=True)
    entreprise = models.CharField("entreprise", max_length=200, blank=True)
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
    date_envoi = models.DateField(
        "date d'envoi", default=timezone.localdate, null=True, blank=True
    )
    canal_envoi = models.CharField(
        "canal d'envoi", max_length=20, choices=Canal.choices, default=Canal.EMAIL
    )
    statut = models.CharField(
        "statut", max_length=20, choices=Statut.choices, default=Statut.ENVOYEE
    )
    notes = models.TextField("notes", blank=True)

    # Étapes d'avancement (issue #3) — la barre de progression en découle.
    envoyee = models.BooleanField("candidature envoyée", default=False)
    traitee = models.BooleanField("candidature traitée", default=False)
    entretien_programme = models.BooleanField("entretien programmé", default=False)
    date_entretien_1 = models.DateField("date entretien 1", null=True, blank=True)
    date_entretien_2 = models.DateField("date entretien 2", null=True, blank=True)
    date_entretien_3 = models.DateField("date entretien 3", null=True, blank=True)
    offre_soumise = models.BooleanField("offre soumise", default=False)
    salaire_propose = models.CharField("salaire proposé", max_length=100, blank=True)
    acceptation = models.BooleanField("acceptation", default=False)

    # Clôture de la candidature (issue #5) : un motif renseigné = terminée.
    motif_cloture = models.CharField(
        "motif de clôture", max_length=20, choices=MotifCloture.choices, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Étapes ordonnées de la candidature, pour la barre de progression (issue #3).
    PROGRESS_STEPS = [
        ("envoyee", "Envoyée"),
        ("traitee", "Traitée"),
        ("entretien_programme", "Entretien programmé"),
        ("offre_soumise", "Offre soumise"),
        ("acceptation", "Acceptation"),
    ]

    class Meta:
        verbose_name = "candidature"
        verbose_name_plural = "candidatures"
        ordering = ["-date_envoi", "-created_at"]

    def __str__(self):
        return self.libelle or f"{self.entreprise} — {self.poste}"

    def get_absolute_url(self):
        return reverse("tracking:candidature_detail", args=[self.pk])

    @property
    def est_terminee(self):
        """A closed candidature has a closing reason set (issue #5)."""
        return bool(self.motif_cloture)

    def progression(self):
        """Progress across milestones (issue #3).

        A closed candidature is shown at 100% regardless of the current
        step (issue #5).
        """
        steps = [
            {"label": label, "done": bool(getattr(self, field))}
            for field, label in self.PROGRESS_STEPS
        ]
        done = sum(1 for s in steps if s["done"])
        total = len(steps)
        closed = self.est_terminee
        return {
            "steps": steps,
            "done": done,
            "total": total,
            "percent": 100 if closed else (round(100 * done / total) if total else 0),
            "closed": closed,
            "motif": self.get_motif_cloture_display() if closed else "",
        }


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
