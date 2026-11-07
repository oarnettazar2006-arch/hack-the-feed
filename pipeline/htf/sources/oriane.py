"""Adaptateur Oriane : POST https://connect.oriane.xyz/rest/contents/search (spec : https://connect.oriane.xyz/rest/docs).

Stratégie de collecte : pour chaque thème et chaque jour, une requête qui renvoie un échantillon de vidéos
et le nombre total de vidéos correspondantes (`totalCount`). Les volumes du score d'émergence viennent de
ces totaux ; chaque vidéo de l'échantillon porte un poids = total du jour / taille de l'échantillon.

Les appels consomment des crédits Oriane : `plan()` affiche le nombre d'appels avant de lancer quoi que ce soit.
"""
import csv
import os
import threading
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
# Filet « décollage » (7/11) : vidéos FR qui font au moins 3 fois l'audience de leur créateur, sans mot-clé.
# C'est le moment où un sujet décolle, avant d'être une tendance (le tri par interactions favorise les gros comptes).
BREAKOUT_NET = "décollage"
DISCOVERY_NETS = (BLIND_NET, BREAKOUT_NET)

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


def _env_keys(env) -> list[str]:
    """Clés Oriane dans l'ordre d'usage : celles des camarades d'abord (ORIANE_API_KEY_2, _3, puis
    ORIANE_API_KEYS séparées par des virgules), la clé principale ORIANE_API_KEY en dernier (épuisée le 7/11)."""
    keys = [env.get("ORIANE_API_KEY_2"), env.get("ORIANE_API_KEY_3"),
            *(env.get("ORIANE_API_KEYS") or "").split(","), env.get("ORIANE_API_KEY")]
    out = []
    for k in keys:
        k = (k or "").strip()
        if k and k not in out:
            out.append(k)
    return out


