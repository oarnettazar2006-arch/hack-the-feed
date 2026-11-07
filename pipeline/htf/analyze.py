"""Regroupement des vidéos en sujets, score d'émergence, état et couverture médias. Aucun appel payant."""
import unicodedata
from collections import Counter
from datetime import datetime, timedelta

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from . import annotate, config, store
from .embed import embed


def _day(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _cluster(vectors: np.ndarray) -> np.ndarray:
    if len(vectors) < 2:
        return np.zeros(len(vectors), dtype=int)
    model = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=config.CLUSTER_DISTANCE
    )
    return model.fit_predict(vectors)


def _w(v: dict) -> float:
    """Nombre de vidéos réelles qu'une vidéo de l'échantillon représente (1 pour les données sans poids)."""
    return v["metrics"].get("weight", 1) or 0


def _engagement_rates(videos: list[dict]) -> dict[str, float]:
    """Taux d'interactions par vue, médian par plateforme, mesuré sur les vidéos qui ont leurs vues."""
    by_platform: dict[str, list[float]] = {}
    for v in videos:
        m = v["metrics"]
        views = m.get("views")
        if views:
            inter = m.get("likes", 0) + m.get("comments", 0) + m.get("shares", 0)
            by_platform.setdefault(m.get("platform") or "?", []).append(inter / views)
    rates = {p: float(np.median(r)) for p, r in by_platform.items() if len(r) >= 5}
    everything = [x for r in by_platform.values() for x in r]
    rates["*"] = float(np.median(everything)) if everything else 0.05
    return rates


def _views(v: dict, rates: dict[str, float]) -> float:
    """Vues réelles, ou estimées par les interactions quand la plateforme ne les publie pas."""
    m = v["metrics"]
    if m.get("views"):
        return m["views"]
    inter = m.get("likes", 0) + m.get("comments", 0) + m.get("shares", 0)
    rate = rates.get(m.get("platform") or "?", rates["*"]) or rates["*"] or 0.05
    return inter / rate


def _shingles(text: str, k: int = 5) -> set[str]:
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {" ".join(words[i:i + k]) for i in range(max(len(words) - k + 1, 0))}


def coordination(members: list[dict]) -> dict | None:
    """Vidéos au texte presque identique publiées par des comptes différents à moins de 48 h d'écart.

    Ne prouve pas une manipulation (reprises, sons tendance), mais c'est un signal à vérifier avant de traiter.
    Les fausses vidéos de test, faites de phrases répétées, sont exclues.
    """
    real = [v for v in members if v["source"] != "fake"]
    sigs = [(v, _shingles(v["text"].split("\nLégende")[0][:600])) for v in real]
    sigs = [(v, s) for v, s in sigs if len(s) >= 8]
    flagged, accounts = set(), set()
    for i, (a, sa) in enumerate(sigs):
        for b, sb in sigs[i + 1:]:
            if a["account"] == b["account"]:
                continue
            if abs((_day(a["published_at"]) - _day(b["published_at"])).total_seconds()) > 48 * 3600:
                continue
            if len(sa & sb) / len(sa | sb) >= 0.6:
                flagged |= {a["id"], b["id"]}
                accounts |= {a["account"], b["account"]}
    if len(flagged) < 5 or len(accounts) < 3 or len(flagged) / max(len(real), 1) < 0.2:
        return None
    example = next(v for v in real if v["id"] in flagged)
    return {"videos": len(flagged), "comptes": len(accounts), "part": round(len(flagged) / len(real), 2),
            "exemple": example["text"][:200]}


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalnum() else " " for c in plain).split()


def locate(citation: str, metrics: dict) -> dict:
    """Retrouve une citation dans la vidéo : seconde du passage dit, ou image où le texte est écrit.

    Rien n'est renvoyé si moins de 60 % des mots de la citation sont dans le passage (citation non vérifiée).
    """
    target = set(_words(citation))
    if len(target) < 3:
        return {}
    best, where = 0.0, {}
    for i, (start, text) in enumerate(metrics.get("chunks") or []):
        # Une citation peut chevaucher deux passages consécutifs.
        nxt = (metrics["chunks"][i + 1][1] if i + 1 < len(metrics["chunks"]) else "")
        score = len(target & set(_words(text + " " + nxt))) / len(target)
        if score > best:
            best, where = score, {"seconde": start}
    for ts, url, text in metrics.get("frames") or []:
        score = len(target & set(_words(text))) / len(target)
        if score > best:
            best, where = score, {"seconde": ts, "image": url}
    return where if best >= 0.6 else {}


