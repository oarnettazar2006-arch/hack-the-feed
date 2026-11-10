# Journal de bord

Notes prises pendant la préparation (du 3 au 6 novembre 2026) et le jour du hackathon (samedi 7 novembre). On y garde les mesures, les erreurs trouvées et ce qu'elles ont fait changer dans l'outil.

## Avant le jour J

Jusqu'au samedi, le pipeline a tourné sur de fausses vidéos, générées avec les mêmes champs que l'API Oriane (`sources/fake_social.py`), faute de crédits Oriane. La presse, elle, était déjà réelle : flux RSS, chaînes YouTube et archives de quatorze jours reconstituées par les sitemaps des journaux.

Le 5 novembre, après les consignes des organisateurs, l'outil a été recentré sur ce que seule la lecture de la vidéo permet de voir.

- Pour chaque vidéo, le modèle dit si la légende et les hashtags suffisent à deviner le sujet, où le sujet est exprimé (paroles, texte à l'écran, légende), et recopie une citation exacte.
- Les citations sont horodatées grâce aux segments de transcription d'Oriane, ou rattachées à l'image où le texte est écrit.
- Par sujet, on cherche la vidéo après laquelle le rythme change le plus (48 heures après contre 48 heures avant).

Deux garde-fous viennent de mesures faites ce jour-là. Sur douze vidéos sans commentaires, le modèle donnait quand même une réaction du public dans dix cas : le code force maintenant « sans commentaires ». Et une citation dont les mots ne se retrouvent pas dans la vidéo est supprimée.

## Samedi 7 novembre

### Collecte

Chaque compte Oriane de l'équipe avait 8 000 crédits. Mesuré à 10 h 23 : une recherche coûte 20 crédits avec les transcriptions et 10 sans, quel que soit le nombre de vidéos renvoyées. On demande donc le maximum de vidéos par appel, et `oriane-plan` affiche les crédits estimés avant de lancer quoi que ce soit.

La première clé s'est vidée après 391 appels. Le pipeline passe maintenant d'une clé à la suivante quand les crédits sont épuisés, et relit le fichier `.env` avant d'abandonner, ce qui permet d'ajouter une clé pendant une collecte.

Les comptes TikTok et Instagram des médias suivis ont été trouvés par la recherche de profils d'Oriane, puis vérifiés à l'œil : 27 gardés, 8 écartés parce que c'étaient des homonymes (pour CNews la recherche renvoyait BBC News, pour Blast un DJ et un club de foot, pour Le Média « Le Média Positif »).

### Premier run réel, vers 11 h

11,6 minutes et 1,89 $ pour 6 602 vidéos, 75 sujets et 20 fiches. Ce premier classement avait trois défauts, corrigés dans la foulée.

- Le premier sujet était « en baisse », porté par un seul créateur viral. Le classement se fait maintenant par état d'abord, et la surperformance est plafonnée à ×3.
- Avec un seuil de similarité de 0,66, 73 sujets sur 75 étaient donnés comme déjà couverts par la presse, avec de faux rapprochements. Le seuil est passé à 0,75.
- Il manquait des thèmes entiers et les filets sans mot-clé, faute de crédits. Le complément, lancé avec les autres clés, a ajouté 2 297 vidéos et 1 384 publications des comptes de médias.

### Le retard d'indexation d'Oriane

Mesuré le matin : les jours sont complets jusqu'au 1er novembre, puis indexés à 32 % le 2 et à environ 10 % du 3 au 5. L'équipe d'Oriane nous l'a confirmé dans la journée : une vidéo met environ quatre jours à arriver dans l'index, il n'y a pas de flux en temps réel, les comptes de moins de 5 000 abonnés ne sont pas indexés, et une vidéo peu vue n'a parfois pas d'analyse du texte à l'écran.

Conséquences dans le code : le score principal s'arrête au dernier jour indexé à au moins 50 %. Les signaux faibles lisent aussi les jours indexés à au moins 10 %, en comptant les vidéos sans extrapoler.

### Campagne et sondages

Les sondages viennent de la page Wikipédia qui recense ceux de la présidentielle 2027 (46 sondages). On garde un relevé daté à chaque passage, pour qu'un sondage retiré de la page reste dans notre historique.

La surexposition d'un candidat est sa part des vues divisée par sa part dans les sondages, calculées sur le même ensemble de candidats. Pour David Lisnard, les vidéos qui le citent passent de 9 à 21 par semaine en septembre à 30 dès le 29 septembre, puis 63 la semaine du 20 octobre. Ses sondages, entre 2 et 5 % jusqu'à fin septembre, sont à 6-7 % à partir du 14 octobre. Bruno Retailleau, pris comme témoin, n'a pas de tendance dans les vidéos (18 à 66 par semaine) et baisse dans les sondages. Avec d'aussi petits volumes, c'est un signal précoce plausible.

Pour une personnalité absente des sondages, l'outil ne donne jamais de score estimé. Il dit seulement à qui elle se compare en visibilité (« aussi visible que X, sondé à Y % »).

### Une erreur trouvée par le contrôle humain, 12 h 42

En remplissant sa grille, Erwan a remarqué que certaines vidéos avaient été lues sans leur légende. La légende était placée après les paroles, puis le texte était coupé à 1 800 caractères. Sur 9 192 vidéos, 2 957 (32 %) avaient donc été annotées sans légende, et le modèle y répondait « la légende ne suffit pas » dans 99 % des cas, contre 21 % quand il la voit. La part de vidéos « hors légende » était gonflée.

Correction en deux temps. D'abord ne compter que les vidéos dont la légende a bien été lue, et placer le titre, la légende et les hashtags en tête du texte pour les collectes suivantes. Puis, à 14 h, recharger les 2 957 vidéos depuis Oriane avec leur légende (30 appels), les faire relire, et refaire l'analyse et les fiches (1,19 $).

Le chiffre corrigé est de 34 % (3 084 vidéos sur 9 180), puis de 33 % (3 278 sur 9 992) une fois ajoutées les vidéos du Sud-Ouest et du filet décollage.

### Comparaison avec la presse sur le passé : non concluante

Nous voulions montrer, sur quatre histoires passées, quand l'outil les aurait vues. Résultat à 12 h 45 : aucune avance démontrée.

- Pour les violences du 17 octobre, le pic de vidéos du 19 correspond aux événements eux-mêmes, et notre « premier article » du 23 n'est que le début de nos archives de presse, qui commencent le 21.
- Pour la loi dite casseurs-payeurs, l'avance reposait sur deux vidéos.
- Pour le BHV et le Wegovy, zéro à deux vidéos : pas de signal.

Le code refuse maintenant de conclure sous cinq vidéos par jour, et ne tient une date de presse pour fiable que si nos archives couvrent les dix jours qui précèdent. Pour refaire le test correctement, il faudrait remonter les archives de presse sur 45 jours.

### Le local et les comptes éclaireurs, à partir de 13 h

À la mi-journée, Brut nous a dit trois choses. Les sujets naissent souvent dans une région avant de devenir nationaux, comme les gilets jaunes. La rédaction cherche des comptes de niche, notamment locaux, qu'elle ne suit pas encore. Et toutes les sources sont permises en plus d'Oriane.

D'où la veille locale, avec le Sud-Ouest comme région de démonstration (Nouvelle-Aquitaine et ouest de l'Occitanie). Une vidéo est rattachée à la région par le lieu tagué, le lieu du profil, la bio du créateur, puis une ville ou un département cité. 800 vidéos collectées en 34 appels. Pour chaque sujet, on calcule sa part locale, son foyer, et s'il est né localement avant d'être repris ailleurs.

