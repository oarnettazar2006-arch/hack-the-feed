"""Veille locale : les sujets qui naissent dans une région avant de devenir nationaux (schéma des gilets jaunes),
et les comptes « éclaireurs », peu connus, qui en parlent en premier.

Région de démonstration : Sud-Ouest (Nouvelle-Aquitaine + ouest de l'Occitanie), demande de Brut le 7/11.
Ajouter une région = ajouter une entrée dans REGIONS (villes, départements, médias locaux) : rien d'autre à changer.

Une vidéo est rattachée à la région par, dans l'ordre : le lieu tagué sur la vidéo, le lieu du profil, la bio
du créateur, puis une ville ou un département cité dans les paroles, le texte à l'écran ou la légende.
Limite d'Oriane à dire : les comptes de moins de 5 000 abonnés ne sont pas indexés.
"""
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import config, store

REGIONS = {
    "Sud-Ouest": {
        "villes": ["Bordeaux", "Toulouse", "Pau", "Bayonne", "Biarritz", "Anglet", "Dax", "Mont-de-Marsan",
                   "Arcachon", "Mérignac", "Pessac", "Libourne", "Périgueux", "Bergerac", "Agen", "Villeneuve-sur-Lot",
                   "Angoulême", "La Rochelle", "Royan", "Niort", "Poitiers",
                   "Limoges", "Brive", "Tulle", "Guéret", "Tarbes", "Lourdes", "Auch", "Montauban", "Albi", "Castres",
                   "Cahors", "Foix", "Pamiers", "Rodez", "Millau", "Blagnac", "Colomiers", "Muret", "Hendaye",
                   "Saint-Jean-de-Luz", "Oloron", "Orthez", "Marmande", "Figeac", "Saint-Gaudens"],
        "departements": ["Gironde", "Landes", "Pyrénées-Atlantiques", "Haute-Garonne", "Gers", "Tarn-et-Garonne",
                         "Lot-et-Garonne", "Dordogne", "Charente-Maritime", "Charente", "Deux-Sèvres",
                         "Haute-Vienne", "Corrèze", "Creuse", "Hautes-Pyrénées", "Ariège", "Aveyron", "Tarn",
                         "Pays basque", "Béarn", "Bigorre", "Nouvelle-Aquitaine", "Occitanie", "Médoc", "Périgord",
                         "Bassin d'Arcachon", "Sud-Ouest"],
        # Noms ambigus volontairement absents : Cognac (l'alcool), Saintes (« les saintes »), Vienne (Autriche), Lot.
        # Médias locaux : leurs vidéos comptent comme « couvert localement », pas comme éclaireurs.
        "medias": ["sudouest", "ladepechedumidi", "ladepeche", "france3occitanie", "france3nouvelleaquitaine",
                   "france3aquitaine", "larepubliquedespyrenees", "charentelibre", "lepetitbleu", "actutoulouse",
                   "actubordeaux", "rue89bordeaux", "mediacites", "icigironde", "icioccitanie", "bfmtoulouse",
                   "bfmbordeaux", "tv7bordeaux", "lacentrepresse", "lepopulaire", "lanouvellerepublique"],
    },
}
NATIONAL_MEDIA = {"brutofficiel", "hugodecrypte", "konbini", "loopsider", "lemondefr", "franceinfo", "bfmtv",
                  "leparisien", "lefigaro", "20minutesonline", "ouestfrance", "liberationfr", "mediapart",
                  "lecrayonmedia", "frontieresmedia", "le20hfrancetelevisions", "tf1info", "tv5mondeinfo"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s)


_PATTERNS = {name: re.compile(r"\b(" + "|".join(re.escape(_norm(x).strip()) for x in r["villes"] + r["departements"]) + r")\b")
             for name, r in REGIONS.items()}


def place_terms(region: str) -> list[str]:
    r = REGIONS[region]
    return r["villes"] + r["departements"]


def region_of(item: dict) -> tuple[str | None, str | None]:
    """(région, source) d'une vidéo : lieu tagué, lieu du profil, bio, puis texte."""
    m = item.get("metrics") or {}
    for source, text in (("lieu de la vidéo", m.get("location")), ("lieu du profil", m.get("profile_location")),
                         ("bio", m.get("bio")), ("texte", item.get("text"))):
        if not text:
            continue
        t = f" {_norm(text)} "
        for name, pat in _PATTERNS.items():
            if pat.search(t):
                return name, source
    return None, None