def evidence(members: list[dict], notes: dict, rates: dict) -> dict | None:
    """Ce que seule la lecture de la vidéo permettait de voir : part des vidéos dont la légende ne dit rien du sujet."""
    read = [v for v in members if "legende_suffit" in notes[v["id"]]]
    if not read:
        return None
    hidden = [v for v in read if not notes[v["id"]]["legende_suffit"]]
    quotes, accounts = [], set()
    for v in sorted(read, key=lambda v: -_views(v, rates)):
        n = notes[v["id"]]
        if not n.get("citation") or v["account"] in accounts or n["canal"] == "légende":
            continue
        accounts.add(v["account"])
        quotes.append({"video": v["id"], "compte": v["account"], "canal": n["canal"], "citation": n["citation"],
                       "url": v["url"], **locate(n["citation"], v["metrics"])})
        if len(quotes) == 6:
            break
    return {
        "videos_lues": len(read),
        "part_hors_legende": round(len(hidden) / len(read), 2),
        "canaux": dict(Counter(notes[v["id"]]["canal"] for v in read)),
        "reactions": dict(Counter(notes[v["id"]]["reaction_public"] for v in read
                                  if notes[v["id"]]["reaction_public"] != "sans commentaires")),
        "citations": quotes,
    }


def pivot(members: list[dict], rates: dict) -> tuple[dict, dict]:
    """La vidéo qui a fait basculer le sujet.

    Parmi les vidéos qui ont dépassé l'audience habituelle de leur créateur (vues ≥ 2 × abonnés),
    celle après laquelle le sujet a le plus accéléré : vidéos des 48 h suivantes comparées aux 48 h précédentes.
    À défaut, la plus ancienne vidéo du sujet.
    """
    window = timedelta(hours=48)
    dated = [(_day(v["published_at"]), _w(v), v) for v in members]
    best, best_key, effect = None, None, {}
    for t, _, v in dated:
        if _views(v, rates) < 2 * max(v["metrics"].get("followers", 0), 1):
            continue
        before = sum(w for d, w, o in dated if t - window <= d < t)
        after = sum(w for d, w, o in dated if t <= d < t + window and o is not v)
        key = ((after + 1) / (before + 1), _views(v, rates))
        if best_key is None or key > best_key:
            best, best_key, effect = v, key, {"avant_48h": round(before), "apres_48h": round(after)}
    if best is None:
        best = min(members, key=lambda v: _day(v["published_at"]))
    return best, effect


# Familles par type de source (et non par orientation) : la presse écrite a 14 jours d'archives,
# les vidéos sur les réseaux (YouTube, puis TikTok/Instagram via Oriane) ont leur propre historique.
PRESS_SOURCES = {"rss", "archive", "brut"}
SOCIAL_SOURCES = {"youtube", "oriane"}


def coverage_known_since(medias: list[dict]) -> dict:
    """Pour chaque famille de sources, la date depuis laquelle toutes ses sources régulières sont connues.

    Une même rédaction peut apparaître dans les deux familles (Le Monde : articles et vidéos).
    Une source qui n'a que 1 à 4 contenus est ignorée (trop peu pour dater sa couverture).
    """
    starts: dict[str, dict[str, list[str]]] = {"presse": {}, "concurrents": {}}
    for m in medias:
        family = "presse" if m["source"] in PRESS_SOURCES else "concurrents" if m["source"] in SOCIAL_SOURCES else None
        if family:
            starts[family].setdefault(m["account"], []).append(m["published_at"][:10])
    known = {}
    for family, by_account in starts.items():
        firsts = [min(days) for days in by_account.values() if len(days) >= 5]
        known[family] = max(firsts) if firsts else None
    return known