class Oriane:
    def __init__(self, api_key: str | None = None):
        # Plusieurs comptes possibles (crédits hackathon par personne) : ORIANE_API_KEYS=clé1,clé2,clé3.
        # Quand une clé n'a plus de crédits (402), on passe à la suivante.
        keys = [api_key] if api_key else _env_keys(os.environ)
        if not keys:
            raise RuntimeError("ORIANE_API_KEY (ou ORIANE_API_KEYS) doit être rempli dans .env")
        self.keys = keys
        self.key_index = 0
        self.key = keys[0]
        self.lock = threading.Lock()
        self.http = httpx.Client(base_url=BASE_URL, timeout=60)
        self.auth = None
        self.calls = 0

    def _post(self, body: dict, params: dict, path: str = "/rest/contents/search") -> dict:
        styles = [self.auth] if self.auth else AUTH_STYLES
        last = None
        for style in styles:
            for attempt in range(4):
                self.calls += 1
                key = self.key
                r = self.http.post(path, json=body, params=params, headers=style(key))
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                break
            if r.status_code in (401, 403):
                last = r
                continue
            if r.status_code == 402:
                with self.lock:
                    if key == self.key and self.key_index + 1 >= len(self.keys):
                        # Clés ajoutées dans .env pendant la collecte : on les relit avant d'abandonner.
                        from dotenv import dotenv_values
                        extra = [k for k in _env_keys(dotenv_values(config.ROOT / ".env")) if k not in self.keys]
                        self.keys += extra
                    if key == self.key and self.key_index + 1 < len(self.keys):
                        self.key_index += 1
                        self.key = self.keys[self.key_index]
                        print(f"Oriane : clé {self.key_index} épuisée, passage à la clé {self.key_index + 1}/{len(self.keys)}")
                    elif key == self.key:
                        raise OrianeCreditsExhausted(f"Crédits Oriane épuisés sur les {len(self.keys)} clés "
                                                     f"({self.calls} appels faits) : {r.text[:200]}")
                return self._post(body, params, path)
            if r.status_code == 416:  # offset au-delà du dernier résultat
                return {"data": {"results": []}, "metadata": {"pagination": {"totalCount": 0}}}
            if r.status_code >= 400:
                raise RuntimeError(f"Oriane {r.status_code} : {r.text[:500]}")
            self.auth = style
            return r.json()
        raise RuntimeError(f"Authentification Oriane refusée ({last.status_code}) : {last.text[:200]}")

    def search(self, filters: dict, queries: list | None = None, limit: int = 50, offset: int = 0,
               projection: str = "full", sort: str = "publishedAt:desc") -> tuple[list[dict], int]:
        results, total, _ = self.search_meta(filters, queries, limit, offset, projection, sort)
        return results, total

    def search_meta(self, filters: dict, queries: list | None = None, limit: int = 50, offset: int = 0,
                    projection: str = "full", sort: str = "publishedAt:desc") -> tuple[list[dict], int, dict]:
        """Comme search, plus les agrégations d'Oriane sur TOUS les résultats (pas seulement la page) :
        totalViewsCount, totalInteractionsCount, moyennes… Même prix que search."""
        body = {"operator": "and", "filters": filters}
        if queries:
            body["queries"] = queries
        res = self._post(body, {"limit": limit, "offset": offset, "projection": projection, "sort": sort})
        return (res["data"].get("results", []), res["metadata"].get("pagination", {}).get("totalCount", 0),
                res["data"].get("aggregations") or {})

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
    # Repères dans la vidéo : chaque citation retrouvée pointe vers sa seconde ou l'image où le texte apparaît.
    first = medias[0] if medias else {}
    chunks = [[round(c["startSeconds"], 1), c["text"]] for c in (first.get("transcriptChunks") or [])[:120]]
    frames = [[round(f.get("timestampSeconds") or 0, 1), f.get("url"),
               " ".join(t.get("text", "") for t in f["onScreenTextRegions"])]
              for f in (first.get("frames") or []) if f.get("onScreenTextRegions")][:12]
    # Correctif du 7/11 (repéré par Erwan) : la légende passait après les paroles et était coupée par
    # MAX_TEXT sur les vidéos longues. Chaque partie a maintenant sa propre limite : rien n'est perdu en entier.
    tags = " ".join("#" + h.lstrip("#") for h in (r.get("hashtags") or [])[:15])
    caption = (r.get("caption") or "").strip()
    if tags and tags.split()[0].lower() not in caption.lower():
        caption = f"{caption} {tags}".strip()
    parts = [f"Titre : {r['title'][:200]}" if r.get("title") else "",
             f"Légende : {caption[:400]}",
             f"Paroles : {transcript[:900]}" if transcript else "",
             f"Texte à l'écran : {on_screen[:400]}" if on_screen else "",
             ("Commentaires populaires : " + " | ".join(comments))[:300] if comments else ""]
    text = "\n".join(p for p in parts if p)[:MAX_TEXT + 400]
    handle, platform = r.get("profileHandle"), r.get("platform")
    url = None
    if platform == "tiktok" and handle and r.get("platformId"):
        url = f"https://www.tiktok.com/@{handle}/video/{r['platformId']}"
    elif platform == "youtube" and r.get("platformId"):
        url = f"https://www.youtube.com/watch?v={r['platformId']}"
    elif platform == "instagram" and handle:
        # Oriane ne donne pas le code court du post Instagram (seulement un identifiant numérique) :
        # lien de repli vers le compte, signalé par `lien_compte` pour que l'interface l'écrive.
        url = f"https://www.instagram.com/{handle}/"
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
            "comments_text": comments, "hashtags": r.get("hashtags") or [],
            "chunks": chunks, "frames": frames, "platform_id": r.get("platformId"),
            # Géographie (veille locale) : lieu tagué, lieu du profil, bio du créateur.
            "location": r.get("locationCompleteAddress"), "profile_location": r.get("profileLocationCompleteAddress"),
            "bio": (r.get("profileBio") or "")[:300],
            "lien_compte": platform == "instagram",
        },
    }


