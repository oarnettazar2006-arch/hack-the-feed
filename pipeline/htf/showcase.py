"""Fiches sujets rédigées par Opus (seulement pour les sujets affichés) et brief du matin assemblé sans appel en plus."""
import json
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from . import config, llm, store

SYSTEM = """Tu aides l'éditeur du matin de Brut, média vidéo d'information pour les 18-35 ans, à décider quoi traiter.
On te donne un sujet qui circule sur TikTok et Instagram : ses chiffres, les médias qui l'ont déjà traité, et ce que chaque vidéo affirme.

Écris une fiche factuelle :
- titre : 10 mots maximum, neutre, comme un titre de conducteur de rédaction ;
- pourquoi_ca_monte : 2 phrases maximum, uniquement à partir des chiffres et des vidéos fournis, sans rien inventer ;
- positions : 2 ou 3 positions réellement présentes dans les vidéos, qui s'opposent ou se distinguent. Pour chacune, un libellé court, une phrase de résumé, et la liste des identifiants de vidéos qui la portent. Une vidéo purement informative va dans une position « explique le sujet » si elles sont nombreuses, sinon nulle part. L'ironie compte comme la position qu'elle sert ;
- angle_brut : une phrase, l'angle que Brut pourrait prendre, en tenant compte de ce que les autres médias ont déjà fait ;
- prudence : une phrase sur ce qu'il faut vérifier avant de traiter le sujet (source, représentativité, risque de manipulation), ou chaîne vide.

Pas de chiffre qui ne figure pas dans les données. Pas de jugement sur les créateurs. Français simple."""


class Position(BaseModel):
    libelle: str
    resume: str
    videos: list[str]


class Card(BaseModel):
    titre: str
    pourquoi_ca_monte: str
    positions: list[Position]
    angle_brut: str
    prudence: str


def _prompt(topic: dict, local: dict[str, str]) -> str:
    reverse = {v: k for k, v in local.items()}
    s = topic["signaux"]
    lines = [
        f"Sujet type : {topic['sujet_type']}",
        f"Thèmes : {', '.join(topic['themes'])}",
        f"Vidéos : {topic['videos_total']} au total, {topic['videos_recentes']} sur les {config.WINDOW_RECENT} derniers jours",
        f"Accélération (vidéos par jour récentes / habituelles) : x{s['acceleration']}",
        f"Créateurs différents sur la période récente : {s['createurs_recents']}",
        f"Surperformance médiane (vues / abonnés) : {s['surperformance_mediane']}",
        f"Tons : {json.dumps(topic['tons'], ensure_ascii=False)}",
        (f"Signal : {topic['coordination']['videos']} vidéos de {topic['coordination']['comptes']} comptes différents "
         f"reprennent un texte presque identique en moins de 48 h ({int(topic['coordination']['part'] * 100)} % du sujet)."
         if topic.get("coordination") else "Pas de signal de publication coordonnée."),
        "Couverture médias : " + ("; ".join(f"{c['media']} ({c['date'][:10]}) : {c['titre']}" for c in topic["couverture"])
                                  or "aucun média de notre base n'a traité ce sujet"),
        "",
        "Ce qu'affirme chaque vidéo :",
    ]
    lines += [f"[{reverse[a['video']]}] ({a['ton']}) {a['affirmation']}" for a in topic["affirmations"]]
    return "\n".join(lines)


def build_cards(run_id: str, topics: list[dict], top: int) -> list[dict]:
    items = {i["id"]: i for i in store.load_items("social")}

    def card_for(topic: dict) -> dict:
        local = {f"v{n}": a["video"] for n, a in enumerate(topic["affirmations"])}
        card = llm.structured(
            run_id=run_id, purpose="fiche sujet", model=config.MODEL_SHOWCASE, effort=config.EFFORT_SHOWCASE,
            system=SYSTEM, prompt=_prompt(topic, local), schema=Card, max_tokens=6000,
        )
        positions = []
        for p in card.positions:
            vids = [local[v] for v in p.videos if v in local]
            metrics = [items[v]["metrics"] for v in vids]
            positions.append({
                "libelle": p.libelle, "resume": p.resume, "videos": vids,
                "nb_videos": len(vids),
                "vues": sum(m.get("views") or 0 for m in metrics),
                "partages": sum(m.get("shares", 0) for m in metrics),
            })
        return {**topic, "titre": card.titre, "pourquoi_ca_monte": card.pourquoi_ca_monte,
                "positions": positions, "angle_brut": card.angle_brut, "prudence": card.prudence}

    with ThreadPoolExecutor(max_workers=config.SHOWCASE_WORKERS) as pool:
        cards = list(pool.map(card_for, topics[:top]))  # garde l'ordre du classement
    return cards + topics[top:]


PRIORITY = ["à traiter maintenant", "course de vitesse", "à surveiller", "angle mort durable"]


def morning_brief(cards: list[dict], size: int = 5) -> list[dict]:
    """Les sujets à proposer en conférence de rédaction : d'abord ce qui monte et n'est pas couvert."""
    candidates = [c for c in cards if c.get("titre") and c["politique"] and c["etat"] in PRIORITY]
    candidates.sort(key=lambda c: (PRIORITY.index(c["etat"]), c["rang"]))
    return [{"sujet": c["id"], "titre": c["titre"], "etat": c["etat"], "pourquoi": c["pourquoi_ca_monte"],
             "angle": c["angle_brut"], "deja_traite_par": sorted({x["media"] for x in c["couverture"]}),
             "valide": False} for c in candidates[:size]]