STATE_ORDER = {"à traiter maintenant": 0, "course de vitesse": 1, "à surveiller": 2, "signal faible": 2.5,
               "déjà repéré": 3,
               "en hausse": 3, "angle mort durable": 4, "stable": 5, "en baisse": 6}


def _state(accel: float, recent: int, total: int, covered: bool, coverage_complete: bool = True) -> str:
    if accel >= 2.5 and recent >= config.MIN_VIDEOS:
        state = "en forte hausse"
    elif accel >= 1.5:
        state = "petit mais en accélération" if total < 60 else "en hausse"
    elif accel < 0.7:
        state = "en baisse"
    else:
        state = "stable"
    if state in ("en forte hausse", "en hausse"):
        return "course de vitesse" if covered else "à traiter maintenant"
    if state == "petit mais en accélération":
        return "à surveiller" if not covered else "déjà repéré"
    if state == "stable" and total >= 60 and not covered:
        # Un angle mort ne s'affirme que si l'on connaît la couverture de toute la période.
        return "angle mort durable" if coverage_complete else "stable"
    return state


def _last_complete_day() -> datetime | None:
    """Avec Oriane, l'analyse s'arrête au dernier jour indexé à au moins 50 % (les jours suivants sont ignorés)."""
    completeness = store.cache_get("oriane:day_completeness") or {}
    complete_days = [d for d, c in completeness.items() if c >= 0.5]
    return datetime.fromisoformat(max(complete_days) + "T23:59:59+00:00") if complete_days else None


def _last_fresh_day(threshold: float = 0.1) -> datetime | None:
    completeness = store.cache_get("oriane:day_completeness") or {}
    days = [d for d, c in completeness.items() if c >= threshold]
    return datetime.fromisoformat(max(days) + "T23:59:59+00:00") if days else None


