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
