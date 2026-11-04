"""Adaptateur Oriane : POST https://connect.oriane.xyz/rest/contents/search (spec : https://connect.oriane.xyz/rest/docs).

Stratégie de collecte : pour chaque thème et chaque jour, une requête qui renvoie un échantillon de vidéos
et le nombre total de vidéos correspondantes (`totalCount`). Les volumes du score d'émergence viennent de
ces totaux ; chaque vidéo de l'échantillon porte un poids = total du jour / taille de l'échantillon.

Les appels consomment des crédits Oriane : `plan()` affiche le nombre d'appels avant de lancer quoi que ce soit.
"""
import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx

from .. import config, store

BASE_URL = "https://connect.oriane.xyz"
MAX_TEXT = 1800  # caractères envoyés au LLM par vidéo

# Filets de collecte. Ce ne sont pas les sujets affichés : le regroupement les découpe ensuite.
# Chaque expression exige tous ses mots (dans n'importe quel ordre, mots partiels acceptés),
# d'où des expressions de 2-3 mots et aucun mot court ambigu (« IA », « RN », « voile »).
# Personnalités : candidatures recensées par Touteleurope au 3/11/2026
# (https://www.touteleurope.eu/vie-politique-des-etats-membres/presidentielle-2027-qui-sont-les-candidats-deja-declares/)
# + personnalités très présentes dans le débat. Les noms absents sont rattrapés par les filets génériques
# du thème « campagne 2027 » et par la détection des personnalités émergentes (analyze.people).
CANDIDATES = [
    "Édouard Philippe", "Gabriel Attal", "Olivier Becht", "Dominique de Villepin", "Bernard Cazeneuve",
    "Karim Bouamrane", "Marine Le Pen", "Jean-Luc Mélenchon", "Raphaël Glucksmann", "Marine Tondelier",
    "Delphine Batho", "François Ruffin", "Fabien Roussel", "François Hollande", "Bruno Retailleau",
    "David Lisnard", "Xavier Bertrand", "Éric Zemmour", "Nathalie Arthaud", "Nicolas Dupont-Aignan",
    "Florian Philippot", "François Asselineau", "Clara Egger", "Anasse Kazib", "Selma Labib", "Juan Branco",
    "Natacha Polony", "Francis Lalanne", "Olivier Faure", "Ségolène Royal",
]
PUBLIC_FIGURES = ["Jordan Bardella", "Emmanuel Macron", "Marion Maréchal", "Sarah Knafo", "Laurent Wauquiez"]

