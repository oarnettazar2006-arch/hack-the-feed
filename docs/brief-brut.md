# Ce que veut Brut, et comment on y répond

## L'objectif

Un outil pour les journalistes de Brut, d'abord l'éditeur du matin. Chaque matin, il doit savoir quels sujets montent sur TikTok et Instagram avant qu'ils deviennent des tendances, d'où ils viennent, ce que les vidéos en disent et quoi en faire pour Brut. On le mesure en lisant ce qui est dit et écrit dans les vidéos (grâce à Oriane), en plus des légendes et des hashtags.

Notre phrase : « Un outil qui aide l'éditeur du matin de Brut à repérer les sujets de campagne qui montent sur TikTok et Instagram avant la presse, en lisant ce qui est dit et écrit dans les vidéos, pas les hashtags. »

Règle de fond : chaque chiffre renvoie à ses vidéos sources, chaque citation est exacte, chaque limite est dite. Un journaliste doit pouvoir vérifier, contacter, tourner.

## Ce que Brut nous a dit

### Consignes des organisateurs (5 novembre)

- La formule attendue : « un outil qui aide qui à faire quoi grâce à la vidéo ».
- « Un outil qui fait une chose et la fait vraiment bien bat toujours la démo qui promet tout. »
- Les quatre questions de Brut : de quoi parlent les 18-25 ans sur TikTok ; quels sujets de campagne montent avant que quiconque le remarque (c'est la nôtre) ; quel candidat fait réagir et sur quel ton ; quelle vidéo a fait basculer un débat.
- Les trois critères du jury : la pertinence en salle de rédaction (Brut), la réponse à un besoin réel de l'utilisateur (Deel), et la compréhension de ce qui se passe à l'intérieur de la vidéo (Oriane).

### Pendant la journée (7 novembre)

1. La politique compte beaucoup : quelles campagnes fonctionnent, quelle figure monte. Il faut un bon filtre politique.
2. Le cœur du sujet : attraper les sujets avant qu'ils deviennent de très grosses tendances.
3. Le local : les sujets naissent souvent dans une région avant de devenir nationaux, comme les gilets jaunes. L'exemple demandé était le Sud-Ouest.
4. Le champ « angle mort » est libre, mais ce qui intéresse la rédaction, ce sont des comptes peu connus, notamment locaux, qu'elle ne suit pas encore.
5. Oriane est la base, mais toutes les sources peuvent être croisées. Apify a été cité.
6. La démo est une vidéo de trois minutes.

### Ce qu'Oriane nous a appris

- Une vidéo met environ quatre jours à arriver dans l'index, sans flux en temps réel.
- Les comptes de moins de 5 000 abonnés ne sont pas indexés.
- Une vidéo peu vue n'a parfois pas d'analyse du texte à l'écran.
- Le nombre de vues ne change pas le délai d'indexation.

## Comment l'outil y répond

| Demande | Ce qu'on a construit | Où |
|---|---|---|
| Sujets qui montent | Radar : regroupement des vidéos en sujets, trois signaux lisibles (accélération, nombre de créateurs, vues au-dessus de l'audience habituelle) et un état par sujet | `analyze.py`, table `topics` |
| Avant la grosse tendance | Signaux faibles (sujets neufs, petits, portés par plusieurs créateurs), filet décollage (vidéos à au moins 3 fois l'audience de leur créateur) et veille ouverte, tous deux sans mot-clé | `analyze.py`, `sources/oriane.py` |
| Lire la vidéo et pas seulement les hashtags | 33 % des vidéos (3 278 sur 9 992) ne laissent pas deviner leur sujet par la légende et les hashtags ; citations exactes avec la seconde | `analyze.evidence`, `topics.citations` |
| Politique, qui monte | Filtre campagne 2027, parti et camp des personnalités, tendance, part de voix, solde favorable ou critique, volumes réels d'Oriane | `politics.py`, table `personnalites` |
| Campagnes qui marchent | Sondages (Wikipédia, relevés réguliers) comparés à la visibilité ; pour Lisnard, les vidéos doublent environ deux semaines avant le saut dans les sondages | `polls.py`, tables `sondages` et `sondages_releves`, `docs/visuels/` |
| Du local au national | Veille locale Sud-Ouest : foyer d'un sujet, sujets nés localement puis repris au national (exemple : le PV de police de Bordeaux du 17 octobre) | `local.py`, `topics.foyer`, `topics.local_vers_national` |
| Comptes de niche | Comptes éclaireurs : 5 000 à 150 000 abonnés sur TikTok et Instagram, 500 à 150 000 sur X, qui publient en premier sur des sujets qui grossissent, typés créateur, média ou élu | `local.scouts`, table `comptes_eclaireurs` |
| Croiser les sources | X via Apify pour le Sud-Ouest : tweets du jour même, rapprochés des sujets ; comptes X de niche parmi les éclaireurs | `sources/x_apify.py`, `topics.x_*` |
| Utile au journaliste | Fiche par sujet écrite par Claude Opus : pourquoi ça monte, positions, qui l'a déjà traité, angle et format pour Brut, points à vérifier ; brief du matin | `showcase.py`, tables `topics` et `brief` |
| Fiabilité | Contrôle humain à l'aveugle sur 30 vidéos ; erreurs trouvées et corrigées dans la journée (légendes coupées, liens Instagram, comparaison avec la presse) | `controle.py`, `docs/controle/`, `docs/journal.md` |

## Limites

- On mesure des vidéos. Ce n'est ni l'opinion des Français ni l'avis « des 18-25 ans » : Oriane ne donne pas l'âge des spectateurs.
- Environ quatre jours de retard, et pas de comptes sous 5 000 abonnés.
- La comparaison avec la presse sur des histoires passées n'est pas concluante, la fenêtre de données est trop courte. Ce qu'on montre à la place, c'est Lisnard face aux sondages, une source extérieure.
- Les partis, les camps et les types de comptes sont classés par nous, et restent à vérifier.
- Le Sud-Ouest est une région de démonstration. En ajouter une demande une liste de villes et de médias locaux.
- X n'est couvert que sur le Sud-Ouest. Facebook ne l'est pas (groupes fermés).