def collect(region: str = "Sud-Ouest", days: int = 17, per_day: int = 50) -> dict:
    """Par jour : les vidéos FR rattachées à la région (lieu, profil, bio ou texte), deux fois :
    les plus interactives, et celles qui dépassent le plus l'audience de leur créateur (décollage)."""
    from .sources import oriane
    api = oriane.Oriane()
    terms = place_terms(region)
    # Expression exacte : en recherche floue, « Pau » attraperait « Paul » et « Agen » « agence ».
    fuzzy = {"includesExactly": {"values": terms}}
    where = {"name": f"local:{region}", "operator": "or",
             "filters": {"locationCompleteAddress": fuzzy, "profileLocationCompleteAddress": fuzzy,
                         "profileBio": fuzzy, "transcript": fuzzy, "onScreenText": fuzzy, "caption": fuzzy}}
    base = {"platform": {"includes": ["tiktok", "instagram"]}, "format": {"includes": ["video"]}}
    today = datetime.now(timezone.utc).date()
    saved, totals = 0, {}
    try:
        for d in range(days):
            day = (today - timedelta(days=d)).isoformat()
            f = {**base, "publishedAt": {"after": day, "before": day}}
            for sort in ("interactionsCount:desc", "viewsRatePerFollowers:desc"):
                results, total = api.search(f, [oriane.FRENCH, where], limit=per_day, sort=sort)
                totals[day] = total
                known = store.existing_ids([f"oriane:{r['id']}" for r in results])
                saved += store.upsert_items([oriane.to_item(r, f"local:{region}", 1) for r in results
                                             if f"oriane:{r['id']}" not in known])
    except oriane.OrianeCreditsExhausted as e:
        return {"arrêt": str(e), "vidéos nouvelles": saved, "appels": api.calls}
    store.cache_set(f"local:totals:{region}", totals)
    return {"région": region, "vidéos nouvelles": saved, "appels": api.calls,
            "vidéos de la région par jour (total Oriane)": dict(sorted(totals.items()))}