THEMES = {
    "campagne 2027 : personnalités": CANDIDATES + PUBLIC_FIGURES,
    "campagne 2027 : candidatures et partis": [
        "élection présidentielle", "présidentielle 2027", "candidat présidentielle", "ma candidature",
        "serai candidat", "serai candidate", "parrainages", "sondage présidentielle", "Rassemblement national",
        "France insoumise", "parti Renaissance", "Les Républicains", "Parti socialiste", "Reconquête Zemmour",
        "Les Écologistes", "Parti communiste", "primaire de la gauche"],
    "institutions": ["Assemblée nationale", "motion de censure", "49.3", "dissolution Assemblée",
                     "Premier ministre", "Conseil constitutionnel", "référendum"],
    "budget, dette, impôts": ["dette publique", "budget État", "déficit public", "hausse des impôts",
                              "taxe Zucman", "niches fiscales"],
    "retraites": ["réforme des retraites", "âge de départ retraite", "montant des pensions"],
    "pouvoir d'achat": ["pouvoir d'achat", "prix des courses", "fin du mois", "smic",
                        "augmentation des salaires", "inflation"],
    "logement": ["loyer", "logement étudiant", "crise du logement", "logement social", "expulsion locative"],
    "énergie et carburant": ["prix essence", "prix carburant", "facture électricité", "centrale nucléaire",
                             "prix du gaz"],
    "travail et emploi": ["chômage", "licenciement", "plan social", "premier emploi", "assurance chômage",
                          "semaine de quatre jours"],
    "santé et services publics": ["urgences hôpital", "désert médical", "fermeture maternité",
                                  "médecin généraliste", "sécurité sociale"],
    "éducation et jeunesse": ["blocus lycée", "Parcoursup", "professeurs absents", "harcèlement scolaire",
                              "précarité étudiante", "bourse étudiante"],
    "sécurité": ["insécurité", "narcotrafic", "violences policières", "vidéosurveillance", "délinquance",
                 "fusillade"],
    "justice": ["décision de justice", "peine de prison", "garde à vue", "magistrats", "condamné à"],
    "immigration": ["immigration", "titre de séjour", "OQTF", "sans-papiers", "régularisation",
                    "droit d'asile"],
    "laïcité et religion": ["laïcité", "port du voile", "abaya", "islamisme"],
    "discriminations et violences": ["racisme", "homophobie", "sexisme", "antisémitisme", "islamophobie",
                                     "féminicide", "violences sexuelles"],
    "écologie et climat": ["réchauffement climatique", "canicule", "sécheresse", "inondations", "pollution",
                           "biodiversité"],
    "agriculture": ["agriculteurs", "colère agricole", "Mercosur", "pesticides"],
    "transports": ["grève SNCF", "train annulé", "prix billet train", "transports en commun", "ZFE"],
    "numérique et IA": ["intelligence artificielle", "ChatGPT", "interdiction réseaux sociaux",
                        "majorité numérique", "deepfake"],
    "outre-mer": ["Nouvelle-Calédonie", "Mayotte", "vie chère Guadeloupe", "Martinique"],
    "société": ["fin de vie", "aide à mourir", "IVG", "PMA", "légalisation cannabis"],
    "international vu de France": ["Gaza", "Ukraine", "Trump", "Israël", "Iran"],
    # Filet de cadrage : formules qu'emploient les créateurs sur un sujet de société, quel qu'il soit.
    # Attrape l'imprévu par la forme, pas par le fond. « Personne n'en parle » signale aussi un angle mort.
    "signaux d'actualité": [
        "personne n'en parle", "médias n'en parlent pas", "il faut qu'on parle", "on vous explique",
        "c'est un scandale", "c'est honteux", "inadmissible", "partagez au maximum", "ce qui se passe en France",
        "polémique", "indignation", "pétition", "manifestation", "mobilisation", "on lâche rien"],
}

# Filet aveugle : chaque jour, les vidéos françaises les plus commentées et partagées, sans mot-clé.
# Le filtre d'intérêt public (annotation) écarte le divertissement ; il reste l'actualité imprévue.
BLIND_NET = "veille ouverte"

# Médias suivis sur TikTok et Instagram (base de couverture). Leurs comptes sont trouvés par la recherche
# de profils d'Oriane (nom affiché ou compte proche, le plus suivi par plateforme), puis vérifiés à l'œil.
MEDIA_ACCOUNTS = {
    "Brut": ("brut", ["Brut"]),
    "HugoDécrypte": ("concurrent", ["HugoDécrypte", "hugodecrypte"]),
    "Konbini": ("concurrent", ["Konbini", "Konbini news"]),
    "Loopsider": ("concurrent", ["Loopsider"]),
    "Blast": ("concurrent", ["Blast", "blast info"]),
    "Le Crayon": ("concurrent", ["Le Crayon"]),
    "Vert": ("concurrent", ["Vert le média"]),
    "Le Monde": ("traditionnel", ["Le Monde", "lemondefr"]),
    "franceinfo": ("traditionnel", ["franceinfo"]),
    "20 Minutes": ("traditionnel", ["20 Minutes"]),
    "BFMTV": ("traditionnel", ["BFMTV"]),
    "Le Parisien": ("traditionnel", ["Le Parisien"]),
    "Ouest-France": ("traditionnel", ["Ouest-France"]),
    "Le Figaro": ("droite", ["Le Figaro"]),
    "CNews": ("droite", ["CNEWS"]),
    "Frontières": ("droite", ["Frontières média"]),
    "Libération": ("gauche", ["Libération"]),
    "Mediapart": ("gauche", ["Mediapart"]),
    "Le Média": ("gauche", ["Le Média"]),
}


