"""Seed the default job sites (issue #366)."""

from django.db import migrations

DEFAULT_SITES = [
    {"name": "Cadremploi", "url": "https://www.cadremploi.fr/"},
    {"name": "Monster", "url": "https://www.monster.fr/"},
    {"name": "LinkedIn", "url": "https://www.linkedin.com/jobs/"},
    {"name": "Indeed", "url": "https://fr.indeed.com/"},
]


def create_default_sites(apps, schema_editor):
    JobSite = apps.get_model("tracking", "JobSite")
    for site in DEFAULT_SITES:
        JobSite.objects.get_or_create(
            name=site["name"],
            defaults={"url": site["url"], "is_builtin": True},
        )


def remove_default_sites(apps, schema_editor):
    JobSite = apps.get_model("tracking", "JobSite")
    JobSite.objects.filter(
        name__in=[s["name"] for s in DEFAULT_SITES], is_builtin=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_sites, remove_default_sites),
    ]
