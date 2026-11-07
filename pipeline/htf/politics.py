"""Repères politiques : famille politique des personnalités suivies, pour filtrer et comparer les campagnes.

Classement fait par l'équipe (étiquette du parti ou du mouvement au 7/11/2026), à vérifier avant diffusion.
Une personnalité absente de la table reste « non classée » : on ne devine jamais un camp.
"""
from .analyze import _name_key

# nom → (parti ou mouvement, camp)
AFFILIATIONS = {
    "Édouard Philippe": ("Horizons", "centre"),
    "Gabriel Attal": ("Renaissance", "centre"),
    "Olivier Becht": ("Renaissance", "centre"),
    "Emmanuel Macron": ("Renaissance", "centre"),
    "Dominique de Villepin": ("La France humaniste", "centre"),
    "Bernard Cazeneuve": ("La Convention", "gauche"),
    "Karim Bouamrane": ("PS", "gauche"),
    "François Hollande": ("PS", "gauche"),
    "Olivier Faure": ("PS", "gauche"),
    "Ségolène Royal": ("divers gauche", "gauche"),
    "Raphaël Glucksmann": ("Place publique", "gauche"),
    "François Ruffin": ("Debout !", "gauche"),
    "Fabien Roussel": ("PCF", "gauche"),
    "Jean-Luc Mélenchon": ("LFI", "gauche radicale"),
    "Marine Tondelier": ("Les Écologistes", "écologistes"),
    "Delphine Batho": ("Génération écologie", "écologistes"),
    "Nathalie Arthaud": ("Lutte ouvrière", "extrême gauche"),
    "Anasse Kazib": ("Révolution permanente", "extrême gauche"),
    "Selma Labib": ("NPA", "extrême gauche"),
    "Bruno Retailleau": ("LR", "droite"),
    "Laurent Wauquiez": ("LR", "droite"),
    "Xavier Bertrand": ("divers droite", "droite"),
    "David Lisnard": ("Nouvelle Énergie", "droite"),
    "Nicolas Dupont-Aignan": ("Debout la France", "souverainistes"),
    "Florian Philippot": ("Les Patriotes", "souverainistes"),
    "François Asselineau": ("UPR", "souverainistes"),
    "Marine Le Pen": ("RN", "extrême droite"),
    "Jordan Bardella": ("RN", "extrême droite"),
    "Éric Zemmour": ("Reconquête", "extrême droite"),
    "Sarah Knafo": ("Reconquête", "extrême droite"),
    "Marion Maréchal": ("Identité-Libertés", "extrême droite"),
    "Juan Branco": ("sans parti", "divers"),
    "Natacha Polony": ("sans parti", "divers"),
    "Francis Lalanne": ("sans parti", "divers"),
    "Clara Egger": ("Espoir RIC", "divers"),
    # Hors listes de candidats, repérées dans les vidéos du 7/11 (gardent leur badge « repérée seule »).
    "Roland Lescure": ("Renaissance", "centre"),
    "Julien Odoul": ("RN", "extrême droite"),
    "Ali Rabeh": ("Génération.s", "gauche"),
}

# Personnalités étrangères très citées : jamais signalées comme « repérées seules » dans la campagne française.
INTERNATIONAL = ["Donald Trump", "Vladimir Poutine", "Volodymyr Zelensky", "Benyamin Netanyahou", "Joe Biden",
                 "Kamala Harris", "Elon Musk", "Xi Jinping", "Giorgia Meloni", "Friedrich Merz", "Keir Starmer",
                 "Mark Carney", "Flavio Bolsonaro", "Jair Bolsonaro", "Christine Lagarde", "Ursula von der Leyen"]

CAMP_ORDER = ["extrême gauche", "gauche radicale", "gauche", "écologistes", "centre", "droite",
              "souverainistes", "extrême droite", "divers"]

_BY_KEY = {_name_key(n): v for n, v in AFFILIATIONS.items()}
_BY_LAST = {}
for _n, _v in AFFILIATIONS.items():
    _BY_LAST.setdefault(_name_key(_n).split()[-1], []).append(_v)
_INTL = {_name_key(n) for n in INTERNATIONAL} | {_name_key(n).split()[-1] for n in INTERNATIONAL}


def affiliation(name: str) -> tuple[str | None, str | None]:
    """(parti, camp) d'une personnalité, ou (None, "international") / (None, None) si inconnue."""
    key = _name_key(name)
    if key in _BY_KEY:
        return _BY_KEY[key]
    # Nom seul (« Lisnard ») : rattaché s'il n'y a qu'une personnalité de ce nom. Jamais pour un nom complet
    # différent (« Brigitte Macron », « Jean-Marie Le Pen » ne sont pas candidats).
    last = _BY_LAST.get(key) if key and len(key.split()) == 1 else None
    if last and len(last) == 1:
        return last[0]
    if key in _INTL or (key and key.split()[-1] in _INTL):
        return None, "international"
    return None, None


# Classées (camp connu) mais pas candidates : leur seule présence ne fait pas d'un sujet un sujet de campagne.
NOT_RUNNING = {_name_key(n) for n in ("Emmanuel Macron", "Roland Lescure", "Ali Rabeh")}


def is_campaign_figure(name: str) -> bool:
    return affiliation(name)[1] not in (None, "international") and _name_key(name) not in NOT_RUNNING
