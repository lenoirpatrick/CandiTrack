# Guide pas à pas — Enregistrer une annonce LinkedIn dans CandiTrack

Objectif : depuis une offre d'emploi affichée sur LinkedIn, créer la candidature
correspondante dans CandiTrack **en un clic** grâce à l'extension Chrome.

> ℹ️ L'extension ne se connecte pas à LinkedIn et n'utilise aucune API LinkedIn.
> Elle lit simplement les informations de **la page que vous avez ouverte** (titre du
> poste, entreprise, URL) et les envoie à **votre** instance CandiTrack.

---

## Étape 0 — Prérequis (à faire une seule fois)

### 0.1 Démarrer le backend avec un jeton
Dans un terminal, à la racine du projet :
```powershell
.venv\Scripts\Activate.ps1
```
Si `CANDITRACK_API_TOKEN` n'est pas encore dans votre `.env`, générez-en un :
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Copiez la valeur dans `.env` :
```
CANDITRACK_API_TOKEN=la_valeur_generee
```
Puis lancez le serveur :
```powershell
python manage.py runserver
```
Laissez ce terminal ouvert. CandiTrack tourne sur **http://127.0.0.1:8000/**.

### 0.2 Installer l'extension
1. Ouvrez **`chrome://extensions`** dans Chrome.
2. Activez le **Mode développeur** (interrupteur en haut à droite).
3. Cliquez **Charger l'extension non empaquetée**.
4. Sélectionnez le dossier **`chrome-extension/`** du projet.
5. L'extension **CandiTrack** apparaît. Cliquez sur l'icône 🧩 (puzzle) de Chrome puis
   sur l'épingle à côté de CandiTrack pour **l'afficher** dans la barre d'outils.

### 0.3 Configurer l'extension
1. Clic **droit** sur l'icône CandiTrack → **Options**.
2. **URL du backend** : `http://127.0.0.1:8000`
3. **Jeton API** : collez la **même valeur** que `CANDITRACK_API_TOKEN` de votre `.env`.
4. Cliquez **Enregistrer** → vous devez voir « Enregistré ✓ ».

✅ Tout est prêt. Les étapes suivantes sont à refaire pour **chaque** annonce.

---

## Étape 1 — Ouvrir l'annonce sur LinkedIn

1. Allez sur **https://www.linkedin.com/jobs/** et lancez une recherche (mot-clé + lieu).
2. Dans les résultats, **cliquez sur une offre** : son détail s'affiche à droite.
3. **Important** : ouvrez l'offre sur sa **page dédiée** pour une extraction fiable.
   - soit cliquez sur le titre de l'offre / le bouton qui ouvre la page complète,
   - l'URL doit ressembler à `https://www.linkedin.com/jobs/view/4039xxxxxx/`.
4. Attendez que la page soit **entièrement chargée** (titre du poste + nom de l'entreprise visibles).

---

## Étape 2 — Ouvrir l'extension et vérifier le pré-remplissage

1. Cliquez sur l'icône **CandiTrack** dans la barre d'outils.
2. Une petite **popup** s'ouvre et tente de remplir automatiquement :
   - **Entreprise** → ex. « ACME France »
   - **URL de l'offre** → l'adresse `.../jobs/view/...`
   - **Localisation** → la zone géographique de l'offre (ex. « Lyon, France »)
   - **Source** → affichée en bas : `linkedin`

> ℹ️ Le plugin **ne capture volontairement pas l'intitulé du poste ni la date d'envoi** :
> vous les compléterez dans CandiTrack une fois la candidature réellement envoyée.
> Si l'entreprise est vide ou inexacte (LinkedIn change parfois sa mise en page),
> **corrigez-la** dans la popup. L'URL, elle, est toujours correcte.

---

## Étape 3 — Ajouter la candidature

1. Vérifiez/ajustez les champs.
2. Cliquez **Ajouter**.
3. La popup affiche **« Ajouté ✓ »** avec un lien **voir**.
   - Le bouton se réactive et un message d'erreur s'affiche si quelque chose ne va pas
     (voir Dépannage).

---

## Étape 4 — Vérifier dans CandiTrack

1. Ouvrez (ou rafraîchissez) **http://127.0.0.1:8000/**.
2. La nouvelle candidature apparaît dans la liste :
   - **Libellé** = le nom de l'entreprise
   - **Source** = LinkedIn, **URL de l'offre** cliquable
   - **Poste** et **date d'envoi** restent **vides** (à compléter)
3. Cliquez sur son libellé pour ouvrir le détail et compléter le poste, la date d'envoi,
   les étapes, les dates d'entretien, etc.

🎉 L'annonce LinkedIn est enregistrée.

---

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Configurez l'URL et le jeton… » | Options non remplies | Refaire l'**étape 0.3** |
| « Erreur : unauthorized » (401) | Jeton de l'extension ≠ `CANDITRACK_API_TOKEN` du `.env` | Recopier exactement le jeton, **Enregistrer**, réessayer |
| « Erreur réseau… » | Serveur arrêté ou mauvaise URL backend | Vérifier que `runserver` tourne et que l'URL est `http://127.0.0.1:8000` |
| Entreprise vide dans la popup | Page pas finie de charger, ou structure LinkedIn différente | Recharger l'annonce, rouvrir la popup, sinon **saisir à la main** |
| Rien ne se passe au clic sur l'icône | Vous n'êtes pas sur un onglet de page web (ex. `chrome://`) | Ouvrir l'extension depuis l'**onglet de l'annonce** |
| Modifs de l'extension non prises en compte | Cache de l'extension | `chrome://extensions` → bouton **⟳** sur la carte CandiTrack |

### Tester sans LinkedIn (vérifier que la chaîne fonctionne)
Sur n'importe quelle page d'offre (Indeed, Welcome to the Jungle…), la même procédure
s'applique. Pour un test purement backend, voir la section 3 de **`../TESTING.md`**
(`Invoke-RestMethod` vers `/api/candidatures/`).

---

## Notes et limites

- **Page dédiée recommandée** : sur la page de recherche LinkedIn (`/jobs/search/`),
  plusieurs offres coexistent ; ouvrez l'offre sur sa page `/jobs/view/...` pour que
  l'entreprise et le poste soient extraits de manière fiable.
- **Pas de connexion requise côté extension** : elle lit la page visible. Si l'offre n'est
  visible que connecté à LinkedIn, restez connecté dans votre onglet — l'extension lit
  alors ce que **vous** voyez.
- **Doublons** : cliquer « Ajouter » deux fois crée deux candidatures. Supprimez l'éventuel
  doublon depuis CandiTrack.
- **Autre machine / hôte** : si votre backend n'est pas en local, ajoutez son URL dans
  `host_permissions` du `manifest.json`, puis rechargez l'extension.
