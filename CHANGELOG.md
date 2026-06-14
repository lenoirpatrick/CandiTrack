# Changelog

Toutes les évolutions notables de CandiTrack sont consignées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnage [SemVer](https://semver.org/lang/fr/). Chaque version correspond à
un milestone GitHub ; la liste des issues traitées est aussi publiée dans la
release du même nom.

## [Non publié] — 1.2.0

- #43 — Sites d'emploi : suppression de la gestion des **identifiants et mots de
  passe**. Seuls le nom, l'URL et le logo d'un site sont désormais conservés ;
  les champs `username`/`password` (et leur stockage chiffré) sont retirés du
  modèle, du formulaire et de la liste.

## [Non publié] — 1.1.0

- #35 — Modernisation de l'interface : navigation déplacée dans une **sidebar
  latérale rétractable** (étendue avec icônes + libellés, réduite en icônes
  seules avec tooltips au survol, transition animée, bouton de bascule ; état
  mémorisé). L'entrée **Options** reste épinglée en bas dans les deux états.
  Design corporate (ombres subtiles, coins arrondis, focus accessibles),
  **animations des graphiques** de statistiques (barres et donut qui se
  tracent, survol interactif de la légende, KPI en cascade) et **affichage
  mobile réactif** (tiroir avec voile).
- #33 — Coaching IA (Gemini) : à partir du CV, des postes visés et des retours
  reçus (volume, motifs de refus…), un bilan de coaching et des actions à
  réaliser s'affichent dans une fenêtre modale (avec spinner d'attente). Sur
  chaque candidature, un bouton génère un brouillon de mail de relance. La
  fonctionnalité s'active en renseignant sa propre clé API Gemini (clé stockée
  chiffrée), avec choix du modèle dans un menu déroulant (défaut Gemini 2.5
  Flash). Le menu « Aide » devient « Options » (déplacé près du bouton de thème)
  et regroupe désormais le choix d'apparence clair/sombre/système par vignettes.
- #34 — Page Options réorganisée en catégories (onglets) : **Interface** (thème),
  **Extensions** (plugin Chrome et clés API) et **IA** (coaching) ; la catégorie
  ouverte est mémorisée et accessible via l'ancre d'URL. Le coaching gère
  désormais **deux fournisseurs au choix — Google Gemini ou Mistral AI** :
  chacun garde sa propre clé (chiffrée) et son modèle, on bascule de l'un à
  l'autre sans ressaisie.
- #36 — Quotas d'utilisation des clés IA : chaque appel journalise les tokens
  consommés ; la conso du mois courant (appels + tokens) s'affiche par
  fournisseur dans Options → IA, avec une **limite mensuelle configurable** qui
  avertit lorsqu'elle est atteinte (limite souple, sans blocage).
- #37 — La fenêtre modale d'IA indique désormais **le fournisseur et le modèle**
  qui ont généré le texte (ex. « Généré par 🔵 Google Gemini · gemini-2.5-flash »).
- #38 — Options → IA : rappel des **quotas du tier gratuit** de chaque fournisseur
  (Gemini, Mistral) avec un **lien vers la documentation officielle**.
- #39 — Trois fournisseurs d'IA supplémentaires : **OpenAI (ChatGPT)**,
  **Anthropic (Claude)** et **Perplexity**, chacun avec sa clé, son modèle, sa
  limite mensuelle, ses infos de tier gratuit et son lien doc/clé.

## [Non publié] — 1.0.2

- #21 — Suppression d'une candidature (avec confirmation).
- #22 — Sites d'emploi : désactivation des sites par défaut et suppression des
  sites ajoutés manuellement ; les sites désactivés ne sont plus proposés.
- #23 — Easter egg : à l'acceptation d'une offre, la barre de progression passe
  à 100 % en vert et un jet de confettis s'affiche.
- #24 — Documentation : description du dépôt, ce CHANGELOG et publication
  automatique d'une release à la clôture de chaque milestone.
- #25 — Relecture SonarQube : analyse statique SonarQube Cloud avec mesure de
  couverture (workflow GitHub Actions sur `main` et pull requests).
- #26 — Correctif : les boutons « Nouvelle candidature », « Ajouter un site » et
  « Charger un CV » devenaient illisibles une fois visités (texte de la couleur
  du fond) ; la couleur du texte est désormais verrouillée pour tous les états.
- #27 — Sites d'emploi : suppression du bouton « Logo » de la liste ; le favicon
  du site est désormais chargé automatiquement à l'enregistrement (un logo
  manuel reste possible via le champ dédié).
- #28 — Liste des candidatures : retrait de la colonne « Date d'envoi ».
- #30 — Motif de clôture : ajout de « Pas donné suite ».
- #31 — Canal d'envoi : ajout de « Contact entrant (tél./mail) » et
  « Relationnel ».
- #32 — Sites d'emploi : le bouton activer/désactiver devient un interrupteur.

## [1.0.1] — 2026-06-13

- #19 — Upload des CV limité à 5 Mo.
- #20 — Pied de page de copyright (Patrick Lenoir & Claude Code).

## [1.0.0] — 2026-06-13

Première version : fondation du suivi de candidatures et conteneurisation.

- #1 — Ajout de sites d'emploi (mot de passe chiffré au repos).
- #2 / #9 — Extension Chrome : ajout de la page d'offre courante en un clic,
  avec récupération du nom de l'entreprise.
- #3 — Création / édition d'une candidature.
- #4 — Thème sombre.
- #5 — Clôture d'une candidature (motif).
- #6 — Page d'aide et gestion des jetons API.
- #7 — Masquage du lien vers l'admin Django.
- #8 — Affichage du site source et de l'entreprise dans la liste / le détail.
- #10 — Couleur de la barre de progression selon l'avancement.
- #11 — Tri des colonnes et champ de recherche des candidatures.
- #12 — Colonne « Statut » (étape courante).
- #13 — Notifications (toasts).
- #14 — Améliorations UX (icônes de menus, palette).
- #15 — KPI : répartition par source en graphique circulaire.
- #16 — Base de sites de candidature connus pour le déploiement.
- #17 — Dockerfile de production (gunicorn + WhiteNoise).
- #18 — Publication de l'image sur Docker Hub via GitHub Actions.
