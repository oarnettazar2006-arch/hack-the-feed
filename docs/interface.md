# Spécification de l'interface

L'interface est un outil interne pour l'éditeur du matin d'une rédaction vidéo. Elle lit les tables Supabase remplies par le pipeline, en lecture seule, avec la clé publique `anon`. Elle ne crée aucune table et n'invente aucun chiffre : une valeur nulle s'affiche « — ». La seule écriture autorisée est la case `brief.valide`.

Toute l'interface est en français. Navigation principale : Radar, Campagne, Sud-Ouest, Brief du matin.

Ce document a été écrit avant l'interface et lui a servi de cahier des charges. La démo en ligne s'en écarte sur quelques points : l'écran Campagne s'y appelle Politique, la veille locale est répartie entre les onglets Régions et Comptes, et une page Méthode rassemble les limites.

## Tables

`topics` : un sujet par ligne.

- Identité et classement : `id`, `rang`, `etat`, `titre` (peut être nul : afficher alors `sujet_type`), `sujet_type`, `politique` (bool), `themes` (text[]), `score`.
- Signaux : `videos_total`, `videos_recentes`, `acceleration`, `createurs_recents`, `surperformance`, `engagement`, `serie` (jsonb : liste de `{jour, videos}`), `signal_faible` (bool), `vu_jusqu_au` (date), `imprevu` (bool), `videos_decollage`.
- Preuve dans la vidéo : `part_hors_legende` (0 à 1 : part des vidéos dont la légende et les hashtags ne disent rien du sujet), `videos_lues`, `canaux` (jsonb : paroles, texte à l'écran, légende → nombre de vidéos), `reactions` (jsonb : réaction dominante des commentaires → nombre de vidéos), `citations` (jsonb : liste de `{video, compte, canal, citation, url, seconde, image}` ; `seconde` et `image` peuvent manquer), `tons` (jsonb : ton → nombre de vidéos).
- Vidéo pivot : `video_declencheur`, `declencheur_avant` et `declencheur_apres` (vidéos du sujet dans les 48 heures avant et après).
- Fiche : `pourquoi_ca_monte`, `angle_brut`, `format_brut`, `prudence`.
- Couverture : `couvert` (bool), `couvert_par_brut` (bool), `couverture_presse_depuis` (date), `couverture_concurrents_depuis` (date), `couverture_complete` (bool).
- Campagne : `campagne` (bool : sujet de la campagne 2027), `personnalites` (text[]), `camps` (jsonb : camp politique → nombre de personnalités).
- Local : `regions` (jsonb : région → nombre de vidéos rattachées), `foyer` (région où le sujet est né, ou nul), `local_vers_national` (bool).
- X : `x_tweets`, `x_premier`, `x_avant_videos` (bool), `x_exemples`.

`topic_positions` : `topic_id`, `ordre`, `libelle`, `resume`, `nb_videos`, `vues`, `partages`.

`topic_coverage` : `topic_id`, `media`, `groupe` (brut, concurrent, traditionnel, droite, gauche), `titre`, `url`, `date`, `similarite`.

`videos` : `id`, `topic_id`, `position`, `account`, `platform`, `published_at`, `url`, `contenu`, `sujet`, `ton`, `affirmation`, `canal`, `legende_suffit`, `citation`, `reaction_public`, `miniature` (URL d'image), `views`, `likes`, `shares`, `comments`, `followers`, `est_declencheur`, `est_phare`.

`brief` : `id`, `ordre`, `topic_id`, `titre`, `etat`, `pourquoi`, `angle`, `format`, `deja_traite_par` (text[]), `valide` (bool).

`personnalites` : `rang`, `nom`, `parti`, `camp` (extrême gauche, gauche radicale, gauche, écologistes, centre, droite, souverainistes, extrême droite, divers, international ; nul = non classée), `tendance` (monte, stable, baisse), `solde` (de −1 à +1 : favorable moins critique et ironique), `part_de_voix` (0 à 1 : part des vues récentes parmi les personnalités françaises), `surperformance` (vues ÷ abonnés, médiane), `taux_engagement`, `serie`, `video_phare`, `video_phare_url`, `video_phare_compte`, `video_phare_traitement`, `hors_liste` (bool), `videos_total`, `videos_recentes`, `acceleration`, `createurs_recents`, `tons` (jsonb : favorable, critique, ironique, neutre → nombre), `reactions` (jsonb), `vues`, `interactions`, `affirmations` (text[]), et pour les sondages `sondage`, `sondages_serie`, `historique_videos`, `teste_depuis`, `colonne_propre_depuis`, `surexposition_videos`, `surexposition_presse`, `visibilite_comparable`.

`sondages` : une ligne par score (`institut`, `date`, `candidat`, `nom`, `score`, `hypothese_principale`, `autres`, `premier_releve`). `sondages_releves` : `releve_le`, `sondages`, `dernier_sondage`, `source`.

`comptes_eclaireurs` : `rang`, `compte`, `plateforme` (tiktok, instagram, x), `abonnes`, `url`, `region`, `type`, `bio`, `nb_sujets` (sujets sur lesquels le compte a publié dans le premier quart), `avance_moyenne_jours`, `sujets` (text[]), `exemple_url`.

Le schéma exact est dans `supabase/schema.sql` et les fichiers `supabase/migration_*.sql`.

## Radar

La liste des sujets triés par `rang`. Une ligne compacte par sujet :

- le titre ;
- l'état en badge : « à traiter maintenant » et « course de vitesse » en évidence, « à surveiller » et « signal faible » en second, « stable », « en baisse » et « angle mort durable » discrets ;
- un badge « Signal faible » si `signal_faible` est vrai (infobulle : « Sujet neuf, porté par plusieurs créateurs, encore trop petit pour être une tendance : à regarder avant les autres »), avec la date « vidéos lues jusqu'au [vu_jusqu_au] » ;
- un badge « Imprévu » si `imprevu` est vrai (infobulle : « Trouvé sans mot-clé : aucun thème suivi ne l'avait prévu ») ;
- une pastille « Sud-Ouest » si `foyer` vaut « Sud-Ouest » ;
- une mini-courbe des vidéos par jour, à partir de `serie` ;
- les signaux en petits chiffres libellés : accélération (« ×3,4 »), créateurs récents, surperformance (« ×4,2 vues/abonnés »), engagement ;
- « Lu dans la vidéo : X % » à partir de `part_hors_legende` (infobulle : « Part des vidéos dont la légende et les hashtags ne disent rien du sujet : il n'apparaît que dans les paroles ou le texte à l'écran ») ;
- la couverture : les médias de `topic_coverage`, avec Brut mis à part (« Brut : pas encore » ou « Brut : traité »). Si aucun média ne l'a traité, on n'écrit jamais seulement « non traité » mais « Non traité par la presse suivie depuis le [couverture_presse_depuis], ni par les concurrents depuis le [couverture_concurrents_depuis] », avec « couverture incomplète » en discret si `couverture_complete` est faux.

Filtres : « Campagne 2027 », « Politique » ou « Tout » (« Politique » par défaut, parce que les premiers sujets du radar non filtré ne sont pas toujours politiques), personnalité, camp politique, thème, état, « Peu couverts par les médias ». Les sujets de campagne affichent les personnalités citées en petites étiquettes.

Pas de score global sur 100 : on affiche le rang et les signaux.

Style : un outil de travail de rédaction, sobre et dense. Fond clair, texte presque noir, une seule couleur d'accent pour les états urgents, chiffres tabulaires. Ni dégradés, ni emojis.

## Fiche sujet

Une page par sujet, avec une adresse partageable.

1. En-tête : titre, badges d'état et « Imprévu », thèmes.
2. « Pourquoi ça monte » : le texte de `pourquoi_ca_monte`, la courbe de `serie` en grand, puis « La vidéo qui a fait basculer » : la vidéo marquée `est_declencheur` (miniature, compte, vues, lien) et la phrase « [declencheur_avant] vidéos sur le sujet dans les 48 h avant elle, [declencheur_apres] dans les 48 h après ».
3. « La preuve est dans la vidéo », section mise en valeur : « [part_hors_legende en %] des [videos_lues] vidéos lues n'en parlent ni dans leur légende ni dans leurs hashtags ». Dessous, les `citations` : chacune entre guillemets français, avec un badge du canal (« dit » pour les paroles, « écrit à l'écran » pour le texte à l'écran), le compte, « à 0:12 » si `seconde` existe, l'image si elle existe, et le lien vers la vidéo. Ce sont des extraits exacts, jamais reformulés.
4. « Ce que les vidéos en disent » : les positions de `topic_positions` triées par `ordre`, avec libellé, résumé, nombre de vidéos et vues. Une barre horizontale montre la part de chaque position. Un clic sur une position liste ses vidéos (`videos.position = libelle`). Sous les positions, la répartition de `reactions` : « Dans les commentaires : rejet 12, moquerie 5 ».
5. « Sur X » : le nombre de tweets rapprochés, la date du premier, quelques exemples (`x_exemples`) et un badge « sur X avant TikTok » si `x_avant_videos` est vrai.
6. « Qui l'a déjà traité » : `topic_coverage` (média, titre cliquable, date). Si la liste est vide : « Aucun média suivi n'a traité ce sujet ».
7. « Pour Brut » : l'angle proposé (`angle_brut`), le format proposé (`format_brut`) et, dans un encadré visible, « À vérifier avant de traiter » (`prudence`).
8. En bas, les vidéos phares (`est_phare`) en grille simple.

Les liens Instagram sans `/p/` ni `/reel/` pointent vers le compte et non vers la publication : l'interface écrit alors « lien vers le compte ».

Chaque chiffre renvoie à ses vidéos sources.

## Brief du matin

Les lignes de `brief` triées par `ordre`, présentées comme une note à lire en deux minutes. Pour chacune : titre (lien vers la fiche), état, « pourquoi », « angle », « format », « déjà traité par ». Une case « Valider » met à jour `brief.valide`. Mention en bas : « Proposition générée par IA à partir des vidéos sources : à valider par la rédaction. »

## Campagne

La table `personnalites`, sans les lignes dont `camp` vaut « international ».

1. « Qui monte » : les personnalités dont `tendance` vaut « monte », en grandes cartes (nom, parti, accélération, mini-courbe, vidéos récentes, créateurs récents).
2. Un tableau comparatif triable : nom et parti, camp, tendance, part de voix, accélération, vidéos récentes, surperformance, taux d'engagement, une barre empilée « comment les vidéos le présentent » (`tons`), le `solde` coloré de −1 à +1, et « dans les commentaires » (`reactions`).
3. Un filtre par camp, et un regroupement par camp qui additionne `part_de_voix` et moyenne `solde`.
4. La fiche d'une personnalité : la courbe en grand, la vidéo phare, deux `affirmations`, et la liste des sujets où elle apparaît.
5. Les personnalités `hors_liste` portent un badge « Repérée seule : absente de nos listes ».

Lecture : un solde positif veut dire que les vidéos la présentent plutôt favorablement. Une surperformance supérieure à 1 veut dire que ses vidéos font plus de vues que l'audience habituelle de leurs créateurs.

Section « Sondages et visibilité » :

- un nuage de points, avec en abscisse la part de chaque candidat dans les sondages et en ordonnée sa part des vues, en échelles logarithmiques, une diagonale « visibilité = poids dans les sondages » et la couleur du point selon `solde` ;
- dans la fiche d'une personnalité, deux graphiques l'un au-dessus de l'autre sur le même axe du temps (jamais deux axes verticaux sur un même graphique) : en haut ses vidéos par semaine, en bas ses sondages, un point par sondage et la moyenne sur 14 jours ;
- pour une personnalité sans sondage, la phrase `visibilite_comparable` (« aussi visible dans les vidéos que Lisnard, sondé à 6,2 % ») et jamais un score estimé ;
- en bas : « Sondages recensés par Wikipédia, relevé du [dernier `sondages_releves.releve_le`] ».

Mentions en bas d'écran : « Vidéos lues sur TikTok et Instagram : ce n'est pas un sondage. » et « Partis et camps classés par l'équipe, à vérifier. »

## Sud-Ouest et comptes éclaireurs

1. « Nés dans le Sud-Ouest » : les sujets dont `foyer` vaut « Sud-Ouest », avec un badge « Local → national » si `local_vers_national` est vrai, la part de vidéos locales et le lien vers la fiche.
2. « Comptes à suivre » : `comptes_eclaireurs`, ceux de la région d'abord. Pour chacun : le compte (lien), la plateforme, les abonnés, « a publié tôt sur N sujets, en moyenne X jours avant la majorité », les sujets, un exemple de vidéo. Phrase d'explication : « Comptes peu connus (5 000 à 150 000 abonnés sur TikTok et Instagram, dès 500 sur X) qui publient en premier sur des sujets qui grossissent ensuite. Hors grands médias ; chaque compte est typé créateur, média local ou élu : ce sont des sources à vérifier. »

Mentions : « Région de démonstration : Sud-Ouest. Ajouter une région = une liste de villes et de médias locaux. » et « Oriane n'indexe pas les comptes de moins de 5 000 abonnés. »
