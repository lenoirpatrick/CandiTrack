# CandiTrack

Suivi de candidatures — application web Django pour gérer le cycle de candidature
(envois, relances, entretiens, statistiques).

Cette première itération pose la **fondation** : gestion des candidatures opérationnelle,
et le schéma de données qui anticipe les fonctionnalités du board GitHub :

- **#365** — modèle de suivi (candidatures, historique de statut, relances, entretiens, contacts)
- **#366** — sites d'emploi avec mot de passe **chiffré au repos**
- **#367** — page de statistiques (premiers agrégats)
- **#368** — chargement de CV

## Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuration

Copier `.env.example` vers `.env` et renseigner les valeurs :

```bash
cp .env.example .env
```

Générer une clé de chiffrement Fernet (obligatoire pour stocker les mots de passe des sites) :

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

…puis la coller dans `CANDITRACK_FERNET_KEY` du fichier `.env`. Renseigner aussi `SECRET_KEY`.
Le fichier `.env`, la base `db.sqlite3` et le dossier `media/` sont ignorés par Git
(données personnelles).

## Lancement

```bash
python manage.py migrate
python manage.py createsuperuser   # pour accéder à /admin/
python manage.py runserver
```

Puis ouvrir http://127.0.0.1:8000/

## Déploiement Docker (issue #17)

Une image de production (gunicorn + statiques servis par WhiteNoise) est fournie.

```bash
cp .env.example .env   # renseigner SECRET_KEY, CANDITRACK_FERNET_KEY,
                       # DEBUG=False et ALLOWED_HOSTS pour la prod
docker compose up -d --build
```

L'entrypoint applique les migrations (dont le seed des sites) et collecte les
statiques au démarrage. La base SQLite et les CV uploadés sont persistés dans
des volumes nommés (`data`, `media`). L'app écoute sur le port **53487**.

Sans compose, directement avec Docker :

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
celui-ci, puis pousse l'image taguée `latest` et `<version>`.

Configuration unique — `Settings → Secrets and variables → Actions` :

| Secret | Valeur |
|---|---|
| `DOCKERHUB_USERNAME` | identifiant Docker Hub (= namespace de l'image `…/canditrack`) |
| `DOCKERHUB_TOKEN` | access token Docker Hub (Account → Security → New Access Token) |

## Extension Chrome (issue #2)

L'extension du dossier `chrome-extension/` permet d'ajouter l'offre de la page
courante à CandiTrack en un clic.

1. Générer un jeton et le mettre dans `.env` :
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   → coller la valeur dans `CANDITRACK_API_TOKEN` puis (re)lancer le serveur.
2. Dans Chrome : `chrome://extensions` → activer le **mode développeur** →
   **Charger l'extension non empaquetée** → choisir le dossier `chrome-extension/`.
3. Ouvrir les **options** de l'extension : renseigner l'URL du backend
   (`http://127.0.0.1:8000`) et coller le **jeton**.
4. Sur une page d'offre, cliquer l'icône CandiTrack : l'entreprise et l'URL
   sont pré-remplies (via les métadonnées JobPosting / Open Graph de la page),
   puis **Ajouter**. Le plugin ne renseigne pas le poste ni la date d'envoi
   (à compléter ensuite dans CandiTrack).

L'extension appelle `POST /api/candidatures/` en envoyant le jeton dans l'en-tête
`X-Api-Token`. Le backend par défaut écoute sur `127.0.0.1:8000`/`localhost:8000`
(déclarés dans `host_permissions` du `manifest.json` ; pour un autre hôte, l'y ajouter).

## Pages

| URL | Rôle |
|---|---|
| `/` (`/candidatures/`) | Liste des candidatures (créer / modifier / consulter) |
| `/sites/` | Sites d'emploi (#366 — gestion complète via `/admin/` pour l'instant) |
| `/stats/` | Statistiques (#367 — premiers KPI) |
| `/cv/` | CV (#368 — upload via `/admin/` pour l'instant) |
| `/admin/` | Administration Django (tous les modèles) |

## Prochaines itérations

- #366 : UI d'ajout de sites + récupération automatique du logo
- #367 : KPI complets (taux de réponse par source, délais moyens, graphes)
- #368 : reformatage du CV (technique/pro) + import LinkedIn
- #365 : intégration API France Travail, rappels actifs et notifications
