"""Adaptateur Oriane : POST https://connect.oriane.xyz/rest/contents/search (spec : https://connect.oriane.xyz/rest/docs).

Stratégie de collecte : pour chaque thème et chaque jour, une requête qui renvoie un échantillon de vidéos
et le nombre total de vidéos correspondantes (`totalCount`). Les volumes du score d'émergence viennent de
ces totaux ; chaque vidéo de l'échantillon porte un poids = total du jour / taille de l'échantillon.

Les appels consomment des crédits Oriane : `plan()` affiche le nombre d'appels avant de lancer quoi que ce soit.
"""
import csv
import os
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .. import store

BASE_URL = "https://connect.oriane.xyz"
MAX_TEXT = 1800  # caractères envoyés au LLM par vidéo

# Mots-clés par thème. Chaque expression est cherchée (tous ses mots, dans n'importe quel ordre)
# dans la transcription, le texte à l'écran et la légende. À ajuster samedi selon les premiers résultats.
THEMES = {
    "logement": ["loyer", "logement étudiant", "propriétaire", "expulsion", "HLM", "crise du logement"],
    "pouvoir d'achat": ["pouvoir d'achat", "prix courses", "inflation", "fin de mois", "smic", "salaire"],
    "carburant et énergie": ["prix essence", "carburant", "facture électricité", "prix gaz"],
    "emploi": ["chômage", "licenciement", "premier emploi", "stage", "retraite", "réforme des retraites"],
    "sécurité et police": ["police", "CRS", "violences policières", "insécurité", "délinquance", "vidéosurveillance"],
    "justice": ["procès", "tribunal", "garde à vue", "condamné"],
    "immigration": ["immigration", "migrants", "titre de séjour", "OQTF", "expulsé"],
    "écologie": ["climat", "canicule", "sécheresse", "pollution", "écologie", "inondations"],
    "santé": ["hôpital", "urgences", "maternité", "médecin", "désert médical"],
    "éducation": ["lycée", "blocus", "Parcoursup", "prof absent", "université", "bourse étudiante"],
    "numérique et IA": ["intelligence artificielle", "ChatGPT", "IA emploi", "réseaux sociaux interdits"],
    "institutions et élections": ["présidentielle", "2027", "Assemblée nationale", "gouvernement", "49.3",
                                  "dissolution", "Premier ministre", "élections", "sondage"],
    "discriminations": ["racisme", "homophobie", "sexisme", "discrimination", "islamophobie", "antisémitisme"],
    "transports": ["SNCF", "grève", "train annulé", "transports en commun"],
    "agriculture": ["agriculteurs", "paysans", "Mercosur"],
    "international": ["Gaza", "Ukraine", "Trump", "guerre"],
}

# Comptes TikTok et Instagram des médias, pour la base de couverture. À vérifier samedi (handles exacts).
MEDIA_HANDLES = {
    "Brut": ("brut", ["brut", "brutofficiel", "brutfr"]),
    "HugoDécrypte": ("concurrent", ["hugodecrypte"]),
    "Konbini": ("concurrent", ["konbini", "konbininews"]),
    "Loopsider": ("concurrent", ["loopsider"]),
    "Le Monde": ("traditionnel", ["lemondefr"]),
    "franceinfo": ("traditionnel", ["franceinfo"]),
    "20 Minutes": ("traditionnel", ["20minutesfrance", "20minutes"]),
    "BFMTV": ("traditionnel", ["bfmtv"]),
    "Blast": ("concurrent", ["blastinfo", "blast_info"]),
    "CNews": ("droite", ["cnews"]),
    "Le Figaro": ("droite", ["lefigarofr", "le_figaro"]),
    "Libération": ("gauche", ["liberationfr", "libe"]),
}

# Bearer confirmé le 4/11 (x-api-key refusé). Les autres restent en secours.
AUTH_STYLES = [
    lambda k: {"Authorization": f"Bearer {k}"},
    lambda k: {"x-api-key": k},
    lambda k: {"api-key": k},
]


class OrianeCreditsExhausted(RuntimeError):
    pass


