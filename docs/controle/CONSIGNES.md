# Contrôle humain : 30 vidéos annotées à l'aveugle

But : mesurer si le modèle lit bien les vidéos, surtout l'ironie.

La commande `controle-echantillon` tire 30 vidéos politiques parmi les sujets exportés, dont plusieurs que le modèle juge ironiques, et écrit la grille vierge `grille-30-videos.csv`. Les réponses du modèle restent dans `data/out/controle-haiku.json`, hors du dépôt.

À l'aveugle : ne pas lancer l'analyse et ne pas ouvrir ce fichier avant d'avoir fini.

1. Ouvrir `grille-30-videos.csv` (Google Sheets : Fichier > Importer, séparateur point-virgule ; ou Excel).
2. Pour chaque ligne : regarder la vidéo (`lien`) ou, si elle ne charge pas, lire `paroles_et_texte_a_l_ecran`.
3. Remplir les 5 colonnes `VOTRE_…` :
   - `VOTRE_sujet` : une phrase neutre de 6 à 15 mots, style titre de dépêche AFP (« Le gouvernement prévoit 2,3 M€ pour les futurs bureaux de Macron »). Pas d'opinion.
   - `VOTRE_ton` : un seul mot parmi `favorable`, `critique`, `ironique`, `informatif`, `incertain`.
     favorable = la vidéo soutient ; critique = elle attaque sérieusement ; ironique = moquerie, second degré ;
     informatif = explique sans prendre parti ; incertain = impossible à dire.
   - `VOTRE_legende_suffit` : `oui` si on devine le sujet en lisant seulement la légende et les hashtags, sinon `non`.
   - `VOTRE_personnalites` : personnalités publiques citées ou visées (prénom nom, séparées par des virgules), vide sinon.
   - `VOTRE_remarque` : facultatif (vidéo indisponible, hésitation…).
4. Enregistrer en CSV (point-virgule), par exemple sous `docs/controle/grille-remplie-erwan.csv`.

Comparaison, depuis `pipeline/` : `python -m htf.cli controle-comparer ../docs/controle/grille-remplie-erwan.csv`.

## Résultat du 7 novembre

Grille remplie par Erwan (`grille-remplie-erwan.csv`), comparée aux annotations du modèle.

| Mesure | Résultat |
|---|---|
| Même ton | 19 sur 30 |
| Désaccords qui inversent le sens de la vidéo | 2 sur 30 |
| Vidéos ironiques repérées par le modèle | 5 sur 7 |
| Même réponse à « la légende suffit-elle ? » | 18 sur 30 |
| Vidéos où le modèle retrouve au moins une personnalité citée | 11 sur 18 |

Le commentaire de ces chiffres est dans [le journal de bord](../journal.md).
