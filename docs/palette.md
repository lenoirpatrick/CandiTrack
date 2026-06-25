# Palette de couleurs — CandiTrack

Palette de référence (issue #14) :
<https://coolors.co/080e20-090f23-0a1127-0b132b-1c2541-3a506b-5bc0be>

| Hex       | Rôle indicatif                          |
|-----------|------------------------------------------|
| `#080E20` | Noir bleuté (fond le plus profond)       |
| `#090F23` | Variante                                 |
| `#0A1127` | Fond des champs (thème sombre)           |
| `#0B132B` | Fond principal (thème sombre)            |
| `#1C2541` | Cartes (thème sombre) / texte (clair)    |
| `#3A506B` | Bordures (sombre) / accent (clair)       |
| `#5BC0BE` | Accent / surbrillance (thème sombre)     |

## Application

Les couleurs sont mappées sur les variables CSS du thème dans
`templates/base.html` (`:root`, `@media (prefers-color-scheme: dark)`,
`:root[data-theme="dark"]` et `:root[data-theme="linkedin"]`).

- **Thème clair** : accent `#3A506B` (slate, bon contraste avec le texte blanc
  des boutons), texte `#0B132B`.
- **Thème sombre** : reprend directement la palette — fond `#0B132B`, cartes
  `#1C2541`, bordures `#3A506B`, accent `#5BC0BE`.
- **Thème LinkedIn** (issue #68) : variante claire aux couleurs de LinkedIn —
  fond gris `#F3F2EF`, cartes blanches, accent bleu LinkedIn `#0A66C2`, texte
  `#1D2226`, puces/chips bleutées `#E8F0FB`.

Les couleurs du graphique circulaire « répartition par source » (issue #15)
sont définies dans `tracking/statistics.py` (`SOURCE_COLORS`), ancrées sur la
palette tout en restant distinguables entre segments.