def profile_query(names: list[str], platform: str) -> dict:
    return {"operator": "and", "filters": {"platform": {"includes": [platform]}},
            "queries": [{"operator": "or", "filters": {
                "displayName": {"includesFuzzy": {"values": names}},
                "handle": {"includesFuzzy": {"values": [n.replace(" ", "").lower() for n in names]}}}}]}


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

    def _post(self, body: dict, params: dict, path: str = "/rest/contents/search") -> dict:
        styles = [self.auth] if self.auth else AUTH_STYLES
        last = None
        for style in styles:
            for attempt in range(4):
                self.calls += 1
                r = self.http.post(path, json=body, params=params, headers=style(self.key))
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

    def profiles(self, body: dict, limit: int = 5) -> list[dict]:
        res = self._post(body, {"limit": limit, "sort": "followersCount:desc"}, path="/rest/profiles/search")
        return res["data"].get("results", [])


def _text_filter(terms: list[str]) -> dict:
    return {"includesFuzzy": {"values": terms, "operator": "or"}}


def theme_queries(theme: str) -> list[dict]:
    """Requêtes imbriquées d'un thème (le filet aveugle n'a que le filtre de langue)."""
    if theme == BLIND_NET:
        return [FRENCH]
    return [FRENCH, theme_query(theme, THEMES[theme])]


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
            # Instagram ne publie pas toujours les vues : None, estimé ensuite dans analyze.
            "views": r.get("viewsCount"), "likes": r.get("likesCount") or 0,
            "shares": r.get("sharesCount") or 0, "comments": r.get("commentsCount") or 0,
            "followers": r.get("profileFollowersCount") or 0, "platform": platform, "handle": handle,
            "theme_query": theme, "weight": weight, "thumbnail": r.get("thumbnailMediaUrl"),
            "comments_text": comments,
        },
    }


def plan(days: int, per_day: int, themes: list[str] | None = None, media: bool = True) -> dict:
    themes = themes or list(THEMES) + [BLIND_NET]
    social_calls = days * len(themes) + days  # + 1 appel par jour pour le total des vidéos françaises
    media_calls = len(MEDIA_ACCOUNTS) * 2 if media else 0  # ~2 pages de 100 par média
    return {"thèmes": len(themes), "jours": days, "vidéos max par thème et par jour": per_day,
            "appels sociaux": social_calls, "appels médias": media_calls,
            "appels au total": social_calls + media_calls,
            "vidéos max récupérées": social_calls * per_day + media_calls * 100}


