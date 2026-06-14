# CandiTrack

Suivi de candidatures — application web Django pour gérer le cycle de candidature
(envois, relances, entretiens, statistiques).

[![Publier l'image Docker](https://github.com/lenoirpatrick/CandiTrack/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/lenoirpatrick/CandiTrack/actions/workflows/docker-publish.yml)
[![SonarQube](https://github.com/lenoirpatrick/CandiTrack/actions/workflows/sonarqube.yml/badge.svg)](https://github.com/lenoirpatrick/CandiTrack/actions/workflows/sonarqube.yml)

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=bugs)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=coverage)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=lenoirpatrick_CandiTrack&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=lenoirpatrick_CandiTrack)

## Déploiement (Docker)

Le mode d'exécution recommandé est le conteneur Docker : image de production
(gunicorn + statiques servis par WhiteNoise), migrations et seed des sites
appliqués automatiquement au démarrage.

### 1. Configuration — fichier `.env`

Toute la configuration passe par un fichier `.env` (jamais commité). Partir du
modèle fourni :

```bash
cp .env.example .env
```

Puis renseigner les valeurs :

| Variable | Rôle |
|---|---|
| `SECRET_KEY` | Clé secrète Django — en générer une fraîche pour tout déploiement réel |
| `DEBUG` | `False` en production |
| `ALLOWED_HOSTS` | Hôtes autorisés (liste séparée par des virgules), requis si `DEBUG=False` |
| `CANDITRACK_FERNET_KEY` | Clé de chiffrement des mots de passe des sites (**obligatoire**) |
| `CANDITRACK_API_TOKEN` | Jeton partagé pour l'extension Chrome (issue #2) |
| `SQLITE_PATH` | Laisser vide : `docker-compose` le pointe vers le volume persistant |

Générer la clé Fernet :

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

…et un jeton pour l'extension :

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Lancement avec docker-compose

```bash
docker compose up -d --build
```

L'entrypoint applique les migrations (dont le seed des sites) et collecte les
statiques au démarrage. La base SQLite et les CV uploadés sont persistés dans
des volumes nommés (`data`, `media`), donc préservés entre les redémarrages.
L'application écoute sur le port **53487** → http://127.0.0.1:53487/

`docker-compose.yml` pointe `SQLITE_PATH` vers `/app/data/db.sqlite3` (volume
`data`) ; il n'y a donc rien à renseigner pour cette variable dans `.env`.

### Déploiement depuis l'image Docker Hub (sans build)

Sur la machine cible (ex. Raspberry Pi), inutile de cloner les sources ni de
construire l'image : `docker-compose.deploy.yml` tire directement l'image
publiée `plenoir/canditrack:latest`.

```bash
cp .env.example .env   # renseigner SECRET_KEY, CANDITRACK_FERNET_KEY,
                       # DEBUG=False et ALLOWED_HOSTS
docker compose -f docker-compose.deploy.yml pull
docker compose -f docker-compose.deploy.yml up -d
```

Mise à jour : relancer `pull` puis `up -d` (`pull_policy: always` récupère le
dernier `latest`). Mêmes volumes persistants (`data`, `media`) et port **53487**
que le compose de build.

> Sur ARM (Raspberry Pi), l'image tirée doit avoir été construite pour
> `linux/arm64` — la CI doit publier en multi-arch, sinon construire sur place
> avec `docker-compose.yml`.

### Sans docker-compose

```bash
docker build -t canditrack .
docker run -d -p 53487:53487 --env-file .env \
  -e SQLITE_PATH=/app/data/db.sqlite3 \
  -v canditrack-data:/app/data -v canditrack-media:/app/media canditrack
```

### Publication automatique de l'image (issue #18)

Le workflow `.github/workflows/docker-publish.yml` publie l'image sur Docker Hub
**à la fermeture d'un milestone** : le titre du milestone (ex. `1.0.0`) sert de
version. Le workflow rattache au passage les issues fermées sans milestone à
celui-ci, pousse l'image taguée `latest` et `<version>`, puis crée une
**release GitHub** du nom du milestone listant les issues traitées (l'archive
source est jointe automatiquement). L'historique des versions est aussi tenu
dans [CHANGELOG.md](CHANGELOG.md).

Configuration unique — `Settings → Secrets and variables → Actions` :

| Secret | Valeur |
|---|---|
| `DOCKERHUB_USERNAME` | identifiant Docker Hub (= namespace de l'image `…/canditrack`) |
| `DOCKERHUB_TOKEN` | access token Docker Hub (Account → Security → New Access Token) |

### Relecture SonarQube (issue #25)

Le workflow `.github/workflows/sonarqube.yml` lance la suite de tests avec
mesure de couverture (`coverage.xml`) puis l'analyse statique **SonarQube Cloud**
([sonarcloud.io](https://sonarcloud.io)) à chaque push sur `main`, sur les pull
requests et manuellement. La configuration de l'analyse (clé de projet,
organisation, exclusions, chemin du rapport de couverture) est dans
[`sonar-project.properties`](sonar-project.properties).

Configuration unique :

1. Importer le dépôt sur SonarQube Cloud (organisation `lenoirpatrick`, clé de
   projet `lenoirpatrick_CandiTrack`).
2. Désactiver *Automatic Analysis* côté SonarCloud (l'analyse est pilotée par la
   CI).
3. `Settings → Secrets and variables → Actions` → ajouter le secret :

| Secret | Valeur |
|---|---|
| `SONAR_TOKEN` | jeton SonarCloud (My Account → Security → Generate Tokens) |

## Développement local (sans Docker)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # renseigner au minimum CANDITRACK_FERNET_KEY

python manage.py migrate
python manage.py runserver
```

Puis ouvrir http://127.0.0.1:8000/ (port par défaut du serveur de développement).
Le fichier `.env`, la base `db.sqlite3`, les dossiers `media/` et `staticfiles/`
sont ignorés par Git.

## Extension Chrome (issue #2)

L'extension du dossier `chrome-extension/` permet d'ajouter l'offre de la page
courante à CandiTrack en un clic.

1. Renseigner `CANDITRACK_API_TOKEN` dans `.env` (voir tableau ci-dessus) puis
   (re)lancer l'application.
2. Dans Chrome : `chrome://extensions` → activer le **mode développeur** →
   **Charger l'extension non empaquetée** → choisir le dossier `chrome-extension/`.
3. Ouvrir les **options** de l'extension : renseigner l'URL du backend et coller
   le **jeton**.
4. Sur une page d'offre, cliquer l'icône CandiTrack : l'entreprise et l'URL
   sont pré-remplies (via les métadonnées JobPosting / Open Graph de la page),
   puis **Ajouter**. Le plugin ne renseigne pas le poste ni la date d'envoi
   (à compléter ensuite dans CandiTrack).

L'extension appelle `POST /api/candidatures/` en envoyant le jeton dans l'en-tête
`X-Api-Token`. L'URL du backend et le jeton se configurent dans les options de
l'extension ; l'hôte doit figurer dans les `host_permissions` du `manifest.json`.

## Coaching IA (issue #33)

CandiTrack peut générer un **coaching** et des **mails de relance** via l'IA
**Gemini** de Google. La fonctionnalité est désactivée par défaut : chacun
renseigne **sa propre clé API**.

1. Obtenir une clé sur [Google AI Studio](https://aistudio.google.com/apikey).
2. La coller dans la section **« Coaching IA »** de la page `/aide/` (et,
   facultativement, choisir le modèle — défaut `gemini-2.0-flash`). La clé est
   stockée **chiffrée** en base (Fernet, comme les mots de passe des sites) et
   n'est jamais réaffichée.
3. Depuis la liste des candidatures, **« ✨ Coaching IA »** ouvre une fenêtre
   modale : à partir du dernier CV chargé et des statistiques (volume, motifs de
   refus, délais…), l'IA propose un positionnement et des actions à réaliser.
4. Sur une candidature, **« ✉️ Mail de relance (IA) »** génère un brouillon de
   mail de relance, régénérable à volonté.

L'appel se fait en HTTP direct vers l'API Gemini (aucune dépendance ajoutée). La
clé n'est utilisée que pour les appels sortants vers Google ; vos crédits, vos
données.

## Pages

| URL | Rôle |
|---|---|
| `/` (`/candidatures/`) | Liste des candidatures (créer / modifier / consulter) |
| `/sites/` | Sites d'emploi : ajout, modification, suppression, logo (#366) |
| `/stats/` | Statistiques (#367 — premiers KPI) |
| `/cv/` | CV : chargement et suppression (#368) |
| `/aide/` | Aide, jetons de l'extension Chrome et configuration du coaching IA (#33) |

## Prochaines itérations

- #367 : KPI complets (taux de réponse par source, délais moyens, graphes)
- #368 : reformatage du CV (technique/pro) + import LinkedIn
- #365 : intégration API France Travail, rappels actifs et notifications
