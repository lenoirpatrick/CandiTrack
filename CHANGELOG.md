# Changelog

Toutes les évolutions notables de CandiTrack sont consignées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionnage [SemVer](https://semver.org/lang/fr/). Chaque version correspond à
un milestone GitHub ; la liste des issues traitées est aussi publiée dans la
release du même nom.

## [Non publié] — 1.1.0

- #33 — Coaching IA (Gemini) : à partir du CV, des postes visés et des retours
  reçus (volume, motifs de refus…), un bilan de coaching et des actions à
  réaliser s'affichent dans une fenêtre modale (avec spinner d'attente). Sur
  chaque candidature, un bouton génère un brouillon de mail de relance. La
  fonctionnalité s'active en renseignant sa propre clé API Gemini dans la
  section « Configuration IA » de la page d'aide (clé stockée chiffrée).

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
