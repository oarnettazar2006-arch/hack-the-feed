"""Annotation par Haiku : chaque vidéo et chaque contenu média devient une phrase de sujet neutre.

Les vidéos et les articles reçoivent la même consigne de normalisation, pour que leurs vecteurs soient comparables.
Chaque élément n'est annoté qu'une fois (table `annotations`).
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from pydantic import BaseModel

from . import config, llm, store

# Vidéos : v3 (où se trouve la preuve dans la vidéo, citation exacte, traitement de chaque personnalité,
# réaction du public). Médias : v2, inchangé (évite de repayer les ~12 600 articles déjà annotés).
SOCIAL_VERSION = "v3"
MEDIA_VERSION = "v2"

SUJET_RULES = """Règles pour « sujet » :
- une phrase neutre de 6 à 15 mots qui dit de quoi on parle concrètement, comme un titre de dépêche AFP ;
- jamais d'opinion, d'ironie, d'émotion ni de « je » ;
- garder les précisions utiles (lieu, public concerné, mesure) mais pas les chiffres anecdotiques ;
- deux contenus sur le même fait doivent avoir des sujets presque identiques, qu'ils viennent d'un TikTok ou d'un journal."""

SOCIAL_SYSTEM = f"""Tu analyses des vidéos TikTok et Instagram françaises pour la rédaction de Brut.
Chaque vidéo est décrite par ses paroles (transcription), le texte écrit à l'écran, sa légende et ses hashtags.
Les paroles et le texte à l'écran comptent plus que la légende.
Les « commentaires populaires » sont la réaction du public : ils aident à comprendre le contexte,
mais « ton » et « affirmation » décrivent la vidéo elle-même, pas ses commentaires.

{SUJET_RULES}

Autres champs :
- politique : vrai si le sujet relève du débat public ou de l'action publique (lois, services publics, économie, société, élus) ;
- interet_public : faux pour le divertissement, les clashs entre influenceurs, les recettes, la mode, le sport sans enjeu de société ;
- themes : 1 à 3 thèmes pris uniquement dans cette liste : {", ".join(config.THEMES)} ;
- ton : favorable, critique, ironique (moquerie, second degré), informatif (explique sans prendre parti), incertain (impossible à dire) ;
- affirmation : en une phrase, ce que la vidéo affirme ou défend sur le sujet, reformulé sans citer le créateur ;
- personnalites : les personnalités publiques (élus, candidats, ministres, militants connus, dirigeants) citées,
  montrées ou visées par la vidéo, avec prénom et nom complets dans l'orthographe officielle, et pour chacune
  « traitement » : comment la vidéo la présente (favorable, critique, ironique, neutre). Liste vide s'il n'y en a pas.
  Jamais le créateur de la vidéo ni une personne privée ;
- canal : où le sujet est surtout exprimé : « paroles », « texte à l'écran » ou « légende » (le titre compte comme la légende) ;
- legende_suffit : vrai si on devine le sujet en lisant seulement la légende et les hashtags ; faux s'il n'apparaît
  que dans les paroles ou le texte à l'écran ;
- citation : 5 à 20 mots recopiés mot pour mot dans les paroles ou le texte à l'écran, ceux qui montrent le mieux
  l'affirmation. Ne jamais reformuler. Chaîne vide s'il n'y a ni paroles ni texte à l'écran ;
- reaction_public : ce que disent surtout les « commentaires populaires » fournis : soutien, rejet, moquerie,
  partagée (avis opposés). S'il n'y a pas de ligne « Commentaires populaires », toujours « sans commentaires » :
  ne jamais deviner la réaction du public.

Réponds pour chaque vidéo, avec son identifiant."""

MEDIA_SYSTEM = f"""Tu normalises des titres d'articles et de vidéos de médias français pour les comparer à des sujets venus des réseaux sociaux.

{SUJET_RULES}

themes : 1 à 3 thèmes pris uniquement dans cette liste : {", ".join(config.THEMES)}.

Réponds pour chaque contenu, avec son identifiant."""


class Personne(BaseModel):
    nom: str
    traitement: Literal["favorable", "critique", "ironique", "neutre"]


class SocialNote(BaseModel):
    id: str
    sujet: str
    politique: bool
    interet_public: bool
    themes: list[str]
    ton: Literal["favorable", "critique", "ironique", "informatif", "incertain"]
    affirmation: str
    personnalites: list[Personne]
    canal: Literal["paroles", "texte à l'écran", "légende"]
    legende_suffit: bool
    citation: str
    reaction_public: Literal["soutien", "rejet", "moquerie", "partagée", "sans commentaires"]