def plan(days: int, per_day: int, themes: list[str] | None = None, media: bool = True) -> dict:
    themes = themes or list(THEMES) + [BLIND_NET]
    social_calls = days * len(themes) + days  # + 1 appel par jour pour le total des vidéos françaises
    media_calls = len(MEDIA_ACCOUNTS) * 2 if media else 0  # ~2 pages de 100 par média
    return {"thèmes": len(themes), "jours": days, "vidéos max par thème et par jour": per_day,
            "appels sociaux": social_calls, "appels médias": media_calls,
            "appels au total": social_calls + media_calls,
            # Mesuré le 7/11 : 20 crédits par recherche avec transcriptions, 10 en projection basic ou profils,
            # quel que soit le nombre de vidéos renvoyées.
            "crédits estimés": days * 10 + (social_calls - days) * 20 + (media_calls * 1.5 * 20 if media else 0) + (400 if media else 0),
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


def collect_breakout(days: int = 17, per_day: int = 100, min_ratio: float = 300,
                     platforms: tuple[str, ...] = ("tiktok", "instagram")) -> dict:
    """Filet « décollage » : par jour, les vidéos FR dont les vues dépassent `min_ratio` % des abonnés,
    triées par ce ratio. Découverte (poids 1) ; une vidéo déjà connue garde son thème et son poids."""
    api = Oriane()
    today = datetime.now(timezone.utc).date()
    base = {"platform": {"includes": list(platforms)}, "format": {"includes": ["video"]},
            "viewsRatePerFollowers": {"min": min_ratio}}
    day_list = [(today - timedelta(days=d)).isoformat() for d in range(days)]
    totals, saved = {}, 0

    def one(day: str) -> int:
        results, total, aggs = api.search_meta({**base, "publishedAt": {"after": day, "before": day}}, [FRENCH],
                                               limit=per_day, sort="viewsRatePerFollowers:desc")
        totals[day] = {"videos": total, "vues": aggs.get("totalViewsCount")}
        known = store.existing_ids([f"oriane:{r['id']}" for r in results])
        return store.upsert_items([to_item(r, BREAKOUT_NET, 1) for r in results if f"oriane:{r['id']}" not in known])

    try:
        with ThreadPoolExecutor(max_workers=config.ORIANE_WORKERS) as pool:
            saved = sum(pool.map(one, day_list))
    except OrianeCreditsExhausted as e:
        return {"arrêt": str(e), "vidéos enregistrées": saved, "appels": api.calls}
    store.cache_set("oriane:breakout_totals", totals)
    return {"vidéos nouvelles": saved, "appels": api.calls,
            "vidéos en décollage par jour (FR, total Oriane)": {d: t["videos"] for d, t in sorted(totals.items())}}


def people_volumes(names: list[str], end: date, recent_days: int, base_days: int) -> dict:
    """Volumes RÉELS (tout l'index, pas l'échantillon) des vidéos FR citant chaque personnalité, sur la période
    récente et la période de référence : nombre, vues et interactions totales (agrégations). 2 appels basic
    par nom (10 crédits chacun)."""
    api = Oriane()
    base = {"platform": {"includes": ["tiktok", "instagram"]}, "format": {"includes": ["video"]}}
    r_start = end - timedelta(days=recent_days - 1)
    b_start = r_start - timedelta(days=base_days)
    out = {}

    def one(name: str) -> tuple[str, dict]:
        q = [FRENCH, theme_query(name, [name])]
        _, n_r, a_r = api.search_meta({**base, "publishedAt": {"after": r_start.isoformat(), "before": end.isoformat()}},
                                      q, limit=1, projection="basic")
        _, n_b, a_b = api.search_meta({**base, "publishedAt": {"after": b_start.isoformat(),
                                                                 "before": (r_start - timedelta(days=1)).isoformat()}},
                                      q, limit=1, projection="basic")
        return name, {"videos_recentes": n_r, "vues_recentes": a_r.get("totalViewsCount") or 0,
                      "interactions_recentes": a_r.get("totalInteractionsCount") or 0,
                      "videos_reference": n_b, "vues_reference": a_b.get("totalViewsCount") or 0,
                      "periode": f"{r_start} → {end} (référence {b_start} → {r_start - timedelta(days=1)})"}

    try:
        with ThreadPoolExecutor(max_workers=config.ORIANE_WORKERS) as pool:
            out = dict(pool.map(one, names))
        store.cache_set("oriane:people_volumes", out)
        people_volume_totals(end, recent_days, base_days)
    except OrianeCreditsExhausted as e:
        return {"arrêt": str(e)}
    return {"personnalités": len(out), "appels": api.calls}


def people_volume_totals(end: date, recent_days: int, base_days: int) -> dict:
    """Total des vidéos FR indexées sur les deux mêmes périodes (2 appels basic) : sert à corriger
    l'accélération du retard d'indexation (la période récente est toujours moins remplie)."""
    api = Oriane()
    base = {"platform": {"includes": ["tiktok", "instagram"]}, "format": {"includes": ["video"]}}
    r_start = end - timedelta(days=recent_days - 1)
    b_start = r_start - timedelta(days=base_days)
    _, n_r = api.search({**base, "publishedAt": {"after": r_start.isoformat(), "before": end.isoformat()}},
                        [FRENCH], limit=1, projection="basic")
    _, n_b = api.search({**base, "publishedAt": {"after": b_start.isoformat(),
                                                  "before": (r_start - timedelta(days=1)).isoformat()}},
                        [FRENCH], limit=1, projection="basic")
    totals = {"videos_fr_recentes": n_r, "videos_fr_reference": n_b}
    store.cache_set("oriane:people_volume_totals", totals)
    return totals


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
