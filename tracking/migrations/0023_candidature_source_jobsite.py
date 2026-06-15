"""Source d'une candidature : énumération figée -> référence à un JobSite (issue #52).

L'ancien champ ``source`` (CharField, énumération France Travail/APEC/LinkedIn…)
est converti en clé étrangère vers :class:`JobSite`, ce qui permet de proposer
tous les sites actifs (y compris personnalisés) et d'afficher leur favicon.

La conversion mappe chaque ancienne valeur d'énumération vers le site par défaut
de même nom ; ``autre`` (et toute valeur sans site correspondant) devient ``NULL``.
"""

from django.db import migrations, models
import django.db.models.deletion

# Ancienne valeur d'énumération -> nom du JobSite par défaut équivalent.
SOURCE_TO_SITE = {
    "france_travail": "France Travail",
    "apec": "APEC",
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "monster": "Monster",
    "cadremploi": "Cadremploi",
}


def forwards(apps, schema_editor):
    Candidature = apps.get_model("tracking", "Candidature")
    JobSite = apps.get_model("tracking", "JobSite")
    sites = {s.name: s for s in JobSite.objects.all()}
    for cand in Candidature.objects.all():
        name = SOURCE_TO_SITE.get(cand.source)
        site = sites.get(name) if name else None
        if site is not None:
            cand.source_site_id = site.pk
            cand.save(update_fields=["source_site"])


def backwards(apps, schema_editor):
    # Conversion irréversible des sites personnalisés : on rétablit au mieux.
    Candidature = apps.get_model("tracking", "Candidature")
    name_to_source = {v: k for k, v in SOURCE_TO_SITE.items()}
    for cand in Candidature.objects.all():
        site = cand.source_site
        cand.source = name_to_source.get(site.name, "autre") if site else "autre"
        cand.save(update_fields=["source"])


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0022_candidature_localisation_cv_par_defaut"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidature",
            name="source_site",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="source_candidatures",
                to="tracking.jobsite",
                verbose_name="source",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name="candidature",
            name="source",
        ),
        migrations.RenameField(
            model_name="candidature",
            old_name="source_site",
            new_name="source",
        ),
    ]