def run(now: datetime | None = None) -> list[dict]:
    notes = annotate.notes()
    videos = [v for v in store.load_items("social") if v["id"] in notes]
    medias = [m for m in store.load_items("media") if m["id"] in notes]
    if not videos:
        return []
    # Avec Oriane, le score s'arrête au dernier jour indexé à au moins 50 % (les jours suivants sont ignorés).
    explicit_now = now is not None
    now = now or _last_complete_day() or max(_day(v["published_at"]) for v in videos)
    # Signaux faibles : on lit aussi les jours indexés à au moins 10 % après `now` (retard d'Oriane),
    # en comptant les vidéos sans les extrapoler. Le score principal, lui, s'arrête à `now`.
    fresh_end = now if explicit_now else max(now, _last_fresh_day() or now)
    fresh_start = fresh_end - timedelta(days=4)
    videos = [v for v in videos if _day(v["published_at"]) <= fresh_end]
    recent_start = now - timedelta(days=config.WINDOW_RECENT)
    base_start = recent_start - timedelta(days=config.WINDOW_BASELINE)

    rates = _engagement_rates(videos)

    # On ne regroupe que les vidéos d'intérêt public ; le reste est compté à part.
    kept = [v for v in videos if notes[v["id"]]["interet_public"]]
    vectors = embed([notes[v["id"]]["sujet"] for v in kept])
    labels = _cluster(vectors)
    media_vectors = embed([notes[m["id"]]["sujet"] for m in medias]) if medias else np.zeros((0, vectors.shape[1]))
    known_since = coverage_known_since(medias)

    topics = []
    for label in sorted(set(labels)):
        idx = np.where(labels == label)[0]
        everyone = [kept[i] for i in idx]
        members = [v for v in everyone if _day(v["published_at"]) <= now]
        main = len(members) >= config.MIN_VIDEOS and len({v["account"] for v in members}) >= config.MIN_CREATORS
        fresh = [v for v in everyone if _day(v["published_at"]) >= fresh_start]
        # Signal faible : trop petit pour le radar, mais neuf (70 % des vidéos dans les 5 derniers jours lisibles)
        # et porté par au moins 3 créateurs différents. C'est ce qu'il faut voir avant que ça devienne une tendance.
        weak = (not main and len(everyone) >= 3 and len({v["account"] for v in fresh}) >= 3
                and len(fresh) / len(everyone) >= 0.7)
        if not main and not weak:
            continue
        if weak:
            members = everyone
        recent = fresh if weak else [v for v in members if _day(v["published_at"]) >= recent_start]
        base = [v for v in members if base_start <= _day(v["published_at"]) < recent_start]
        w = (lambda v: 1.0) if weak else _w  # jours partiels : on compte, on n'extrapole pas
        recent_per_day = sum(map(w, recent)) / (5 if weak else config.WINDOW_RECENT)
        base_per_day = sum(map(w, base)) / config.WINDOW_BASELINE
        accel = (recent_per_day + 1) / (base_per_day + 1)
        creators_recent = len({v["account"] for v in recent})
        ratios = [_views(v, rates) / max(v["metrics"].get("followers", 0), 1) for v in recent] or [0]
        overperf = float(np.median(ratios))
        views = sum(_views(v, rates) for v in recent)
        engagement = sum(3 * v["metrics"].get("shares", 0) + 2 * v["metrics"].get("comments", 0)
                         + v["metrics"].get("likes", 0) for v in recent) / max(views, 1)

        centroid = vectors[idx].mean(axis=0)
        centroid /= np.linalg.norm(centroid) or 1
        sims = media_vectors @ centroid if len(media_vectors) else np.array([])
        order = np.argsort(-sims)[:5]
        coverage = [
            {"media": medias[i]["account"], "groupe": medias[i]["account_group"], "titre": medias[i]["text"][:140],
             "url": medias[i]["url"], "date": medias[i]["published_at"], "similarite": round(float(sims[i]), 3)}
            for i in order if sims[i] >= config.COVERAGE_SIMILARITY
        ]
        covered = bool(coverage)
        base_day = base_start.date().isoformat()
        coverage_complete = all(d is not None and d <= base_day for d in known_since.values())

        days = Counter()
        for v in members:
            days[_day(v["published_at"]).date().isoformat()] += w(v)
        first_day = (now - timedelta(days=config.WINDOW_RECENT + config.WINDOW_BASELINE)).date()
        series = [{"jour": (first_day + timedelta(days=d)).isoformat(),
                   "videos": round(days.get((first_day + timedelta(days=d)).isoformat(), 0))}
                  for d in range(config.WINDOW_RECENT + config.WINDOW_BASELINE + 1 + ((fresh_end - now).days if weak else 0))]

        member_notes = [notes[v["id"]] for v in members]
        themes = Counter(t for n in member_notes for t in n["themes"])
        tones = Counter(n["ton"] for n in member_notes)
        launcher, launch_effect = pivot(members, rates)
        from . import politics
        cited = Counter(n for note in member_notes for n in set(annotate.names(note)))
        figures = [n for n, _ in cited.most_common() if politics.is_campaign_figure(n)]
        campaign_share = sum(1 for note in member_notes
                             if any(politics.is_campaign_figure(n) for n in annotate.names(note))) / len(member_notes)
        campaign_net = sum(1 for v in members if str(v["metrics"].get("theme_query", "")).startswith("campagne 2027"))
        top_videos = sorted(members, key=lambda v: -_views(v, rates))[:12]

        topics.append({
            "id": f"t{label}",
            "sujet_type": Counter(n["sujet"] for n in member_notes).most_common(1)[0][0],
            "politique": sum(n["politique"] for n in member_notes) > len(member_notes) / 2,
            "themes": [t for t, _ in themes.most_common(3)],
            # Sujet de campagne : une personnalité de la campagne dans au moins un quart des vidéos,
            # ou la majorité des vidéos ramenées par les filets « campagne 2027 » (avec au moins une personnalité citée).
            "campagne": bool(figures) and (campaign_share >= 0.25 or campaign_net > len(members) / 2),
            "personnalites": figures[:4],
            "camps": dict(Counter(politics.affiliation(n)[1] for n in figures[:8])),
            "videos_total": round(sum(map(w, members))),
            "videos_recentes": round(sum(map(w, recent))),
            "videos_echantillon": len(members),
            # Sujet trouvé uniquement par le filet aveugle : aucun de nos thèmes ne l'avait prévu.
            "imprevu": all(v["metrics"].get("theme_query") == "veille ouverte" for v in members),
            "coordination": coordination(members),
            "vues_estimees": sum(1 for v in members if not v["metrics"].get("views")),
            "signaux": {
                "acceleration": round(accel, 2),
                "createurs_recents": creators_recent,
                "surperformance_mediane": round(overperf, 2),
                "engagement": round(engagement, 3),
            },
            # Surperformance plafonnée à ×3 : un seul compte viral ne doit pas dominer le classement (constaté le 7/11).
            "score": accel * np.sqrt(creators_recent) * min(max(overperf, 0.01), 3.0),
            "tons": dict(tones),
            "couverture": coverage,
            "couvert": covered,
            "couvert_par_brut": any(c["groupe"] == "brut" for c in coverage),
            "couverture_presse_depuis": known_since["presse"],
            "couverture_concurrents_depuis": known_since["concurrents"],
            "couverture_complete": coverage_complete,
            "etat": ("déjà repéré" if covered else "signal faible") if weak
                    else _state(accel, len(recent), len(members), covered, coverage_complete),
            "signal_faible": weak,
            "vu_jusqu_au": (fresh_end if weak else now).date().isoformat(),
            "serie": series,
            "video_declencheur": launcher["id"],
            "declencheur_effet": launch_effect,
            "preuve": evidence(members, notes, rates),
            "videos_phares": [v["id"] for v in top_videos],
            "videos": [v["id"] for v in members],
            "affirmations": [{"video": v["id"], "ton": notes[v["id"]]["ton"], "affirmation": notes[v["id"]]["affirmation"]}
                             for v in members][:60],
        })

    # L'état passe d'abord : un sujet qui monte est toujours devant un sujet stable ou en baisse.
    topics.sort(key=lambda t: (STATE_ORDER.get(t["etat"], 5), -t["score"]))
    for rank, t in enumerate(topics, 1):
        t["rang"] = rank
        t["score"] = round(float(t["score"]), 3)
    return topics


