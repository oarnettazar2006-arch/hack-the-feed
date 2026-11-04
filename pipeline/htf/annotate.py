"""Annotation par Haiku : chaque vidéo et chaque contenu média devient une phrase de sujet neutre.

Les vidéos et les articles reçoivent la même consigne de normalisation, pour que leurs vecteurs soient comparables.
Chaque élément n'est annoté qu'une fois (table `annotations`).
"""
from typing import Literal

from pydantic import BaseModel

from . import config, llm, store

VERSION = "v2"  # v2 : ajout des personnalités citées

SUJET_RULES = """Règles pour « sujet » :
- une phrase neutre de 6 à 15 mots qui dit de quoi on parle concrètement, comme un titre de dépêche AFP ;
- jamais d'opinion, d'ironie, d'émotion ni de « je » ;
- garder les précisions utiles (lieu, public concerné, mesure) mais pas les chiffres anecdotiques ;
- deux contenus sur le même fait doivent avoir des sujets presque identiques, qu'ils viennent d'un TikTok ou d'un journal."""

SOCIAL_SYSTEM = f"""Tu analyses des vidéos TikTok et Instagram françaises pour la rédaction de Brut.
Chaque vidéo est décrite par ses paroles, le texte à l'écran, une description de l'image et sa légende.
Les paroles, le texte à l'écran et l'image comptent plus que la légende.
Les « commentaires populaires » sont la réaction du public : ils aident à comprendre le contexte,
mais « ton » et « affirmation » décrivent la vidéo elle-même, pas ses commentaires.

{SUJET_RULES}

Autres champs :
- politique : vrai si le sujet relève du débat public ou de l'action publique (lois, services publics, économie, société, élus) ;
- interet_public : faux pour le divertissement, les clashs entre influenceurs, les recettes, la mode, le sport sans enjeu de société ;
- themes : 1 à 3 thèmes pris uniquement dans cette liste : {", ".join(config.THEMES)} ;
- ton : favorable, critique, ironique (moquerie, second degré), informatif (explique sans prendre parti), incertain (impossible à dire) ;
- affirmation : en une phrase, ce que la vidéo affirme ou défend sur le sujet, reformulé sans citer le créateur ;
- personnalites : prénom et nom complets, orthographe officielle, des personnalités publiques (élus, candidats,
  ministres, militants connus, dirigeants) citées, montrées ou visées par la vidéo. Liste vide s'il n'y en a pas.
  Jamais le créateur de la vidéo ni une personne privée.

Réponds pour chaque vidéo, avec son identifiant."""

MEDIA_SYSTEM = f"""Tu normalises des titres d'articles et de vidéos de médias français pour les comparer à des sujets venus des réseaux sociaux.

{SUJET_RULES}

themes : 1 à 3 thèmes pris uniquement dans cette liste : {", ".join(config.THEMES)}.

Réponds pour chaque contenu, avec son identifiant."""


class SocialNote(BaseModel):
    id: str
    sujet: str
    politique: bool
    interet_public: bool
    themes: list[str]
    ton: Literal["favorable", "critique", "ironique", "informatif", "incertain"]
    affirmation: str
    personnalites: list[str]


class SocialBatch(BaseModel):
    notes: list[SocialNote]


class MediaNote(BaseModel):
    id: str
    sujet: str
    themes: list[str]


class MediaBatch(BaseModel):
    notes: list[MediaNote]


def _annotate(kind: str, run_id: str, limit: int | None, batch_size: int) -> dict:
    items = store.load_items(kind)
    done = store.get_annotations(VERSION)
    todo = [i for i in items if i["id"] not in done][:limit]
    system, schema, per_item = (
        (SOCIAL_SYSTEM, SocialBatch, 160) if kind == "social" else (MEDIA_SYSTEM, MediaBatch, 90)
    )
    annotated = 0
    for start in range(0, len(todo), batch_size):
        chunk = todo[start:start + batch_size]
        local = {f"e{n}": item["id"] for n, item in enumerate(chunk)}
        prompt = "\n\n".join(f"[e{n}]\n{item['text']}" for n, item in enumerate(chunk))
        result = llm.structured(
            run_id=run_id, purpose=f"annotation {kind}", model=config.MODEL_BULK, effort=config.EFFORT_BULK,
            system=system, prompt=prompt, schema=schema, max_tokens=400 + per_item * len(chunk), thinking=False,
        )
        notes = {local[n.id]: n.model_dump(exclude={"id"}) for n in result.notes if n.id in local}
        store.save_annotations(VERSION, notes)
        annotated += len(notes)
    return {"à faire": len(todo), "annotés": annotated, "dépense de l'exécution ($)": round(store.spent(run_id), 4)}


def annotate_social(run_id: str, limit: int | None = None) -> dict:
    return _annotate("social", run_id, limit, batch_size=10)


def annotate_media(run_id: str, limit: int | None = None) -> dict:
    return _annotate("media", run_id, limit, batch_size=20)