class Oriane:
    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ.get("ORIANE_API_KEY")
        if not self.key:
            raise RuntimeError("ORIANE_API_KEY doit être rempli dans .env")
        self.http = httpx.Client(base_url=BASE_URL, timeout=60)
        self.auth = None
        self.calls = 0

    def _post(self, body: dict, params: dict) -> dict:
        styles = [self.auth] if self.auth else AUTH_STYLES
        last = None
        for style in styles:
            for attempt in range(4):
                self.calls += 1
                r = self.http.post("/rest/contents/search", json=body, params=params, headers=style(self.key))
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                break
            if r.status_code in (401, 403):
                last = r
                continue
            if r.status_code == 402:
                raise OrianeCreditsExhausted(f"Crédits Oriane épuisés ({self.calls} appels faits) : {r.text[:200]}")
            if r.status_code == 416:  # offset au-delà du dernier résultat
                return {"data": {"results": []}, "metadata": {"pagination": {"totalCount": 0}}}
            if r.status_code >= 400:
                raise RuntimeError(f"Oriane {r.status_code} : {r.text[:500]}")
            self.auth = style
            return r.json()
        raise RuntimeError(f"Authentification Oriane refusée ({last.status_code}) : {last.text[:200]}")

    def search(self, filters: dict, queries: list | None = None, limit: int = 50, offset: int = 0,
               projection: str = "full", sort: str = "publishedAt:desc") -> tuple[list[dict], int]:
        body = {"operator": "and", "filters": filters}
        if queries:
            body["queries"] = queries
        res = self._post(body, {"limit": limit, "offset": offset, "projection": projection, "sort": sort})
        return res["data"].get("results", []), res["metadata"].get("pagination", {}).get("totalCount", 0)


def _text_filter(terms: list[str]) -> dict:
    return {"includesFuzzy": {"values": terms, "operator": "or"}}


def theme_query(name: str, terms: list[str]) -> dict:
    """Un groupe nommé : l'un des termes dans la transcription, le texte à l'écran ou la légende."""
    return {"name": name, "operator": "or",
            "filters": {"transcript": _text_filter(terms), "onScreenText": _text_filter(terms),
                        "caption": _text_filter(terms)}}


FRENCH = {"name": "fr", "operator": "or",
          "filters": {"transcriptLanguage": {"includes": ["fr"]}, "captionLanguage": {"includes": ["fr"]}}}


def to_item(r: dict, theme: str | None, weight: float, kind: str = "social", group: str | None = None,
            media_name: str | None = None) -> dict:
    medias = r.get("media") or []
    transcript = " ".join(m.get("transcript") or "" for m in medias).strip()
    on_screen = " / ".join(t for m in medias for t in (m.get("onScreenText") or []))
    comments = [c.get("content", "") for c in (r.get("popularComments") or [])][:5]
    parts = [f"Paroles : {transcript}" if transcript else "",
             f"Texte à l'écran : {on_screen}" if on_screen else "",
             f"Titre : {r['title']}" if r.get("title") else "",
             f"Légende : {r.get('caption') or ''}",
             ("Commentaires populaires : " + " | ".join(comments)) if comments else ""]
    text = "\n".join(p for p in parts if p)[:MAX_TEXT]
    handle, platform = r.get("profileHandle"), r.get("platform")
    url = None
    if platform == "tiktok" and handle and r.get("platformId"):
        url = f"https://www.tiktok.com/@{handle}/video/{r['platformId']}"
    elif platform == "youtube" and r.get("platformId"):
        url = f"https://www.youtube.com/watch?v={r['platformId']}"
    return {
        "id": f"oriane:{r['id']}",
        "kind": kind,
        "source": "oriane",
        "account": media_name or f"{platform}:{handle}",
        "account_group": group,
        "published_at": r["publishedAt"],
        "url": url,
        "text": text,
        "metrics": {
            "views": r.get("viewsCount") or 0, "likes": r.get("likesCount") or 0,
            "shares": r.get("sharesCount") or 0, "comments": r.get("commentsCount") or 0,
            "followers": r.get("profileFollowersCount") or 0, "platform": platform, "handle": handle,
            "theme_query": theme, "weight": weight, "thumbnail": r.get("thumbnailMediaUrl"),
            "comments_text": comments,
        },
    }


def plan(days: int, per_day: int, themes: list[str] | None = None, media: bool = True) -> dict:
    themes = themes or list(THEMES)
    social_calls = days * len(themes)
    media_calls = len(MEDIA_HANDLES) if media else 0
    return {"thèmes": len(themes), "jours": days, "vidéos max par thème et par jour": per_day,
            "appels sociaux": social_calls, "appels médias": media_calls,
            "appels au total": social_calls + media_calls,
            "vidéos max récupérées": social_calls * per_day + media_calls * 100}