def _name_key(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return " ".join(plain.replace("-", " ").split())


def people(now: datetime | None = None) -> list[dict]:
    """Personnalités citées dans les vidéos, classées par émergence. Signale celles absentes de nos listes."""
    from .sources.oriane import CANDIDATES, PUBLIC_FIGURES
    from . import politics

    notes = annotate.notes()
    videos = [v for v in store.load_items("social")
              if v["id"] in notes and notes[v["id"]]["interet_public"] and notes[v["id"]].get("personnalites")]
    if not videos:
        return []
    rates = _engagement_rates(videos)
    now = now or _last_complete_day() or max(_day(v["published_at"]) for v in videos)
    recent_start = now - timedelta(days=config.WINDOW_RECENT)
    base_start = recent_start - timedelta(days=config.WINDOW_BASELINE)
    known = {_name_key(n) for n in CANDIDATES + PUBLIC_FIGURES}
    known_last = {k.split()[-1] for k in known}

    mentions: dict[str, list[dict]] = {}
    spellings: dict[str, Counter] = {}
    for v in videos:
        for name in set(annotate.names(notes[v["id"]])):
            key = _name_key(name)
            if len(key.split()) < 2:  # un nom seul (« Lisnard ») est rattaché au nom complet s'il existe
                key = next((k for k in mentions if k.split()[-1] == key), key)
            mentions.setdefault(key, []).append((v, name))
            spellings.setdefault(key, Counter())[name] += 1

    out = []
    for key, cited in mentions.items():
        cited = [(v, name) for v, name in cited if _day(v["published_at"]) <= now]
        vids = [v for v, _ in cited]
        recent = [v for v in vids if _day(v["published_at"]) >= recent_start]
        base = [v for v in vids if base_start <= _day(v["published_at"]) < recent_start]
        creators = len({v["account"] for v in recent})
        # Élargi le 7/11 : une personnalité de la campagne reste visible même si peu de créateurs en parlent
        # cette semaine (c'est justement l'information « en baisse »). Les inconnues gardent un seuil plus haut.
        nom = spellings[key].most_common(1)[0][0]
        parti, camp = politics.affiliation(nom)
        all_creators = len({v["account"] for v in vids})
        if camp in (None, "international"):
            if len(vids) < config.MIN_VIDEOS // 2 or creators < 3:
                continue
        elif len(vids) < 3 or all_creators < 2:
            continue
        accel = (sum(map(_w, recent)) / config.WINDOW_RECENT + 1) / (sum(map(_w, base)) / config.WINDOW_BASELINE + 1)
        names_of = {v["id"]: name for v, name in cited}
        treat = Counter(annotate.treatment(notes[v["id"]], name) for v, name in cited)
        n_treat = sum(treat.values()) or 1
        ratios = [_views(v, rates) / max(v["metrics"].get("followers", 0), 1) for v in recent]
        recent_views = sum(_views(v, rates) for v in recent)
        recent_inter = sum(v["metrics"].get("likes", 0) + v["metrics"].get("comments", 0)
                           + v["metrics"].get("shares", 0) for v in recent)
        days = Counter(_day(v["published_at"]).date().isoformat() for v in vids)
        first_day = (now - timedelta(days=config.WINDOW_RECENT + config.WINDOW_BASELINE)).date()
        top = max(vids, key=lambda v: _views(v, rates))
        out.append({
            "nom": nom,
            "parti": parti,
            "camp": camp,
            "tendance": "monte" if accel >= 1.5 else "baisse" if accel < 0.7 else "stable",
            # (favorable − critique − ironique) / vidéos : de −1 (attaqué partout) à +1 (soutenu partout).
            "solde": round((treat["favorable"] - treat["critique"] - treat["ironique"]) / n_treat, 2),
            "surperformance": round(float(np.median(ratios)), 2) if ratios else None,
            "taux_engagement": round(recent_inter / recent_views, 4) if recent_views else None,
            "serie": [{"jour": (first_day + timedelta(days=d)).isoformat(),
                       "videos": days.get((first_day + timedelta(days=d)).isoformat(), 0)}
                      for d in range(config.WINDOW_RECENT + config.WINDOW_BASELINE + 1)],
            "video_phare": top["id"], "video_phare_url": top["url"], "video_phare_compte": top["account"],
            "video_phare_traitement": annotate.treatment(notes[top["id"]], names_of[top["id"]]),
            "hors_liste": camp != "international" and key not in known and key.split()[-1] not in known_last,
            "videos_total": round(sum(map(_w, vids))),
            "videos_recentes": round(sum(map(_w, recent))),
            "acceleration": round(accel, 2),
            "createurs_recents": creators,
            "score": round(accel * np.sqrt(creators), 3),
            # Comment les vidéos présentent la personne (et non le ton général de la vidéo).
            "tons": dict(Counter(annotate.treatment(notes[v["id"]], name) for v, name in cited)),
            "reactions": dict(Counter(notes[v["id"]]["reaction_public"] for v in vids
                                      if notes[v["id"]].get("reaction_public", "sans commentaires") != "sans commentaires")),
            # Totaux des vidéos lues (échantillon, sans extrapolation) sur la période récente.
            "vues": round(sum(_views(v, rates) for v in recent)),
            "interactions": sum(v["metrics"].get("likes", 0) + v["metrics"].get("comments", 0)
                                + v["metrics"].get("shares", 0) for v in recent),
            "affirmations": [notes[v["id"]]["affirmation"] for v in sorted(recent, key=lambda v: -_w(v))[:5]],
            "videos": [v["id"] for v in vids],
        })
    # Part de voix : part des vues récentes de toutes les personnalités françaises suivies.
    total = sum(p["vues"] for p in out if p["camp"] not in (None, "international")) or 1
    for p in out:
        p["part_de_voix"] = round(p["vues"] / total, 3) if p["camp"] not in (None, "international") else None
    out.sort(key=lambda p: (-p["score"]))
    # Sondages (Wikipédia, commande `polls`) : score moyen, surexposition, et courbe longue des vidéos si mesurée.
    from . import polls
    out = polls.overexposure(out, now.date())
    for p in out:
        p["historique_videos"] = store.cache_get(f"polls:history:{p['nom']}")
    return out