Les comptes éclaireurs sont des comptes de 5 000 à 150 000 abonnés (500 à 150 000 sur X) qui publient dans le premier quart de la vie d'un sujet qui grossit ensuite. Les médias nationaux et locaux connus sont exclus, et chaque compte est typé créateur, média ou élu.

Le filet « décollage », ajouté à 13 h 30, ramène 852 vidéos qui font au moins trois fois l'audience de leur créateur, sans mot-clé.

### X via Apify, 14 h 40

X a les publications du jour même et n'a pas de seuil d'abonnés, ce qui comble en partie le retard d'Oriane. Budget : le crédit gratuit d'Apify (5 $), plafonné à 4 $ dans le code et vérifié auprès d'Apify avant chaque lancement.

Deux choses n'ont pas marché comme prévu. Le premier scraper essayé bride les comptes gratuits à dix tweets par lancement, il a fallu en changer. Et la recherche géolocalisée ne renvoie rien, donc on cherche par villes et par départements.

Au total 3 562 tweets du Sud-Ouest depuis le 22 octobre, pour 1,01 $. Ils sont lus par le modèle comme la presse, puis rapprochés des sujets. 28 sujets ont des tweets rapprochés, dont le PV de police de Bordeaux (75 tweets), les manifestations de Toulouse (57) et Lecornu à Limoges (75), ce dernier circulant sur X avant la première vidéo.

Limite : la collecte X commence le 22 octobre, donc un « premier tweet » daté de ce jour peut avoir des précédents.

### Liens Instagram

Oriane ne fournit pas le code court des publications Instagram. On en retrouve 2 221 sur 4 852 à partir de l'adresse des images. Les autres liens pointent vers le compte, et l'interface le dit.

### Résultat du contrôle humain

30 vidéos TikTok, annotées à l'aveugle par Erwan et comparées aux annotations du modèle.

- Ton : accord dans 19 cas. Sur les 11 désaccords, 6 portent sur des tons voisins (critique contre informatif) et 2 inversent le sens (une vidéo ironique lue comme favorable, une vidéo favorable lue comme critique).
- Ironie : sur les 7 vidéos qu'Erwan juge ironiques, le modèle en repère 5. Sur les 7 que le modèle juge ironiques, Erwan est d'accord pour 5.
- « La légende suffit-elle ? » : accord dans 18 cas. Erwan répond oui 26 fois. Dans les 11 cas où le modèle dit non et lui oui, la légende est vide ou sans rapport avec le sujet 8 fois, et le modèle est trop strict 3 fois. Avant la correction des légendes coupées, l'accord n'était que de 11 sur 30.
- Personnalités : le modèle retrouve au moins une personnalité citée par Erwan dans 11 vidéos sur 18.
- Sujet : les formulations diffèrent (similarité médiane de 0,63), on ne met pas ce chiffre en avant.

### État en fin de journée

91 sujets, 20 fiches, un brief de 5 sujets, 198 comptes éclaireurs dont 48 du Sud-Ouest et 27 sur X. Dépense totale chez Anthropic depuis le début du projet : 6,76 $. Dépense Apify : 1,01 $.

## Pistes pour la suite

- Étendre la veille locale à toutes les régions. Une région est une liste de villes, de départements et de médias locaux dans `local.py`.
- Ajouter la presse régionale en RSS pour dater la couverture locale avant la nationale.
- Regrouper en sujets les tweets des 48 dernières heures, la période qu'Oriane n'a pas encore.
- Refaire la comparaison avec la presse sur 45 jours d'archives.
- Prévenir la rédaction quand un sujet passe « à traiter maintenant » ou qu'un compte éclaireur publie.
