from django import forms

from .models import Candidature


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
