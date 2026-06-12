import os

from django import forms

from .logos import fetch_logo_url
from .models import CV, Candidature, JobSite


class CandidatureForm(forms.ModelForm):
    class Meta:
        model = Candidature
        fields = [
            "entreprise",
            "poste",
            "site",
            "source",
            "url_offre",
            "date_envoi",
            "canal_envoi",
            "statut",
            "notes",
        ]
        widgets = {
            "date_envoi": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


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
    auto_logo = forms.BooleanField(
        label="Récupérer le logo automatiquement depuis l'URL",
        required=False,
        initial=True,
    )

    class Meta:
        model = JobSite
        fields = ["name", "url", "username", "password", "logo_url"]
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://www.exemple.fr/"}),
            "logo_url": forms.URLInput(
                attrs={"placeholder": "Laisser vide pour auto-détection"}
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

        if self.cleaned_data.get("auto_logo") or not instance.logo_url:
            if instance.url:
                instance.logo_url = fetch_logo_url(instance.url)

        if commit:
            instance.save()
        return instance


class CVForm(forms.ModelForm):
    """Upload form for a CV (issue #368)."""

    ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt"}

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
        return f
