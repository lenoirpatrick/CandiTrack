"""Ajout du fournisseur Mistral à la config IA (issue #34).

Renomme les champs Gemini existants (clé + modèle) et ajoute le fournisseur
actif ainsi que la clé et le modèle Mistral. Écrit à la main pour préserver la
clé Gemini déjà saisie (renommage plutôt que suppression/recréation).
"""

import tracking.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0014_alter_aiconfig_model"),
    ]

    operations = [
        migrations.RenameField(
            model_name="aiconfig", old_name="api_key", new_name="gemini_api_key"
        ),
        migrations.RenameField(
            model_name="aiconfig", old_name="model", new_name="gemini_model"
        ),
        migrations.AlterField(
            model_name="aiconfig",
            name="gemini_model",
            field=models.CharField(
                choices=[
                    ("gemini-2.5-flash", "Gemini 2.5 Flash — rapide et économique (recommandé)"),
                    ("gemini-2.5-pro", "Gemini 2.5 Pro — plus puissant"),
                    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite — le plus rapide"),
                    ("gemini-2.0-flash", "Gemini 2.0 Flash"),
                ],
                default="gemini-2.5-flash",
                max_length=100,
                verbose_name="modèle Gemini",
            ),
        ),
        migrations.AddField(
            model_name="aiconfig",
            name="provider",
            field=models.CharField(
                choices=[("gemini", "🔵 Google Gemini"), ("mistral", "🟠 Mistral AI")],
                default="gemini",
                max_length=10,
                verbose_name="fournisseur",
            ),
        ),
        migrations.AddField(
            model_name="aiconfig",
            name="mistral_api_key",
            field=tracking.fields.EncryptedCharField(
                blank=True, default="", verbose_name="clé API Mistral"
            ),
        ),
        migrations.AddField(
            model_name="aiconfig",
            name="mistral_model",
            field=models.CharField(
                choices=[
                    ("mistral-small-latest", "Mistral Small — rapide et économique (recommandé)"),
                    ("mistral-large-latest", "Mistral Large — le plus puissant"),
                    ("open-mistral-nemo", "Open Mistral Nemo"),
                ],
                default="mistral-small-latest",
                max_length=100,
                verbose_name="modèle Mistral",
            ),
        ),
    ]
