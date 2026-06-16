import os

from django import forms

from .logos import favicon_service_url
from .models import CV, Candidature, JobSite, Reference


class CandidatureForm(forms.ModelForm):
    class Meta:
        model = Candidature
        fields = [
            "entreprise",
            "poste",
            "cv",
            "source",
            "url_offre",
            "localisation",
            "date_envoi",
            "canal_envoi",
            "statut",
            # Étapes d'avancement (issue #3)
            "envoyee",
            "traitee",
            "entretien_programme",
            "date_entretien_1",
            "date_entretien_2",
            "date_entretien_3",
            "offre_soumise",
            "salaire_propose",
            "acceptation",
            # Clôture (issue #5)
            "motif_cloture",
            "notes",
        ]
        widgets = {
            "localisation": forms.TextInput(
                attrs={"placeholder": "Ville ou zone géographique de l'offre"}
            ),
            # format ISO obligatoire : <input type="date"> n'affiche une valeur
            # existante que si elle est au format AAAA-MM-JJ (sinon le champ
            # paraît vide à l'édition, issue #3).
            "date_envoi": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_entretien_1": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_entretien_2": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_entretien_3": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On ne propose que les CV actifs (issue #48), tout en conservant celui
        # déjà lié à la candidature (issue #49).
        cv_qs = CV.objects.filter(actif=True)
        current_cv = getattr(self.instance, "cv_id", None)
        if current_cv:
            cv_qs = (cv_qs | CV.objects.filter(pk=current_cv)).distinct()
        self.fields["cv"].queryset = cv_qs

        # La source est le site d'emploi : seulement les sites actifs (issue #22),
        # en gardant la source courante même si désactivée depuis (issue #52).
        source_qs = JobSite.objects.filter(actif=True)
        current_source = getattr(self.instance, "source_id", None)
        if current_source:
            source_qs = (source_qs | JobSite.objects.filter(pk=current_source)).distinct()
        self.fields["source"].queryset = source_qs


class JobSiteForm(forms.ModelForm):
    """Manual create/edit form for a job site (issue #366).

    Les identifiants/mots de passe ne sont plus gérés (issue #43). Le logo n'est
    plus saisi : il est déduit automatiquement du favicon du site (issue #50).
    """

    class Meta:
        model = JobSite
        fields = ["name", "url", "type"]
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://www.exemple.fr/"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Type facultatif au formulaire : à défaut, le site est généraliste
        # (issue #55), comme les sites par défaut.
        self.fields["type"].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.type:
            instance.type = JobSite.Type.GENERALISTE

        # Logo dérivé automatiquement du favicon du site (issues #27, #50). On le
        # (re)calcule à la création, quand il manque, ou si l'URL a changé.
        if instance.url and (not instance.logo_url or "url" in self.changed_data):
            instance.logo_url = favicon_service_url(instance.url)

        if commit:
            instance.save()
        return instance


class CVForm(forms.ModelForm):
    """Upload form for a CV (issue #368)."""

    ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt"}
    # Taille maximale d'un CV : 5 Mo (issue #19).
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024

    class Meta:
        model = CV
        fields = ["label", "file"]
        widgets = {
            "label": forms.TextInput(
                attrs={"placeholder": "Ex. CV Développeur Backend 2026"}
            ),
        }

    def clean_file(self):
        f = self.cleaned_data["file"]
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(self.ALLOWED_EXTENSIONS))
            raise forms.ValidationError(
                f"Format non supporté ({ext or 'inconnu'}). Formats acceptés : {allowed}."
            )
        if f.size > self.MAX_UPLOAD_SIZE:
            limite = self.MAX_UPLOAD_SIZE // (1024 * 1024)
            actuel = f.size / (1024 * 1024)
            raise forms.ValidationError(
                f"Fichier trop volumineux ({actuel:.1f} Mo). Taille maximale : {limite} Mo."
            )
        return f


class ReferenceForm(forms.ModelForm):
    """Saisie d'une référence rattachée à un CV (issue #62).

    L'expérience associée est proposée dans une liste déroulante construite à
    partir des expériences analysées du CV (rang -> libellé).
    """

    class Meta:
        model = Reference
        fields = ["nom", "prenom", "telephone", "email", "linkedin", "experience_index"]
        widgets = {
            "telephone": forms.TextInput(attrs={"placeholder": "06 12 34 56 78"}),
            "linkedin": forms.URLInput(
                attrs={"placeholder": "https://www.linkedin.com/in/…"}
            ),
        }

    def __init__(self, *args, cv=None, **kwargs):
        super().__init__(*args, **kwargs)
        cv = cv or getattr(self.instance, "cv", None)
        experiences = (cv.analysis or {}).get("experiences") or [] if cv else []
        choices = [("", "— Aucune —")]
        for i, exp in enumerate(experiences):
            parts = [p for p in (exp.get("poste"), exp.get("entreprise")) if p]
            choices.append((str(i), " · ".join(parts) or f"Expérience {i + 1}"))
        # On remplace le champ entier par une liste déroulante des expériences,
        # tout en conservant un entier (ou None) côté modèle.
        self.fields["experience_index"] = forms.TypedChoiceField(
            label="Expérience associée",
            choices=choices,
            required=False,
            coerce=int,
            empty_value=None,
        )
