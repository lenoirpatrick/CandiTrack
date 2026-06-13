import os

from django import forms

from .logos import favicon_service_url
from .models import CV, Candidature, JobSite


class CandidatureForm(forms.ModelForm):
    class Meta:
        model = Candidature
        fields = [
            "libelle",
            "entreprise",
            "poste",
            "site",
            "source",
            "url_offre",
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
            "libelle": forms.TextInput(
                attrs={"placeholder": "Laisser vide : généré depuis entreprise et poste"}
            ),
            "date_envoi": forms.DateInput(attrs={"type": "date"}),
            "date_entretien_1": forms.DateInput(attrs={"type": "date"}),
            "date_entretien_2": forms.DateInput(attrs={"type": "date"}),
            "date_entretien_3": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ne proposer que les sites actifs (issue #22), mais conserver le site
        # déjà associé à la candidature même s'il a été désactivé depuis.
        qs = JobSite.objects.filter(actif=True)
        current = getattr(self.instance, "site_id", None)
        if current:
            qs = (qs | JobSite.objects.filter(pk=current)).distinct()
        self.fields["site"].queryset = qs

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Auto-remplir le libellé si laissé vide (issue #3).
        # L'entreprise est facultative ; on compose avec ce qui est disponible.
        if not instance.libelle:
            parts = [p for p in (instance.entreprise, instance.poste) if p]
            instance.libelle = " — ".join(parts) or "Candidature"
        if commit:
            instance.save()
        return instance


class JobSiteForm(forms.ModelForm):
    """Manual create/edit form for a job site (issue #366).

    - The password is never pre-filled; leaving it blank on edit keeps the
      stored (encrypted) value.
    - When ``auto_logo`` is checked the logo is (re)fetched from the URL.
    """

    password = forms.CharField(
        label="Mot de passe",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Laisser vide pour conserver le mot de passe actuel.",
    )
    class Meta:
        model = JobSite
        fields = ["name", "url", "username", "password", "logo_url"]
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://www.exemple.fr/"}),
            "logo_url": forms.URLInput(
                attrs={"placeholder": "Laisser vide pour utiliser le favicon du site"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Capture the current (decrypted) password so a blank submission keeps it.
        self._original_password = self.instance.password if self.instance.pk else ""

    def save(self, commit=True):
        instance = super().save(commit=False)

        if not self.cleaned_data.get("password"):
            instance.password = self._original_password

        # Logo par défaut : le favicon du site (issue #27). On ne l'impose que si
        # l'utilisateur n'a pas saisi de logo manuel.
        if not instance.logo_url and instance.url:
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