def topic_geography(members: list[dict]) -> dict:
    """Part locale d'un sujet et schéma « né localement, devenu national »."""
    tagged = [(v, region_of(v)[0]) for v in members]
    by_region = Counter(r for _, r in tagged if r)
    if not by_region:
        return {"regions": {}, "foyer": None, "local_vers_national": False}
    ordered = sorted(tagged, key=lambda x: x[0]["published_at"])
    third = max(1, len(ordered) // 3)
    early, late = ordered[:third], ordered[-third:]
    out = {"regions": dict(by_region), "foyer": None, "local_vers_national": False}
    for region, n_region in by_region.items():
        # Au moins 8 vidéos rattachées et 30 % du sujet : en dessous, une simple mention ne fait pas un foyer.
        if n_region < 8 or n_region / len(members) < 0.3:
            continue
        early_share = sum(1 for _, r in early if r == region) / len(early)
        late_share = sum(1 for _, r in late if r == region) / len(late)
        national_late = any((v["metrics"].get("handle") or "").lower() in NATIONAL_MEDIA for v, _ in late)
        if early_share >= 0.5 and len(early) >= 2:
            out["foyer"] = region
            # Né dans la région, puis majoritairement porté ailleurs ou repris par un média national.
            out["local_vers_national"] = len(ordered) >= 6 and (late_share < 0.5 or national_late)
            out["part_locale_debut"] = round(early_share, 2)
            out["part_locale_fin"] = round(late_share, 2)
    return out


# Racines de mots (pas de \b final) : « députée », « sénatrices », « secrétaire nationale »…
ELECTED = re.compile(r"\b(deput|senat|maire\b|adjoint au maire|adjointe au maire|conseill|elu\b|elue\b|candidat|ministre|"
                     r"eurodeput|porte parole|secretaire national|president de|presidente de|"
                     r"les republicains|rassemblement national|renaissance|france insoumise|insoumis|parti socialiste|"
                     r"reconquete|horizons|les ecologistes|parti communiste|lfi\b|\bps\b|\brn\b|\blr\b)")
MEDIA = re.compile(r"\b(media|journal|info|actu|radio|chaine|tv\b|tele|magazine|redaction|journalist|presse|quotidien|"
                   r"hebdo|podcast|news|nouvelles|compte officiel de|matin\b|depeche|meteo|emission|france [0-9]|politique\b)")
# Élus connus dont la bio ne le dit pas.
ELECTED_HANDLES = {"robert.menard_off"}


PARTY_HANDLES = {"renaissance", "lesrepublicains", "rassemblementnational", "franceinsoumise", "lafranceinsoumise",
                 "partisocialiste", "reconquete_z", "horizons_le_parti", "leslogistes", "lesecologistes"}


def account_type(bio: str | None, handle: str = "") -> str | None:
    """« élu » (élus, candidats, partis), « média » ou « créateur ». None si bio et nom muets."""
    if handle.lower() in PARTY_HANDLES:
        return "élu"
    if bio is None and not handle:
        return None
    b = f" {_norm(bio or '')} {_norm(handle.replace('.', ' ').replace('_', ' '))} "
    if ELECTED.search(b):
        return "élu"
    if MEDIA.search(b):
        return "média"
    return "créateur"


def fetch_bios(handles: list[tuple[str, str]]) -> dict[str, str]:
    """Bios des comptes (recherche de profils Oriane, 10 crédits par appel, 100 comptes par appel)."""
    from .sources import oriane
    cache = store.cache_get("local:bios") or {}
    todo = [(p, h) for p, h in handles if f"{p}:{h}" not in cache]
    if todo:
        api = oriane.Oriane()
        for platform in {p for p, _ in todo}:
            names = [h for p, h in todo if p == platform]
            for k in range(0, len(names), 100):
                body = {"operator": "and", "filters": {"platform": {"includes": [platform]},
                                                       "handle": {"exactMatch": {"values": names[k:k + 100], "operator": "or"}}}}
                for r in api.profiles(body, limit=100):
                    cache[f"{platform}:{r.get('handle')}"] = r.get("bio") or ""
        for p, h in todo:
            cache.setdefault(f"{p}:{h}", None)
        store.cache_set("local:bios", cache)
    return cache


def scouts(topics: list[dict], min_followers: int = 5000, max_followers: int = 150_000) -> list[dict]:
    """Comptes éclaireurs : peu connus, ils publient dans le premier quart de la vie de sujets qui ont grossi.
    Calculé sur nos données, gratuit. Les médias (nationaux et locaux) sont exclus : on cherche des sources."""
    items = {i["id"]: i for i in store.load_items("social")}
    local_media = {m for r in REGIONS.values() for m in r["medias"]}
    stats: dict[str, dict] = defaultdict(lambda: {"sujets": [], "avances": [], "videos": []})
    for t in topics:
        vids = sorted((items[v] for v in t["videos"] if v in items), key=lambda v: v["published_at"])
        if len(vids) < 8:
            continue
        times = [datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) for v in vids]
        median_t = times[len(times) // 2]
        for v, ts in zip(vids[: max(2, len(vids) // 4)], times):
            m = v["metrics"]
            handle = (m.get("handle") or "").lower()
            if (not min_followers <= (m.get("followers") or 0) <= max_followers or handle in NATIONAL_MEDIA
                    or handle in local_media or v["source"] != "oriane"):
                continue
            s = stats[v["account"]]
            if t["id"] in [x["id"] for x in s["sujets"]]:
                continue
            s["sujets"].append({"id": t["id"], "titre": t.get("titre") or t["sujet_type"]})
            s["avances"].append(max(0.0, (median_t - ts).total_seconds() / 86400))
            s["videos"].append(v)
    out = []
    for account, s in stats.items():
        v0 = s["videos"][0]
        m = v0["metrics"]
        regions = Counter(region_of(v)[0] for v in s["videos"])
        regions.pop(None, None)
        handle, platform = m.get("handle"), m.get("platform")
        out.append({
            "compte": handle or account, "plateforme": platform, "abonnes": m.get("followers"),
            "url": f"https://www.tiktok.com/@{handle}" if platform == "tiktok" else f"https://www.instagram.com/{handle}/",
            "region": regions.most_common(1)[0][0] if regions else None,
            "nb_sujets": len(s["sujets"]), "avance_moyenne_jours": round(sum(s["avances"]) / len(s["avances"]), 1),
            "sujets": [x["titre"] for x in s["sujets"]][:5],
            "exemple_url": v0["url"],
        })
    # Type de compte depuis la bio (les élus et les médias sont des sources différentes des créateurs).
    try:
        bios = fetch_bios([(a["plateforme"], a["compte"]) for a in out if a["plateforme"] and a["compte"]])
    except Exception:
        bios = store.cache_get("local:bios") or {}
    local_media = {m for r in REGIONS.values() for m in r["medias"]}
    for a in out:
        bio = bios.get(f"{a['plateforme']}:{a['compte']}")
        a["bio"] = (bio or "")[:200] or None
        a["type"] = "élu" if a["compte"] in ELECTED_HANDLES else account_type(bio, a["compte"] or "")
        if a["region"] is None and bio and any(pat.search(f" {_norm(bio)} ") for pat in _PATTERNS.values()):
            a["region"] = next(n for n, pat in _PATTERNS.items() if pat.search(f" {_norm(bio)} "))
    # Le plus utile en premier : créateurs avant médias et élus, puis plusieurs sujets vus tôt, puis l'avance.
    rank = {"créateur": 0, None: 1, "média": 2, "élu": 3}
    out.sort(key=lambda a: (rank[a["type"]], -a["nb_sujets"], -a["avance_moyenne_jours"], a["abonnes"] or 0))
    return out
