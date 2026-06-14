"""Data models for CandiTrack.

The schema anticipates the four board issues:
- #365 master plan: Candidature, StatusHistory, Reminder, Interview, Contact
- #366 job sites:   JobSite (name, URL, logo)
- #367 statistics:  built on top of Candidature aggregates
- #368 CV upload:   CV
"""

import secrets

from django.db import models
from django.urls import reverse
from django.utils import timezone

from .fields import EncryptedCharField

# Libellés factorisés pour éviter la duplication de littéraux (issue #29).
LIBELLE_VERBOSE = "libellé"
ENVOYEE_LABEL = "Envoyée"


class JobSite(models.Model):
    """A job board where applications are submitted (issue #366).

    Les identifiants/mots de passe ne sont plus stockés (issue #43) : on ne
    conserve que l'identité du site (nom, URL, logo) et son état.
    """

    name = models.CharField("nom", max_length=100, unique=True)
    url = models.URLField("URL", blank=True)
    logo_url = models.URLField("URL du logo", blank=True)
    is_builtin = models.BooleanField("site par défaut", default=False)
    # Un site désactivé reste en base mais n'est plus proposé pour de nouvelles
    # candidatures (issue #22) — utile pour masquer un site par défaut non voulu.
    actif = models.BooleanField("actif", default=True)

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
    # Une icône précède chaque libellé pour les menus déroulants (issue #14).
    EMAIL = "email", "✉️ Email direct"
    FORMULAIRE = "formulaire", "📝 Formulaire site"
    EASY_APPLY = "easy_apply", "⚡ LinkedIn Easy Apply"
    COOPTATION = "cooptation", "🤝 Cooptation"
    CONTACT_ENTRANT = "contact_entrant", "📞 Contact entrant (tél./mail)"
    RELATIONNEL = "relationnel", "👥 Relationnel"
    AUTRE = "autre", "🌐 Autre"


class Statut(models.TextChoices):
    ENVOYEE = "envoyee", ENVOYEE_LABEL
    RELANCEE = "relancee", "Relancée"
    ENTRETIEN_PLANIFIE = "entretien_planifie", "Entretien planifié"
    ENTRETIEN_PASSE = "entretien_passe", "Entretien passé"
    REFUS = "refus", "Refus"
    OFFRE = "offre", "Offre reçue"
    SANS_REPONSE = "sans_reponse", "Sans réponse"
    ABANDONNEE = "abandonnee", "Abandonnée"


class MotifCloture(models.TextChoices):
    """Reason a candidature is closed/finished (issue #5)."""

    # Une icône précède chaque libellé pour les menus déroulants (issue #14).
    POSTE_POURVU = "poste_pourvu", "🚫 Poste pourvu"
    PAS_QUALIFIE = "pas_qualifie", "📉 Pas assez qualifié"
    REFUS_CANDIDAT = "refus_candidat", "🙅 Refus candidat"
    NON_ADEQUATION = "non_adequation", "🧭 Non adéquation du poste"
    REFUS_SALAIRE = "refus_salaire", "💸 Refus salaire"
    PAS_DONNE_SUITE = "pas_donne_suite", "📭 Pas donné suite"


