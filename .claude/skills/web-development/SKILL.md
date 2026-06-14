---
name: web-development
description: Construire une application web professionnelle en reprenant les principes éprouvés de CandiTrack — thème clair/sombre piloté par variables CSS, connexion aux IA génératives (multi-fournisseurs), présentation UI corporate, graphiques maison et workflow CI SonarQube. À utiliser pour démarrer une nouvelle appli web ou en moderniser une existante selon ces conventions.
---

# Développement web — principes CandiTrack

Ce skill capture les choix de conception réutilisables de **CandiTrack** (Django
6 / Python 3.14, SQLite, application mono-utilisateur, langue française). Il sert
de gabarit pour bâtir une nouvelle application web cohérente ou pour aligner une
appli existante. Les exemples renvoient aux fichiers réels du dépôt — les lire
avant d'adapter.

Langue par défaut : **français** (libellés, commentaires, messages de commit).
Workflow **piloté par les issues** : chaque commit référence `#N`.

## 1. Configuration

### Thème clair/sombre

Référence : `templates/base.html` (CSS inline) + `docs/palette.md`.

Principes :
- **Variables CSS** sur `:root` pour toutes les couleurs (`--bg`, `--card`,
  `--border`, `--accent`, `--accent-soft`, `--sidebar-*`, `--radius`,
  `--shadow*`). Aucune couleur en dur dans les composants — toujours
  `var(--accent)`.
- **Trois sources de thème**, dans cet ordre de priorité :
  1. `:root` → thème clair par défaut ;
  2. `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`
     → préférence système ;
  3. `:root[data-theme="dark"]` / `[data-theme="light"]` → choix explicite de
     l'utilisateur, persisté dans `localStorage`.
- **Anti-flash** : un petit script *inline en `<head>`* lit `localStorage` et
  pose `data-theme` / `data-sidebar` sur `<html>` **avant** le premier rendu,
  pour éviter le flash de thème clair au chargement.
- Palette ancrée sur une référence documentée (`docs/palette.md`) plutôt que des
  couleurs improvisées.

### Connexion aux IA

Référence : `tracking/ai.py`, `tracking/coaching.py`, modèle `AIConfig` dans
`tracking/models.py`.

Principes :
- **Clients REST en stdlib** (`urllib.request`, `json`) — pas de SDK lourd, à
  l'image de `tracking/logos.py`. Un timeout explicite (`TIMEOUT = 60`).
- **Multi-fournisseurs** derrière une fonction unique `generate(..., provider=)`
  qui aiguille. Mutualiser les formats compatibles (OpenAI / Mistral /
  Perplexity partagent « chat completions » ; Anthropic a l'API Messages).
- **Clés API par fournisseur**, stockées **chiffrées au repos** (Fernet via
  `EncryptedCharField`, voir `tracking/fields.py`) ; jamais réaffichées dans
  l'UI (placeholder « laisser vide pour conserver »). Clé fournie par
  l'utilisateur (ses crédits, ses données).
- **Singleton de config** (`AIConfig.load()`), un modèle + une limite par
  fournisseur, accès générique par `getattr(self, f"{provider}_api_key")`.
- Erreurs encapsulées dans une exception métier présentable
  (`AIError`) ; chaque appel renvoie un `GenerationResult` (texte + tokens) et
  est journalisé pour le suivi des quotas.
- Documenter le tier gratuit + lien doc + lien clé par fournisseur
  (`PROVIDER_INFO`) pour guider l'utilisateur.

Toute la config passe par un `.env` (jamais commité), chargé via
`python-dotenv`, avec un `.env.example` de départ.

## 2. UX / UI

### Présentation professionnelle

Référence : `templates/base.html`.

Principes :
- **Sidebar latérale rétractable** (desktop : `data-sidebar="expanded|collapsed"`
  persisté ; mobile : tiroir `.sidebar-open`). Entrée « Options » épinglée en bas.
- Style corporate via `--radius`, `--shadow*` ; survols et états actifs au
  `--accent` ; transitions douces.
- **Feedback utilisateur** : toasts (`.toast` avec variantes info/success/error),
  spinners pour les actions longues (appels IA), modales partagées.
- Accessibilité : `aria-label` sur les contrôles iconographiques, focus visible
  (`box-shadow: 0 0 0 3px var(--accent-soft)`).

### Graphiques

Référence : `tracking/statistics.py` (géométrie du donut), `SOURCE_COLORS`.

Principes :
- **Graphiques calculés côté serveur** en géométrie pure (SVG / barres CSS),
  sans librairie front lourde — la vue prépare les segments, le template les
  rend.
- Couleurs des segments **ancrées sur la palette** du thème tout en restant
  distinguables ; barres de progression dont la teinte évolue (rouge → vert)
  selon l'avancement.

## 3. Workflow CI

### SonarQube Cloud

Référence : `.github/workflows/sonarqube.yml`, `sonar-project.properties`.

Principes :
- Workflow déclenché sur `push` vers `main`, sur les **pull requests** et en
  `workflow_dispatch`. `fetch-depth: 0` pour l'attribution des lignes.
- Étapes : installer les deps + `coverage` → lancer les tests avec couverture
  (`coverage run manage.py test` puis `coverage xml`) → action
  `SonarSource/sonarqube-scan-action`.
- `sonar-project.properties` : `projectKey`, `organization`, `sonar.sources`,
  `sonar.tests`, `sonar.python.coverage.reportPaths=coverage.xml`, et des
  **exclusions** (migrations, `__pycache__`, statiques, fichier de tests — les
  ensembles sources/tests doivent être **disjoints**).
- Secrets requis : `SONAR_TOKEN` (et toute clé d'environnement nécessaire aux
  tests, ex. clé Fernet jetable générée à la volée si absente).
- Désactiver « Automatic Analysis » côté SonarCloud pour éviter le conflit avec
  l'analyse pilotée par CI.

## Checklist de démarrage

1. `.env` + `.env.example` ; secrets jamais commités.
2. `base.html` : variables CSS, trois sources de thème, script anti-flash.
3. Sidebar rétractable + toasts + modales partagées.
4. Module IA stdlib multi-fournisseurs, clés chiffrées, quotas journalisés.
5. Graphiques calculés serveur, couleurs ancrées sur la palette.
6. Workflow SonarQube + `sonar-project.properties` (sources/tests disjoints).
7. Tests (`manage.py test`) verts et couverture générée avant tout push.