class SocialBatch(BaseModel):
    notes: list[SocialNote]


class MediaNote(BaseModel):
    id: str
    sujet: str
    themes: list[str]


class MediaBatch(BaseModel):
    notes: list[MediaNote]


def notes() -> dict[str, dict]:
    """Annotations à jour : médias en v2, vidéos en v3 (à défaut v2 pour les anciennes fausses vidéos de test)."""
    out = store.get_annotations(MEDIA_VERSION)
    out.update(store.get_annotations(SOCIAL_VERSION))
    return out


def names(note: dict) -> list[str]:
    """Noms des personnalités, quel que soit le format (v2 : texte, v3 : objet avec traitement)."""
    return [p if isinstance(p, str) else p["nom"] for p in note.get("personnalites") or []]


def treatment(note: dict, name: str) -> str:
    """Comment la vidéo présente une personnalité. À défaut (v2), déduit du ton de la vidéo."""
    for p in note.get("personnalites") or []:
        if isinstance(p, dict) and p["nom"] == name:
            return p["traitement"]
    return {"favorable": "favorable", "critique": "critique", "ironique": "ironique"}.get(note["ton"], "neutre")


def _words(text: str) -> set[str]:
    return set("".join(c.lower() if c.isalnum() else " " for c in text).split())


def _guard(note: dict, text: str) -> None:
    """Corrige ce que Haiku invente (mesuré le 5/11 : réaction donnée 10 fois sur 12 à des vidéos sans commentaires).

    - pas de commentaires dans les données : « sans commentaires » ;
    - citation dont moins de 80 % des mots figurent dans la vidéo : supprimée (jamais de fausse citation affichée).
    """
    if "Commentaires populaires" not in text:
        note["reaction_public"] = "sans commentaires"
    inside = text.split("\nLégende")[0]
    quote = _words(note.get("citation", ""))
    if quote and len(quote & _words(inside)) / len(quote) < 0.8:
        note["citation"] = ""


def _annotate(kind: str, run_id: str, limit: int | None, batch_size: int) -> dict:
    items = store.load_items(kind)
    version = SOCIAL_VERSION if kind == "social" else MEDIA_VERSION
    done = store.get_annotations(version)
    todo = [i for i in items if i["id"] not in done][:limit]
    system, schema, per_item = (
        (SOCIAL_SYSTEM, SocialBatch, 230) if kind == "social" else (MEDIA_SYSTEM, MediaBatch, 90)
    )
    chunks = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]

    def work(chunk: list[dict]) -> int:
        local = {f"e{n}": item["id"] for n, item in enumerate(chunk)}
        prompt = "\n\n".join(f"[e{n}]\n{item['text']}" for n, item in enumerate(chunk))
        result = llm.structured(
            run_id=run_id, purpose=f"annotation {kind}", model=config.MODEL_BULK, effort=config.EFFORT_BULK,
            system=system, prompt=prompt, schema=schema, max_tokens=400 + per_item * len(chunk), thinking=False,
        )
        notes = {local[n.id]: n.model_dump(exclude={"id"}) for n in result.notes if n.id in local}
        if kind == "social":
            texts = {item["id"]: item["text"] for item in chunk}
            for vid, note in notes.items():
                _guard(note, texts[vid])
        store.save_annotations(version, notes)
        return len(notes)

    annotated, errors, stopped, started = 0, [], None, time.time()
    with ThreadPoolExecutor(max_workers=config.ANNOTATE_WORKERS) as pool:
        futures = [pool.submit(work, c) for c in chunks]
        for n, f in enumerate(as_completed(futures), 1):
            try:
                annotated += f.result()
            except llm.BudgetExceeded as e:
                stopped = str(e)
                for other in futures:
                    other.cancel()
            except Exception as e:  # un paquet en échec sera repris à la prochaine exécution
                errors.append(f"{e.__class__.__name__}: {str(e)[:120]}")
            if n % 50 == 0:
                print(f"  {n}/{len(chunks)} paquets, {store.spent(run_id):.3f} $", flush=True)
    report = {"à faire": len(todo), "annotés": annotated, "durée (s)": round(time.time() - started),
              "dépense de l'exécution ($)": round(store.spent(run_id), 4)}
    if errors:
        report["paquets en échec (relancer pour les reprendre)"] = len(errors)
        report["première erreur"] = errors[0]
    if stopped:
        report["arrêt budget"] = stopped
    return report


def annotate_social(run_id: str, limit: int | None = None) -> dict:
    return _annotate("social", run_id, limit, batch_size=12)


def annotate_media(run_id: str, limit: int | None = None) -> dict:
    return _annotate("media", run_id, limit, batch_size=20)
