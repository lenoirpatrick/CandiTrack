# CLAUDE.md

Guide pour travailler sur CandiTrack. Langue du projet : **français** (libellés,
commentaires, messages de commit).

## Stack

- **Django 6.0.1** / **Python 3.14**, base **SQLite**.
- Projet `canditrack/`, application unique `tracking/`.
- Templates avec **CSS inline** dans `templates/base.html` (pas de dossier
  `static/` source) ; thème clair/sombre via variables CSS + attribut
  `data-theme` (voir `docs/palette.md`).
- Aucune authentification sur les vues : l'application est mono-utilisateur.

## Configuration (`.env`)

Toute la config passe par un `.env` chargé via `python-dotenv` (jamais commité).
Partir de `.env.example`. Variables clés :

- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- `CANDITRACK_FERNET_KEY` — **obligatoire** : clé Fernet chiffrant les mots de
  passe des sites (`EncryptedCharField`, voir `tracking/fields.py`).
- `CANDITRACK_API_TOKEN` — jeton partagé pour l'extension Chrome.
- `SQLITE_PATH` — chemin de la base ; surchargé par `docker-compose` vers le
  volume persistant, vide en local (défaut `db.sqlite3` à la racine).

## Docker (mode de déploiement recommandé)

- `Dockerfile` — image prod `python:3.14-slim`, gunicorn, utilisateur non-root,
  statiques servis par **WhiteNoise** (`STATIC_ROOT`, storage compressé/manifest).
- `docker-entrypoint.sh` — `migrate` (applique aussi le seed des sites) puis
  `collectstatic`, avant de lancer gunicorn. Forcé en LF via `.gitattributes`.
- `docker-compose.yml` — port **53487**, volumes nommés `data` (base SQLite via
  `SQLITE_PATH=/app/data/db.sqlite3`) et `media`.
- `.github/workflows/docker-publish.yml` — CI qui publie sur Docker Hub **à la
  fermeture d'un milestone** (titre du milestone = version, tags `latest` +
  `<version>`). Requiert les secrets `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`.
- `.github/workflows/sonarqube.yml` — relecture **SonarQube Cloud** (issue #25) :
  tests + couverture (`coverage.xml`) puis analyse statique, sur `main` et PR.
  Config dans `sonar-project.properties`, requiert le secret `SONAR_TOKEN`.

```bash
docker compose up -d --build   # → http://127.0.0.1:53487/
```

## Modèles (`tracking/models.py`)

`JobSite` (mot de passe chiffré, `is_builtin`, `logo_url`), `Candidature` (cœur
du suivi, étapes de progression + `motif_cloture` = clôture), `StatusHistory`,
`Reminder`, `Interview`, `Contact`, `ApiToken`, `CV`. Énumérations `TextChoices` :
`Source`, `Canal`, `Statut`, `MotifCloture` (certaines avec icône emoji dans le
libellé pour les menus).

- Seed des sites par défaut : migrations `0002_seed_jobsites` et
  `0010_seed_known_jobsites` (idempotentes, `get_or_create`).
- Logos dérivés du favicon : `tracking/logos.py` (`favicon_service_url`, stdlib
  uniquement) ; chargé par défaut à l'enregistrement d'un site (issue #27).
- Géométrie du donut de stats : `tracking/statistics.py`.

## Extension Chrome (`chrome-extension/`)

Appelle `POST /api/candidatures/` avec le jeton dans l'en-tête `X-Api-Token`
(`tracking/views.py:api_candidature_create`). L'auth accepte un `ApiToken` stocké
en base **ou** `settings.CANDITRACK_API_TOKEN`. Jetons gérés depuis la page
`/aide/`.

## Commandes

```bash
python manage.py test tracking          # suite de tests (modèles, vues, stats)
python manage.py migrate                # migrations + seed des sites
python manage.py makemigrations --check # vérifier qu'aucune migration ne manque
```

## Conventions

- Workflow **piloté par les issues** : chaque commit référence `#N` ; fermer
  l'issue avec `gh issue close` en citant le commit.
- Ne pas committer `db.sqlite3`, `media/`, `staticfiles/`, `.env` (gitignorés).
- Commentaires concis en français, alignés sur le style existant.