class Candidature(models.Model):
    """A single job application and its current state (issue #365)."""

    libelle = models.CharField(LIBELLE_VERBOSE, max_length=200, blank=True)
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
        ("envoyee", ENVOYEE_LABEL),
        ("traitee", "Traitée"),
        ("entretien_programme", "Entretien programmé"),
        ("offre_soumise", "Offre soumise"),
        ("acceptation", "Acceptation"),
    ]

    # Libellés courts pour la colonne « Statut » de la liste (issue #12).
    STEP_SHORT_LABELS = {
        "envoyee": ENVOYEE_LABEL,
        "traitee": "Traitée",
        "entretien_programme": "Entretien",
        "offre_soumise": "Offre",
        "acceptation": "Acceptation",
    }

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

    def etape_courante(self):
        """Short label of the furthest reached step, for the list (issue #12).

        Reflects the boolean progress steps rather than the raw ``statut``
        field, so the list updates as the candidature advances.
        """
        if self.est_terminee:
            return "Terminée"
        label = "Nouvelle"
        for field, _ in self.PROGRESS_STEPS:
            if getattr(self, field):
                label = self.STEP_SHORT_LABELS[field]
        return label

    def progression(self):
        """Progress across milestones (issue #3).

        A closed candidature is shown at 100% regardless of the current
        step (issue #5). The bar colour shifts from red to green as the
        candidature advances, and a closed one is forced to red (issue #10).
        """
        steps = [
            {"label": label, "done": bool(getattr(self, field))}
            for field, label in self.PROGRESS_STEPS
        ]
        done = sum(1 for s in steps if s["done"])
        total = len(steps)
        closed = self.est_terminee
        # Une acceptation est une réussite : barre pleine et verte (issue #23).
        accepted = bool(self.acceptation)
        if accepted:
            color = "hsl(120, 62%, 45%)"  # vert : offre acceptée
        elif closed:
            color = "#e0584b"  # rouge : process stoppé
        else:
            # Teinte de 0° (rouge) à 120° (vert) selon l'avancement.
            hue = round(120 * done / total) if total else 0
            color = f"hsl({hue}, 62%, 45%)"
        # Pourcentage affiché : 100 % si acceptée/clôturée, sinon proportionnel
        # à l'avancement (extraction du ternaire imbriqué, issue #29).
        if accepted or closed:
            percent = 100
        elif total:
            percent = round(100 * done / total)
        else:
            percent = 0
        return {
            "steps": steps,
            "done": done,
            "total": total,
            "percent": percent,
            "closed": closed,
            "accepted": accepted,
            "color": color,
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


class ApiToken(models.Model):
    """API token for the Chrome extension (issue #6).

    Lets an end-user generate / register a key from the help page, without
    needing access to the backend ``.env``. The extension endpoint accepts
    any stored token (and still the ``CANDITRACK_API_TOKEN`` setting, for
    backwards compatibility).
    """

    token = models.CharField("jeton", max_length=64, unique=True)
    label = models.CharField(LIBELLE_VERBOSE, max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "jeton API"
        verbose_name_plural = "jetons API"
        ordering = ["-created_at"]

    def __str__(self):
        return self.label or f"Jeton #{self.pk}"

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(32)


def cv_upload_path(instance, filename):
    return f"cv/{filename}"


class CV(models.Model):
    """An uploaded CV (issue #368). Reformatting/import is a later iteration."""

    label = models.CharField(LIBELLE_VERBOSE, max_length=200)
    file = models.FileField("fichier", upload_to=cv_upload_path)
    uploaded_at = models.DateTimeField("ajouté le", auto_now_add=True)

    class Meta:
        verbose_name = "CV"
        verbose_name_plural = "CV"
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.label


class AIConfig(models.Model):
    """Configuration du module de coaching IA (issues #33, #34, #39).

    Mono-utilisateur : une seule ligne (chargée via :meth:`load`). Cinq
    fournisseurs sont gérés (Gemini, Mistral, OpenAI/ChatGPT, Anthropic/Claude,
    Perplexity) : chacun garde sa propre clé (chiffrée au repos, comme les mots
    de passe des sites), son propre modèle et sa limite, ce qui permet de
    basculer de l'un à l'autre sans ressaisie. Le fournisseur actif (`provider`)
    détermine la clé, le modèle et la limite utilisés. L'accès par fournisseur se
    fait par convention de nom de champ (`<provider>_api_key`, etc.).
    """

    class Provider(models.TextChoices):
        GEMINI = "gemini", "🔵 Google Gemini"
        MISTRAL = "mistral", "🟠 Mistral AI"
        OPENAI = "openai", "🟢 OpenAI (ChatGPT)"
        ANTHROPIC = "anthropic", "🟣 Anthropic (Claude)"
        PERPLEXITY = "perplexity", "🔎 Perplexity"

    # Modèles proposés dans les menus déroulants par fournisseur.
    GEMINI_MODELS = [
        ("gemini-2.5-flash", "Gemini 2.5 Flash — rapide et économique (recommandé)"),
        ("gemini-2.5-pro", "Gemini 2.5 Pro — plus puissant"),
        ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite — le plus rapide"),
        ("gemini-2.0-flash", "Gemini 2.0 Flash"),
    ]
    MISTRAL_MODELS = [
        ("mistral-small-latest", "Mistral Small — rapide et économique (recommandé)"),
        ("mistral-large-latest", "Mistral Large — le plus puissant"),
        ("open-mistral-nemo", "Open Mistral Nemo"),
    ]
    OPENAI_MODELS = [
        ("gpt-4o-mini", "GPT-4o mini — rapide et économique (recommandé)"),
        ("gpt-4o", "GPT-4o — plus puissant"),
        ("gpt-4.1-mini", "GPT-4.1 mini"),
    ]
    ANTHROPIC_MODELS = [
        ("claude-haiku-4-5", "Claude Haiku 4.5 — rapide et économique (recommandé)"),
        ("claude-sonnet-4-6", "Claude Sonnet 4.6 — équilibré"),
        ("claude-opus-4-8", "Claude Opus 4.8 — le plus puissant"),
    ]
    PERPLEXITY_MODELS = [
        ("sonar", "Sonar — rapide (recommandé)"),
        ("sonar-pro", "Sonar Pro — plus puissant"),
    ]
    MODELS_BY_PROVIDER = {
        "gemini": GEMINI_MODELS,
        "mistral": MISTRAL_MODELS,
        "openai": OPENAI_MODELS,
        "anthropic": ANTHROPIC_MODELS,
        "perplexity": PERPLEXITY_MODELS,
    }
    DEFAULTS = {provider: models_list[0][0] for provider, models_list in MODELS_BY_PROVIDER.items()}
    # Compat historique (issue #33) : modèle par défaut = celui de Gemini.
    DEFAULT_GEMINI_MODEL = DEFAULTS["gemini"]
    DEFAULT_MISTRAL_MODEL = DEFAULTS["mistral"]
    DEFAULT_MODEL = DEFAULT_GEMINI_MODEL

    # Rappel des quotas du tier gratuit, doc officielle et page de clé (issues #38, #39).
    PROVIDER_INFO = {
        "gemini": {
            "free_tier": (
                "Tier gratuit (sans carte bancaire) : ~1 500 requêtes/jour, "
                "15 requêtes/min et 1M tokens/min, contexte jusqu'à 1M tokens "
                "selon le modèle."
            ),
            "doc_url": "https://ai.google.dev/gemini-api/docs/billing",
            "key_url": "https://aistudio.google.com/apikey",
        },
        "mistral": {
            "free_tier": (
                "« Free mode » activé par défaut : limites réduites et cap "
                "mensuel de tokens, pour évaluation/prototypage."
            ),
            "doc_url": "https://docs.mistral.ai/admin/user-management-finops/tier",
            "key_url": "https://console.mistral.ai/api-keys",
        },
        "openai": {
            "free_tier": (
                "Pas de tier gratuit permanent pour l'API (crédits d'essai "
                "uniquement) ; facturation à l'usage ensuite."
            ),
            "doc_url": "https://platform.openai.com/docs/guides/rate-limits",
            "key_url": "https://platform.openai.com/api-keys",
        },
        "anthropic": {
            "free_tier": (
                "Pas de tier gratuit permanent pour l'API (crédits d'essai "
                "limités) ; contexte ~200k tokens."
            ),
            "doc_url": "https://platform.claude.com/docs/en/api/rate-limits",
            "key_url": "https://console.anthropic.com/settings/keys",
        },
        "perplexity": {
            "free_tier": (
                "API payante (Sonar), pas de tier gratuit pérenne ; facturation "
                "à l'usage."
            ),
            "doc_url": "https://docs.perplexity.ai/",
            "key_url": "https://www.perplexity.ai/settings/api",
        },
    }

    provider = models.CharField(
        "fournisseur", max_length=10, choices=Provider.choices, default=Provider.GEMINI
    )
    gemini_api_key = EncryptedCharField("clé API Gemini", blank=True, default="")
    mistral_api_key = EncryptedCharField("clé API Mistral", blank=True, default="")
    openai_api_key = EncryptedCharField("clé API OpenAI", blank=True, default="")
    anthropic_api_key = EncryptedCharField("clé API Anthropic", blank=True, default="")
    perplexity_api_key = EncryptedCharField("clé API Perplexity", blank=True, default="")
    gemini_model = models.CharField(
        "modèle Gemini", max_length=100, choices=GEMINI_MODELS, default=DEFAULTS["gemini"]
    )
    mistral_model = models.CharField(
        "modèle Mistral", max_length=100, choices=MISTRAL_MODELS, default=DEFAULTS["mistral"]
    )
    openai_model = models.CharField(
        "modèle OpenAI", max_length=100, choices=OPENAI_MODELS, default=DEFAULTS["openai"]
    )
    anthropic_model = models.CharField(
        "modèle Anthropic", max_length=100, choices=ANTHROPIC_MODELS, default=DEFAULTS["anthropic"]
    )
    perplexity_model = models.CharField(
        "modèle Perplexity", max_length=100, choices=PERPLEXITY_MODELS, default=DEFAULTS["perplexity"]
    )
    # Limite mensuelle de tokens par fournisseur (0 = illimitée, issue #36).
    gemini_monthly_limit = models.PositiveIntegerField("limite mensuelle Gemini (tokens)", default=0)
    mistral_monthly_limit = models.PositiveIntegerField("limite mensuelle Mistral (tokens)", default=0)
    openai_monthly_limit = models.PositiveIntegerField("limite mensuelle OpenAI (tokens)", default=0)
    anthropic_monthly_limit = models.PositiveIntegerField("limite mensuelle Anthropic (tokens)", default=0)
    perplexity_monthly_limit = models.PositiveIntegerField("limite mensuelle Perplexity (tokens)", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuration IA"
        verbose_name_plural = "configuration IA"

    def __str__(self):
        return "Configuration IA"

    @classmethod
    def load(cls):
        """Renvoie l'unique configuration, en la créant au besoin (singleton)."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    @property
    def api_key(self):
        """Clé du fournisseur actif."""
        return getattr(self, f"{self.provider}_api_key")

    @property
    def model(self):
        """Modèle du fournisseur actif."""
        return getattr(self, f"{self.provider}_model")

    @property
    def monthly_limit(self):
        """Limite mensuelle de tokens du fournisseur actif (0 = illimitée)."""
        return getattr(self, f"{self.provider}_monthly_limit")

    @property
    def models_for_provider(self):
        """Liste de modèles proposés pour le fournisseur actif."""
        return self.MODELS_BY_PROVIDER[self.provider]

    @property
    def is_configured(self):
        """Vrai dès qu'une clé est renseignée pour le fournisseur actif."""
        return bool(self.api_key)

    @property
    def model_in_choices(self):
        """Vrai si le modèle actif figure dans le menu déroulant du fournisseur."""
        return self.model in dict(self.models_for_provider)


class AIUsage(models.Model):
    """Journal de consommation des appels IA, par fournisseur (issue #36).

    Une ligne par appel réussi : sert à calculer la consommation du mois
    courant (nombre d'appels et de tokens) et à la comparer à la limite
    mensuelle configurée dans :class:`AIConfig`.
    """

    provider = models.CharField(
        "fournisseur", max_length=10, choices=AIConfig.Provider.choices
    )
    model = models.CharField("modèle", max_length=100)
    prompt_tokens = models.PositiveIntegerField("tokens entrée", default=0)
    completion_tokens = models.PositiveIntegerField("tokens sortie", default=0)
    total_tokens = models.PositiveIntegerField("tokens total", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "consommation IA"
        verbose_name_plural = "consommations IA"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} — {self.total_tokens} tokens ({self.created_at:%Y-%m-%d})"

    @classmethod
    def record(cls, provider, model, result):
        """Enregistre la consommation d'un :class:`tracking.ai.GenerationResult`."""
        return cls.objects.create(
            provider=provider,
            model=model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        )

    @classmethod
    def month_summary(cls, provider, when=None):
        """Appels et tokens consommés par ``provider`` sur le mois de ``when``."""
        when = when or timezone.now()
        agg = cls.objects.filter(
            provider=provider,
            created_at__year=when.year,
            created_at__month=when.month,
        ).aggregate(calls=models.Count("id"), tokens=models.Sum("total_tokens"))
        return {"calls": agg["calls"] or 0, "tokens": agg["tokens"] or 0}
