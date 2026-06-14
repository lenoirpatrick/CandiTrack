# CLAUDE.md

Guide pour travailler sur CandiTrack. Langue du projet : **français** (libellés,
commentaires, messages de commit).

## Stack

- **Django 6.0.1** / **Python 3.14**, base **SQLite**.
- Projet `canditrack/`, application unique `tracking/`.
- Templates avec **CSS inline** dans `templates/base.html` (pas de dossier
  `static/` source) ; thème clair/sombre via variables CSS + attribut
  `data-theme` (voir `docs/palette.md`).
- Mise en page : **sidebar latérale rétractable** (issue #35) — état desktop
  `data-sidebar="expanded|collapsed"` sur `<html>` (persisté dans localStorage,
  pré-appliqué en `<head>` anti-flash), tiroir mobile via `.sidebar-open` +
  bouton `#menu-btn`. L'entrée Options est épinglée en bas (`.sidebar-foot`).
  Variables `--radius`, `--shadow*`, `--sidebar-*` pour le style corporate.
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
`Reminder`, `Interview`, `Contact`, `ApiToken`, `CV`, `AIConfig` (singleton de
config du coaching IA, clé Gemini chiffrée — issue #33). Énumérations
`TextChoices` : `Source`, `Canal`, `Statut`, `MotifCloture` (certaines avec icône
emoji dans le libellé pour les menus).

- Seed des sites par défaut : migrations `0002_seed_jobsites` et
  `0010_seed_known_jobsites` (idempotentes, `get_or_create`).
- Logos dérivés du favicon : `tracking/logos.py` (`favicon_service_url`, stdlib
  uniquement) ; chargé par défaut à l'enregistrement d'un site (issue #27).
- Géométrie du donut de stats : `tracking/statistics.py`.
- Coaching IA (issues #33, #34, #39) : `tracking/ai.py` (clients REST stdlib pour
  **Gemini, Mistral, OpenAI/ChatGPT, Anthropic/Claude, Perplexity** ;
  `generate(..., provider=...)` aiguille — OpenAI/Mistral/Perplexity partagent le
  format « chat completions », Anthropic a l'API Messages) + `tracking/coaching.py`
  (collecte du contexte CV/stats et prompts ; le CV n'est joint que pour Gemini).
  `AIConfig` garde une clé + un modèle + une limite **par fournisseur** (champs
  `<provider>_api_key/_model/_monthly_limit`, accès générique par getattr), le
  `provider` actif détermine `api_key`/`model`. `MODELS_BY_PROVIDER`, `DEFAULTS`
  et `PROVIDER_INFO` (tier gratuit + liens doc/clé) pilotent l'UI. Config via `/aide/` (page Options,
  catégorie IA, issue #34). Endpoints POST AJAX `api/coaching/` (bilan) et
  `api/candidatures/<pk>/relance/` (mail de relance) ; UI = modal partagé
  `#ai-modal` dans `base.html` (spinner + rendu Markdown).
- Quotas IA (issue #36) : `ai.generate` renvoie un `GenerationResult` (texte +
  tokens) ; `coaching._run` journalise chaque appel dans `AIUsage`. `AIConfig`
  porte une limite mensuelle de tokens par fournisseur (0 = illimitée) ; la
  conso du mois et l'avertissement de dépassement (souple, sans blocage) sont
  calculés côté vue (`_ai_usage_context`, `_quota_warning`).

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
