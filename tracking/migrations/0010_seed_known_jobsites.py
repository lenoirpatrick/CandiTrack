"""Élargir la base de sites par défaut pour un déploiement (issue #16).

Complète le seed initial (issue #366) avec les principaux sites de
candidature connus du marché français et les majeurs internationaux, afin
qu'une instance fraîchement déployée parte avec un référentiel utilisable.

Idempotent : ``get_or_create`` sur le nom, donc relancer la migration ou la
cumuler avec ``0002_seed_jobsites`` ne crée aucun doublon. Le logo est dérivé
de l'URL via le service de favicon (aucun appel réseau pendant la migration),
comme en ``0003_builtin_site_logos`` ; l'utilisateur peut le réactualiser
depuis l'interface ensuite.
"""

from django.db import migrations

from tracking.logos import favicon_service_url

# Sites de candidature connus. Ceux déjà présents (Cadremploi, Monster,
# LinkedIn, Indeed) ne sont pas répétés ici : get_or_create les ignorerait,
# mais autant garder la liste lisible.
KNOWN_SITES = [
    # Marché français — institutionnels et cadres
    {"name": "France Travail", "url": "https://candidat.francetravail.fr/"},
    {"name": "APEC", "url": "https://www.apec.fr/"},
    # Marché français — généralistes
    {"name": "HelloWork", "url": "https://www.hellowork.com/"},
    {"name": "Welcome to the Jungle", "url": "https://www.welcometothejungle.com/"},
    {"name": "Meteojob", "url": "https://www.meteojob.com/"},
    {"name": "Jobijoba", "url": "https://www.jobijoba.com/"},
    {"name": "Keljob", "url": "https://www.keljob.com/"},
    {"name": "Talent.com", "url": "https://www.talent.com/"},
    # IT / freelance
    {"name": "Free-Work", "url": "https://www.free-work.com/fr"},
    {"name": "ChooseYourBoss", "url": "https://www.chooseyourboss.com/"},
    # Majeurs internationaux
    {"name": "Glassdoor", "url": "https://www.glassdoor.fr/"},
]


def create_known_sites(apps, schema_editor):
    JobSite = apps.get_model("tracking", "JobSite")
    for site in KNOWN_SITES:
        JobSite.objects.get_or_create(
            name=site["name"],
            defaults={
                "url": site["url"],
                "is_builtin": True,
                "logo_url": favicon_service_url(site["url"]),
            },
        )


def remove_known_sites(apps, schema_editor):
    JobSite = apps.get_model("tracking", "JobSite")
    JobSite.objects.filter(
        name__in=[s["name"] for s in KNOWN_SITES], is_builtin=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0009_alter_candidature_canal_envoi_and_more"),
    ]

    operations = [
        migrations.RunPython(create_known_sites, remove_known_sites),
    ]
