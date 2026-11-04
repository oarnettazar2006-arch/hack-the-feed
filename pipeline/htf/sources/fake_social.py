"""Fausses vidéos TikTok/Instagram pour tester le pipeline avant d'avoir l'API Oriane.

Les sujets sont fictifs et ne citent aucune personne réelle. Chaque sujet suit une dynamique connue
(qui monte, stable, qui retombe), ce qui permet de vérifier que le score d'émergence la retrouve.
"""
import random
from datetime import datetime, timedelta, timezone

from .. import store

# daily(d) = nombre de vidéos le jour d (0 = il y a 16 jours, 16 = aujourd'hui).
TOPICS = {
    "loyers_etudiants": {
        "daily": lambda d: 1 if d < 12 else [6, 14, 25, 38, 45][d - 12],
        "overperf": 4.0,
        "lines": {
            "contre": ["Mon loyer étudiant vient de prendre 90 euros d'un coup, pour 14 mètres carrés.",
                       "On paie 650 euros pour une chambre sans fenêtre, et personne ne fait rien.",
                       "J'ai dû abandonner mon master parce que je ne trouvais pas de logement à moins de 700 euros."],
            "pour": ["Les propriétaires aussi subissent la hausse des charges, il faut le dire.",
                     "Encadrer les loyers, ça fait fuir les bailleurs, et au final il y a encore moins de logements."],
            "ironique": ["POV : tu visites un 9 mètres carrés à 720 euros et l'agent te dit que c'est une affaire.",
                         "Nouvelle tendance : dormir dans sa voiture pour finir sa licence, très chic."],
            "informatif": ["Les loyers des petites surfaces ont augmenté dans les grandes villes universitaires, voici les chiffres de l'observatoire."],
        },
        "screen": ["LOYER : +90€", "9m² = 720€ ???", "Étudiants à la rue"],
        "visual": ["une étudiante filme une chambre minuscule", "capture d'une annonce immobilière", "un étudiant face caméra dans sa voiture"],
        "captions": ["ma vie d'étudiante 🥲", "c'est normal ça ?", "#fyp #etudiant"],
    },
    "prix_carburant": {
        "daily": lambda d: 30 + (d % 3) * 3,
        "overperf": 0.8,
        "lines": {
            "contre": ["Le plein à plus de 100 euros, pour aller bosser c'est intenable.",
                       "Les taxes représentent plus de la moitié du prix à la pompe."],
            "pour": ["Le prix du carburant reflète le marché mondial, l'État ne peut pas tout compenser."],
            "ironique": ["Je vais au travail à cheval, au moins le foin est stable."],
            "informatif": ["Voici comment se décompose le prix d'un litre de gazole cette semaine."],
        },
        "screen": ["2,05€ le litre", "PLEIN = 110€"],
        "visual": ["un automobiliste devant une pompe à essence", "un graphique des prix du carburant"],
        "captions": ["ça devient n'importe quoi", "#essence #prix"],
    },
    "uniforme_ecole": {
        "daily": lambda d: max(1, 20 - d * 2),
        "overperf": 0.6,
        "lines": {
            "pour": ["L'uniforme, ça efface les différences sociales entre les élèves.",
                     "Moins de harcèlement sur les marques, c'est déjà une victoire."],
            "contre": ["L'uniforme coûte cher aux familles et ne règle aucun problème de fond.",
                       "On parle d'uniforme pendant que les classes n'ont pas de prof."],
            "ironique": ["Premier jour d'uniforme : tout le monde ressemble à un stagiaire de banque."],
            "informatif": ["Voici les résultats de l'expérimentation de l'uniforme dans les établissements pilotes."],
        },
        "screen": ["UNIFORME : POUR OU CONTRE ?", "Bilan de l'expérimentation"],
        "visual": ["des collégiens en uniforme bleu marine", "une enseignante face caméra"],
        "captions": ["vous en pensez quoi ?", "#ecole"],
    },
    "ia_emplois_juniors": {
        "daily": lambda d: 2 if d < 10 else [4, 5, 7, 9, 12, 15, 18][d - 10],
        "overperf": 2.5,
        "lines": {
            "contre": ["Mon stage a été annulé, la boîte dit que l'IA fait le travail des juniors maintenant.",
                       "Plus aucune offre de premier emploi en traduction, tout est passé à l'IA."],
            "pour": ["L'IA libère du temps pour des tâches plus intéressantes, il faut se former au lieu de pleurer.",
                     "Ceux qui maîtrisent l'IA trouvent des postes plus vite que les autres."],
            "ironique": ["Mon manager m'a remplacé par une IA, l'IA a démissionné au bout de deux jours."],
            "informatif": ["Ce que dit la dernière enquête sur les embauches de jeunes diplômés dans les métiers exposés à l'IA."],
        },
        "screen": ["Remplacé par une IA ?", "0 offre junior"],
        "visual": ["un jeune diplômé montre une lettre de refus", "capture d'un site d'offres d'emploi vide"],
        "captions": ["storytime", "#emploi #ia"],
    },
    "maternites_rurales": {
        "daily": lambda d: 0 if d < 11 else [2, 3, 4, 6, 8, 10][d - 11],
        "overperf": 5.0,
        "lines": {
            "contre": ["La maternité de notre ville ferme, la prochaine est à une heure et quart de route.",
                       "Accoucher sur le bord de la route, c'est ça l'égalité territoriale ?"],
            "pour": ["Regrouper les maternités garantit plus de sécurité avec des équipes complètes."],
            "ironique": ["Conseil aux futures mamans du coin : prévoyez un GPS et un thermos."],
            "informatif": ["Carte des maternités qui ont fermé ces dix dernières années dans les zones rurales."],
        },
        "screen": ["MATERNITÉ FERMÉE", "1h15 de route pour accoucher"],
        "visual": ["un rassemblement devant un hôpital de petite ville", "une sage-femme témoigne face caméra"],
        "captions": ["on lâche rien", "partagez svp"],
    },
    "videosurveillance_gares": {
        "daily": lambda d: 3 if d < 9 else [5, 6, 8, 10, 12, 14, 16, 18][d - 9],
        "overperf": 3.0,
        "lines": {
            "contre": ["Les caméras algorithmiques dans les gares, c'est la surveillance de masse qui s'installe sans débat.",
                       "Un logiciel qui décide qui a un comportement suspect, ça ne vous fait pas peur ?"],
            "pour": ["Si ça permet de retrouver un bagage abandonné plus vite, je signe tout de suite.",
                     "On veut plus de sécurité dans les transports, il faut des outils modernes."],
            "ironique": ["J'ai couru pour attraper mon train, l'algorithme m'a classé comme menace nationale."],
            "informatif": ["Comment fonctionne la vidéosurveillance algorithmique testée dans les grandes gares."],
        },
        "screen": ["Filmé et analysé", "Caméras IA en gare"],
        "visual": ["des caméras au plafond d'un hall de gare", "un voyageur qui court sur un quai"],
        "captions": ["on en parle ?", "#train"],
    },
    # Bruit : doit être écarté par le filtre d'intérêt public.
    "drama_influenceurs": {
        "daily": lambda d: 5 if d < 13 else [20, 40, 60, 70][d - 13],
        "overperf": 6.0,
        "lines": {
            "informatif": ["Toute l'histoire de la dispute entre les deux influenceuses beauté, je vous explique.",
                           "Elle a supprimé sa vidéo d'excuses, voici ce qu'elle disait."],
            "ironique": ["Les deux qui se clashent en story pendant que leur marque de gloss sort demain, hasard ?"],
        },
        "screen": ["LE CLASH", "Elle répond enfin"],
        "visual": ["une créatrice commente des captures de stories"],
        "captions": ["le thé est chaud ☕", "#drama"],
    },
    "recettes": {
        "daily": lambda d: 15,
        "overperf": 1.0,
        "lines": {"informatif": ["Recette de pâtes au citron en dix minutes, parfait pour les étudiants.",
                                 "Mon astuce pour un gâteau moelleux sans beurre."]},
        "screen": ["10 MIN", "Recette facile"],
        "visual": ["des mains qui cuisinent dans une petite cuisine"],
        "captions": ["recette du jour", "#food"],
    },
    # Sujet réel de la semaine (présent dans la presse) : sert à tester la couverture médias.
    "blocages_lycees": {
        "daily": lambda d: 1 if d < 10 else [3, 6, 9, 12, 14, 15, 16][d - 10],
        "overperf": 2.0,
        "lines": {
            "contre": ["Les CRS ont gazé des lycéens devant mon lycée ce matin, on avait juste bloqué l'entrée.",
                       "On manifeste pacifiquement et on se fait traiter comme des délinquants."],
            "pour": ["Bloquer un lycée empêche ceux qui veulent étudier d'aller en cours, la police fait son travail."],
            "ironique": ["Programme du jour au lycée : maths, histoire, et cours pratique de gaz lacrymogène."],
            "informatif": ["Pourquoi les lycéens bloquent leurs établissements depuis la rentrée des vacances, on vous explique."],
        },
        "screen": ["BLOCUS", "Lycéens gazés ?", "Pourquoi on bloque"],
        "visual": ["des poubelles devant l'entrée d'un lycée", "des CRS face à des lycéens", "une lycéenne face caméra"],
        "captions": ["on lâche rien ✊", "#blocus #lycee"],
    },
    # Personnalité fictive qui émerge, absente des listes de noms : l'outil doit la repérer seul.
    "candidature_surprise": {
        "daily": lambda d: 0 if d < 12 else [2, 5, 9, 14, 18][d - 12],
        "overperf": 4.5,
        "lines": {
            "pour": ["Hugo Vernay, le maire qui a baissé les impôts locaux, annonce sa candidature, enfin quelqu'un de concret.",
                     "Hugo Vernay candidat en 2027 : un élu de terrain face aux appareils de partis, ça change."],
            "contre": ["Hugo Vernay se déclare candidat mais personne ne connaît son programme, c'est du marketing.",
                       "La candidature d'Hugo Vernay, c'est un coup de com' sans aucune équipe derrière."],
            "ironique": ["Hugo Vernay candidat, prochaine étape : président du conseil syndical de mon immeuble."],
            "informatif": ["Qui est Hugo Vernay, le maire qui vient d'annoncer sa candidature à la présidentielle ?"],
        },
        "screen": ["Hugo Vernay candidat", "QUI EST HUGO VERNAY ?", "2027 : un nouveau candidat"],
        "visual": ["un homme en costume annonce sa candidature devant une mairie", "extrait d'un journal télévisé régional"],
        "captions": ["vous le connaissiez ?", "#presidentielle2027"],
    },
}

