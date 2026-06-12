"""Give the default job sites a logo derived from their URL (issue #366).

Uses the deterministic favicon-service URL (no network call during migration);
users can re-fetch a richer logo from the UI afterwards.
"""

from django.db import migrations

from tracking.logos import favicon_service_url


def set_logos(apps, schema_editor):
    JobSite = apps.get_model("tracking", "JobSite")
    for site in JobSite.objects.filter(is_builtin=True):
        if site.url and not site.logo_url:
            site.logo_url = favicon_service_url(site.url)
            site.save(update_fields=["logo_url"])


def clear_logos(apps, schema_editor):
    JobSite = apps.get_model("tracking", "JobSite")
    for site in JobSite.objects.filter(is_builtin=True):
        if site.logo_url and "s2/favicons" in site.logo_url:
            site.logo_url = ""
            site.save(update_fields=["logo_url"])


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0002_seed_jobsites"),
    ]

    operations = [
        migrations.RunPython(set_logos, clear_logos),
    ]