def collect_social(days: int, per_day: int, themes: list[str] | None = None,
                   platforms: tuple[str, ...] = ("tiktok", "instagram")) -> dict:
    """Une requête par thème et par jour. Enregistre les vidéos avec leur poids et les totaux par jour.

    L'index Oriane se remplit progressivement : les derniers jours sont incomplets (constaté le 4/11 :
    dernière semaine ~10 fois moins fournie). On mesure donc chaque jour le total des vidéos françaises
    indexées, et le poids de chaque vidéo est ramené à un jour « complet » (total médian).
    """
    api = Oriane()
    themes = themes or list(THEMES) + [BLIND_NET]
    today = datetime.now(timezone.utc).date()
    base = {"platform": {"includes": list(platforms)}, "format": {"includes": ["video"]}}
    day_list = [(today - timedelta(days=d)).isoformat() for d in range(days)]
    totals, day_totals, saved = {}, {}, 0
    try:
        for day in day_list:
            _, day_totals[day] = api.search({**base, "publishedAt": {"after": day, "before": day}}, [FRENCH],
                                            limit=1, projection="basic")
        reference = sorted(day_totals.values())[len(day_totals) // 2] or 1
        # Enregistré tout de suite : utile même si la collecte s'arrête faute de crédits.
        store.cache_set("oriane:day_completeness", {d: round(t / reference, 3) for d, t in day_totals.items()})

        def one(theme: str, day: str) -> int:
            filters = {**base, "publishedAt": {"after": day, "before": day}}
            # Le filet aveugle prend plus de vidéos : il couvre tout, et beaucoup seront écartées.
            limit = min(100, per_day * 3) if theme == BLIND_NET else per_day
            results, total = api.search(filters, theme_queries(theme), limit=limit, sort="interactionsCount:desc")
            totals[f"{theme}|{day}"] = total
            if theme == BLIND_NET:
                # Échantillon des plus viraux, pas représentatif : sert à découvrir, pas à mesurer.
                # Une vidéo déjà ramenée par un thème garde le poids de ce thème.
                known = store.existing_ids([f"oriane:{r['id']}" for r in results])
                return store.upsert_items([to_item(r, theme, 1) for r in results if f"oriane:{r['id']}" not in known])
            completeness = day_totals[day] / reference if day_totals[day] else 0
            weight = total / len(results) / completeness if results and completeness else 0
            return store.upsert_items([to_item(r, theme, weight) for r in results])

        # Thèmes d'abord, filet aveugle en dernier (il ne doit pas écraser les poids des thèmes).
        jobs = [(t, d) for t in themes if t != BLIND_NET for d in day_list]
        blind = [(BLIND_NET, d) for d in day_list] if BLIND_NET in themes else []
        for batch in (jobs, blind):
            with ThreadPoolExecutor(max_workers=config.ORIANE_WORKERS) as pool:
                for n, got in enumerate(pool.map(lambda job: one(*job), batch), 1):
                    saved += got
                    if n % 50 == 0:
                        print(f"  {n}/{len(batch)} requêtes, {saved} vidéos", flush=True)
    except OrianeCreditsExhausted as e:
        return {"arrêt": str(e), "vidéos enregistrées": saved, "appels": api.calls}
    store.cache_set("oriane:totals", totals)
    return {"vidéos enregistrées": saved, "appels": api.calls,
            "complétude de l'index par jour": {d: round(t / reference, 2) for d, t in sorted(day_totals.items())}}


PROFILES_FILE = config.ROOT / "docs" / "oriane-media-profiles.json"


def find_media_profiles() -> dict:
    """Trouve le compte TikTok et Instagram le plus suivi de chaque média (2 petits appels par média).

    Résultat enregistré dans docs/oriane-media-profiles.json, à relire à l'œil : un homonyme reste possible.
    """
    import json
    api = Oriane()
    found = json.loads(PROFILES_FILE.read_text()) if PROFILES_FILE.exists() else {}
    stopped = None
    for name, (group, names) in MEDIA_ACCOUNTS.items():
        if found.get(name, {}).get("comptes"):
            continue  # déjà trouvé lors d'un passage précédent
        found[name] = {"groupe": group, "comptes": []}
        for platform in ("tiktok", "instagram"):
            try:
                results = api.profiles(profile_query(names, platform), limit=3)
            except OrianeCreditsExhausted as e:
                stopped = str(e)
                break
            if results:
                best = results[0]
                found[name]["comptes"].append({
                    "plateforme": platform, "id": best["id"], "compte": best.get("handle"),
                    "nom": best.get("displayName"), "abonnés": best.get("followersCount"),
                    "vérifié": best.get("isVerified"),
                    "autres candidats": [f"{r.get('handle')} ({r.get('followersCount')})" for r in results[1:]],
                })
        if stopped:
            break
    found = {k: v for k, v in found.items() if v["comptes"]}  # un média interrompu sera repris au prochain passage
    PROFILES_FILE.write_text(json.dumps(found, ensure_ascii=False, indent=1))
    return {"appels": api.calls, "fichier": str(PROFILES_FILE.relative_to(config.ROOT)),
            **({"arrêt": stopped} if stopped else {}),
            **{n: [f"{c['plateforme']} @{c['compte']} ({c['abonnés']})" for c in v["comptes"]] for n, v in found.items()}}


def collect_media(days: int = 14, max_per_account: int = 300) -> dict:
    """Publications TikTok et Instagram des médias suivis sur la période, pour la base de couverture."""
    import json
    if not PROFILES_FILE.exists():
        return {"erreur": "lancer d'abord oriane-find-media (recherche des comptes)"}
    profiles = json.loads(PROFILES_FILE.read_text())
    api = Oriane()
    after = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    report = {}
    try:
        for name, info in profiles.items():
            ids = [c["id"] for c in info["comptes"] if not c.get("exclu")]
            if not ids:
                continue
            items, offset, total = [], 0, None
            while offset < max_per_account:
                results, total = api.search({"profileId": {"includes": ids}, "publishedAt": {"after": after}},
                                            limit=100, offset=offset, projection="default", sort="publishedAt:desc")
                items += [to_item(r, None, 1, kind="media", group=info["groupe"], media_name=name) for r in results]
                offset += 100
                if len(results) < 100 or offset >= total:
                    break
            store.upsert_items(items)
            report[name] = f"{len(items)} publications sur {total} ({days} j)"
    except OrianeCreditsExhausted as e:
        report["arrêt"] = str(e)
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
