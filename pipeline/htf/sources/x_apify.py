"""X (Twitter) via Apify, pour croiser avec Oriane (demande de Brut le 7/11 : « Oriane est la base, croisez les sources »).

Pourquoi X : (1) Brut y suit déjà ~200 comptes et cherche des comptes de niche, notamment locaux ;
(2) X a les publications du jour même, alors qu'Oriane a ~4 jours de retard ; (3) pas de seuil d'abonnés
(Oriane n'indexe pas les comptes de moins de 5 000 abonnés).

Budget : compte Apify gratuit, 5 $ de crédit par mois, PLAFOND DUR 4 $ (APIFY_BUDGET_USD). Chaque lancement
est bridé par Apify lui-même (maxTotalChargeUsd) et compté ici avant de partir. Scraper : kaitoeasyapi (voir ACTOR).
"""
import os
from datetime import datetime

import httpx

from .. import config, store

# apidojo/tweet-scraper (0,40 $/1 000) bride les comptes gratuits à 10 tweets par lancement (constaté le 7/11) :
# on utilise kaitoeasyapi (~0,20 $/1 000 constaté, fonctionne en compte gratuit, mêmes champs de sortie).
ACTOR = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
PRICE_PER_TWEET = 0.00025  # marge sur le prix constaté (0,02 $ les 100)
APIFY_BUDGET_USD = 4.0
API = "https://api.apify.com/v2"

# Requêtes Sud-Ouest : villes et départements regroupés, en français, sans réponses, avec un minimum de likes
# pour écarter le bruit. Une requête par bassin de vie.
SUD_OUEST_QUERIES = {
    "Bordeaux et Gironde": "(Bordeaux OR Gironde OR Mérignac OR Pessac OR Arcachon OR Libourne OR Médoc)",
    "Toulouse et Haute-Garonne": "(Toulouse OR \"Haute-Garonne\" OR Blagnac OR Colomiers OR Muret)",
    "Pays basque et Béarn": "(Pau OR Béarn OR Bayonne OR Biarritz OR Anglet OR \"Pays basque\" OR Hendaye)",
    "Limousin": "(Limoges OR \"Haute-Vienne\" OR Brive OR Corrèze OR Tulle OR Guéret)",
    "Poitou-Charentes": "(Poitiers OR \"La Rochelle\" OR Niort OR Angoulême OR Royan OR \"Charente-Maritime\")",
    "Landes, Périgord, Lot-et-Garonne": "(Agen OR Périgueux OR Bergerac OR \"Mont-de-Marsan\" OR Dax OR Dordogne OR Landes)",
    "Pyrénées et Midi": "(Tarbes OR Lourdes OR Auch OR Montauban OR Albi OR Rodez OR Castres OR Ariège)",
}


def _token() -> str:
    from dotenv import dotenv_values
    token = (os.environ.get("APIFY_TOKEN") or dotenv_values(config.ROOT / ".env").get("APIFY_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("APIFY_TOKEN manquant dans .env")
    return token


def spent() -> dict:
    """Dépense Apify du mois, lue chez Apify (source de vérité) et estimée ici."""
    r = httpx.get(f"{API}/users/me/limits", headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    d = r.json()["data"]
    return {"dépensé chez Apify ($)": round(d["current"]["monthlyUsageUsd"], 4),
            "limite du compte ($)": d["limits"]["maxMonthlyUsageUsd"], "plafond de l'équipe ($)": APIFY_BUDGET_USD}


def search(terms: list[str], max_items: int, sort: str = "Latest") -> list[dict]:
    cost = max_items * PRICE_PER_TWEET
    already = spent()["dépensé chez Apify ($)"]
    if already + cost > APIFY_BUDGET_USD:
        raise RuntimeError(f"Plafond Apify : {already:.2f} $ déjà dépensés, ce lancement coûterait jusqu'à {cost:.2f} $ "
                           f"(plafond {APIFY_BUDGET_USD} $).")
    r = httpx.post(f"{API}/acts/{ACTOR}/run-sync-get-dataset-items",
                   params={"maxItems": max_items, "maxTotalChargeUsd": round(cost + 0.01, 2), "timeout": 280},
                   json={"searchTerms": terms, "maxItems": max_items, "queryType": sort},
                   headers={"Authorization": f"Bearer {_token()}"}, timeout=320)
    r.raise_for_status()
    return [x for x in r.json() if isinstance(x, dict) and x.get("text")]


def to_item(t: dict, query: str) -> dict:
    a = t.get("author") or {}
    created = datetime.strptime(t["createdAt"], "%a %b %d %H:%M:%S %z %Y").isoformat()
    return {
        "id": f"x:{t['id']}", "kind": "x", "source": "x", "account": f"x:{a.get('userName')}",
        "account_group": None, "published_at": created,
        "url": t.get("url") or t.get("twitterUrl"), "text": (t.get("text") or "")[:1200],
        "metrics": {"platform": "x", "handle": a.get("userName"), "name": a.get("name"),
                    "followers": a.get("followers") or 0, "likes": t.get("likeCount") or 0,
                    "shares": t.get("retweetCount") or 0, "comments": t.get("replyCount") or 0,
                    "views": t.get("viewCount"), "bio": (a.get("description") or "")[:300],
                    "profile_location": a.get("location"), "verified": a.get("isBlueVerified"),
                    "theme_query": query},
    }


def collect_sud_ouest(since: str, until: str, per_query: int = 350, min_faves: int = 3, sort: str = "Latest") -> dict:
    """~7 requêtes × per_query tweets. « Latest » ramène surtout les derniers jours : pour une période plus
    ancienne, relancer avec `until` plus tôt et sort="Top" (7/11 : 2e passage 22/10 → 2/11)."""
    terms = [f"{q} lang:fr -filter:replies min_faves:{min_faves} since:{since} until:{until}"
             for q in SUD_OUEST_QUERIES.values()]
    out, saved = {}, 0
    for name, term in zip(SUD_OUEST_QUERIES, terms):
        tweets = search([term], per_query, sort)
        saved += store.upsert_items([to_item(t, f"x:{name}") for t in tweets if t.get("createdAt")])
        out[name] = len(tweets)
    return {"tweets par bassin": out, "nouveaux": saved, **spent()}
