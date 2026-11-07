# Contrôle humain : 30 vidéos contre Haiku (Erwan)

But : mesurer si Haiku lit bien les vidéos, surtout l'ironie. Chiffre attendu par le jury : « accord x/30 ».

**À l'aveugle** : ne pas lancer l'analyse, ne pas ouvrir `data/out/controle-haiku.json` (les réponses de Haiku restent sur la machine d'Oscar).

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
4. Enregistrer en CSV (point-virgule) sous `docs/controle/grille-remplie-erwan.csv` et pousser sur GitHub (ou l'envoyer à Oscar).

Comparaison (Oscar) : `python -m htf.cli controle-comparer ../docs/controle/grille-remplie-erwan.csv`.