def collect_social(days: int, per_day: int, themes: list[str] | None = None,
                   platforms: tuple[str, ...] = ("tiktok", "instagram")) -> dict:
    """Une requête par thème et par jour. Enregistre les vidéos avec leur poids et les totaux par jour."""
    api = Oriane()
    themes = themes or list(THEMES)
    today = datetime.now(timezone.utc).date()
    totals, saved = {}, 0
    try:
        for theme in themes:
            for d in range(days):
                day = (today - timedelta(days=d)).isoformat()
                filters = {"platform": {"includes": list(platforms)}, "format": {"includes": ["video"]},
                           "publishedAt": {"after": day, "before": day}}
                results, total = api.search(filters, [FRENCH, theme_query(theme, THEMES[theme])],
                                            limit=per_day, sort="interactionsCount:desc")
                totals[f"{theme}|{day}"] = total
                weight = total / len(results) if results else 0
                saved += store.upsert_items([to_item(r, theme, weight) for r in results])
    except OrianeCreditsExhausted as e:
        return {"arrêt": str(e), "vidéos enregistrées": saved, "appels": api.calls}
    store.cache_set("oriane:totals", totals)
    return {"vidéos enregistrées": saved, "appels": api.calls,
            "total de vidéos réelles estimé": sum(totals.values())}


def collect_media(days: int = 14, per_account: int = 100) -> dict:
    """Vidéos TikTok et Instagram des médias (Brut et concurrents), pour la base de couverture."""
    api = Oriane()
    after = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    report = {}
    for name, (group, handles) in MEDIA_HANDLES.items():
        filters = {"profileHandle": {"exactMatch": {"values": handles, "operator": "or"}}, "publishedAt": {"after": after}}
        try:
            results, total = api.search(filters, limit=per_account, projection="default")
        except OrianeCreditsExhausted as e:
            report["arrêt"] = str(e)
            break
        items = [to_item(r, None, 1, kind="media", group=group, media_name=name) for r in results]
        store.upsert_items(items)
        report[name] = f"{len(items)} vidéos ({total} sur la période), comptes : {sorted({r.get('profileHandle') for r in results})}"
    report["appels"] = api.calls
    return report


def ping() -> dict:
    """Un seul appel minuscule : vérifie la clé, le style d'authentification et la forme des réponses."""
    api = Oriane()
    since = (date.today() - timedelta(days=2)).isoformat()
    results, total = api.search({"publishedAt": {"after": since}}, [FRENCH, theme_query("test", ["loyer"])], limit=2)
    first = results[0] if results else {}
    return {"authentification": ["Bearer", "x-api-key", "api-key"][AUTH_STYLES.index(api.auth)],
            "résultats sur 2 jours pour « loyer »": total,
            "champs reçus": sorted(first.keys()),
            "champs média": sorted((first.get("media") or [{}])[0].keys()) if first else [],
            "exemple": {k: first.get(k) for k in ("platform", "profileHandle", "publishedAt", "viewsCount", "caption")}}


def import_csv(path: str) -> dict:
    """Plan B : export CSV de l'application Oriane (jusqu'à 10 000 lignes). Colonnes détectées par leur nom."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {"lignes": 0}
    cols = list(rows[0])

    def col(*needles):
        return next((c for c in cols if any(n in c.lower() for n in needles)), None)

    c = {"id": col("content id", "id"), "date": col("published", "date"), "handle": col("handle", "username", "creator"),
         "platform": col("platform"), "url": col("url", "link"), "transcript": col("transcript", "spoken"),
         "screen": col("on screen", "onscreen", "text on"), "caption": col("caption", "description"),
         "views": col("views"), "likes": col("likes"), "shares": col("shares"), "comments": col("comments"),
         "followers": col("follower")}

    def num(row, key):
        try:
            return int(float((row.get(c[key]) or "0").replace(",", "").replace(" ", "")))
        except ValueError:
            return 0

    items = []
    for n, row in enumerate(rows):
        r = {"id": row.get(c["id"]) or f"csv{n}", "publishedAt": row.get(c["date"]), "profileHandle": row.get(c["handle"]),
             "platform": (row.get(c["platform"]) or "").lower(), "caption": row.get(c["caption"]),
             "media": [{"transcript": row.get(c["transcript"]), "onScreenText": [row[c["screen"]]] if c["screen"] and row.get(c["screen"]) else []}],
             "viewsCount": num(row, "views"), "likesCount": num(row, "likes"), "sharesCount": num(row, "shares"),
             "commentsCount": num(row, "comments"), "profileFollowersCount": num(row, "followers")}
        if not r["publishedAt"]:
            continue
        item = to_item(r, "csv", 1)
        item["url"] = row.get(c["url"]) or item["url"]
        items.append(item)
    return {"colonnes reconnues": {k: v for k, v in c.items() if v}, "colonnes ignorées": [x for x in cols if x not in c.values()],
            "vidéos enregistrées": store.upsert_items(items)}