CREATOR_POOL = 400


def generate(seed: int = 7, days: int = 17, scale: float = 1.0) -> int:
    """Génère les vidéos et les enregistre. `scale` réduit le volume pour les tests (0.1 = ~10 %)."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    creators = {f"@createur{i:03d}": int(rng.lognormvariate(9, 1.5)) + 200 for i in range(CREATOR_POOL)}
    names = list(creators)
    items = []
    for topic, spec in TOPICS.items():
        stances = list(spec["lines"])
        for d in range(days):
            for n in range(round(spec["daily"](d) * scale)):
                stance = rng.choice(stances)
                creator = rng.choice(names)
                followers = creators[creator]
                views = int(followers * spec["overperf"] * rng.lognormvariate(0, 0.6))
                when = now - timedelta(days=days - 1 - d, hours=rng.randint(0, 11), minutes=rng.randint(0, 59))
                items.append({
                    "id": f"fake:{topic}:{d}:{n}",
                    "kind": "social",
                    "source": "fake",
                    "account": creator,
                    "published_at": when.isoformat(),
                    "url": None,
                    "text": (
                        f"Paroles : {rng.choice(spec['lines'][stance])}\n"
                        f"Texte à l'écran : {rng.choice(spec['screen'])}\n"
                        f"Image : {rng.choice(spec['visual'])}\n"
                        f"Légende : {rng.choice(spec['captions'])}"
                    ),
                    "metrics": {
                        "views": views,
                        "likes": int(views * rng.uniform(0.03, 0.12)),
                        "shares": int(views * rng.uniform(0.002, 0.02)),
                        "comments": int(views * rng.uniform(0.001, 0.01)),
                        "followers": followers,
                        "platform": rng.choice(["tiktok", "instagram"]),
                        "truth_topic": topic,      # vérité terrain, pour évaluer le regroupement
                        "truth_stance": stance,
                        # La candidature surprise simule un sujet ramené uniquement par le filet aveugle.
                        "theme_query": "veille ouverte" if topic == "candidature_surprise" else "fake",
                    },
                })
    return store.upsert_items(items)
