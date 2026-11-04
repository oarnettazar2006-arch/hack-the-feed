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


PRESS_GROUPS = {"traditionnel", "droite", "gauche"}
SOCIAL_GROUPS = {"brut", "concurrent"}


def coverage_known_since(medias: list[dict]) -> dict:
    """Pour chaque famille de médias, la date depuis laquelle TOUTES ses sources régulières sont connues.

    Une source qui n'a que 1 à 4 contenus est ignorée (trop peu pour dater sa couverture).
    """
    starts: dict[str, dict[str, str]] = {"presse": {}, "concurrents": {}}
    counts = Counter(m["account"] for m in medias)
    for m in medias:
        family = "presse" if m["account_group"] in PRESS_GROUPS else "concurrents" if m["account_group"] in SOCIAL_GROUPS else None
        if family and counts[m["account"]] >= 5:
            day = m["published_at"][:10]
            starts[family][m["account"]] = min(day, starts[family].get(m["account"], day))
    return {family: (max(v.values()) if v else None) for family, v in starts.items()}


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


def run(now: datetime | None = None) -> list[dict]:
    notes = store.get_annotations(annotate.VERSION)
    videos = [v for v in store.load_items("social") if v["id"] in notes]
    medias = [m for m in store.load_items("media") if m["id"] in notes]
    if not videos:
        return []
    # Avec Oriane, le score s'arrête au dernier jour indexé à au moins 50 % (les jours suivants sont ignorés).
    completeness = store.cache_get("oriane:day_completeness") or {}
    if now is None and completeness:
        complete_days = [d for d, c in completeness.items() if c >= 0.5]
        if complete_days:
            now = datetime.fromisoformat(max(complete_days) + "T23:59:59+00:00")
    now = now or max(_day(v["published_at"]) for v in videos)
    videos = [v for v in videos if _day(v["published_at"]) <= now]
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
        members = [kept[i] for i in idx]
        if len(members) < config.MIN_VIDEOS or len({v["account"] for v in members}) < config.MIN_CREATORS:
            continue
        recent = [v for v in members if _day(v["published_at"]) >= recent_start]
        base = [v for v in members if base_start <= _day(v["published_at"]) < recent_start]
        recent_per_day = sum(map(_w, recent)) / config.WINDOW_RECENT
        base_per_day = sum(map(_w, base)) / config.WINDOW_BASELINE
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
            days[_day(v["published_at"]).date().isoformat()] += _w(v)
        first_day = (now - timedelta(days=config.WINDOW_RECENT + config.WINDOW_BASELINE)).date()
        series = [{"jour": (first_day + timedelta(days=d)).isoformat(),
                   "videos": round(days.get((first_day + timedelta(days=d)).isoformat(), 0))}
                  for d in range(config.WINDOW_RECENT + config.WINDOW_BASELINE + 1)]

        member_notes = [notes[v["id"]] for v in members]
        themes = Counter(t for n in member_notes for t in n["themes"])
        tones = Counter(n["ton"] for n in member_notes)
        # Vidéo qui a lancé le sujet : la plus ancienne parmi celles qui ont surperformé.
        launchers = sorted(members, key=lambda v: (_day(v["published_at"]),))
        launcher = next((v for v in launchers
                         if _views(v, rates) / max(v["metrics"].get("followers", 1), 1) >= 2), launchers[0])
        top_videos = sorted(members, key=lambda v: -_views(v, rates))[:12]

        topics.append({
            "id": f"t{label}",
            "sujet_type": Counter(n["sujet"] for n in member_notes).most_common(1)[0][0],
            "politique": sum(n["politique"] for n in member_notes) > len(member_notes) / 2,
            "themes": [t for t, _ in themes.most_common(3)],
            "videos_total": round(sum(map(_w, members))),
            "videos_recentes": round(sum(map(_w, recent))),
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
            "score": accel * np.sqrt(creators_recent) * max(overperf, 0.01),
            "tons": dict(tones),
            "couverture": coverage,
            "couvert": covered,
            "couvert_par_brut": any(c["groupe"] == "brut" for c in coverage),
            "couverture_presse_depuis": known_since["presse"],
            "couverture_concurrents_depuis": known_since["concurrents"],
            "couverture_complete": coverage_complete,
            "etat": _state(accel, len(recent), len(members), covered, coverage_complete),
            "serie": series,
            "video_declencheur": launcher["id"],
            "videos_phares": [v["id"] for v in top_videos],
            "videos": [v["id"] for v in members],
            "affirmations": [{"video": v["id"], "ton": notes[v["id"]]["ton"], "affirmation": notes[v["id"]]["affirmation"]}
                             for v in members][:60],
        })

    topics.sort(key=lambda t: -t["score"])
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

    notes = store.get_annotations(annotate.VERSION)
    videos = [v for v in store.load_items("social")
              if v["id"] in notes and notes[v["id"]]["interet_public"] and notes[v["id"]].get("personnalites")]
    if not videos:
        return []
    now = now or max(_day(v["published_at"]) for v in videos)
    recent_start = now - timedelta(days=config.WINDOW_RECENT)
    base_start = recent_start - timedelta(days=config.WINDOW_BASELINE)
    known = {_name_key(n) for n in CANDIDATES + PUBLIC_FIGURES}
    known_last = {k.split()[-1] for k in known}

    mentions: dict[str, list[dict]] = {}
    spellings: dict[str, Counter] = {}
    for v in videos:
        for name in set(notes[v["id"]]["personnalites"]):
            key = _name_key(name)
            if len(key.split()) < 2:  # un nom seul (« Lisnard ») est rattaché au nom complet s'il existe
                key = next((k for k in mentions if k.split()[-1] == key), key)
            mentions.setdefault(key, []).append(v)
            spellings.setdefault(key, Counter())[name] += 1

    out = []
    for key, vids in mentions.items():
        vids = [v for v in vids if _day(v["published_at"]) <= now]
        recent = [v for v in vids if _day(v["published_at"]) >= recent_start]
        base = [v for v in vids if base_start <= _day(v["published_at"]) < recent_start]
        creators = len({v["account"] for v in recent})
        if len(vids) < config.MIN_VIDEOS // 2 or creators < 3:
            continue
        accel = (sum(map(_w, recent)) / config.WINDOW_RECENT + 1) / (sum(map(_w, base)) / config.WINDOW_BASELINE + 1)
        out.append({
            "nom": spellings[key].most_common(1)[0][0],
            "hors_liste": key not in known and key.split()[-1] not in known_last,
            "videos_total": round(sum(map(_w, vids))),
            "videos_recentes": round(sum(map(_w, recent))),
            "acceleration": round(accel, 2),
            "createurs_recents": creators,
            "score": round(accel * np.sqrt(creators), 3),
            "tons": dict(Counter(notes[v["id"]]["ton"] for v in vids)),
            "affirmations": [notes[v["id"]]["affirmation"] for v in sorted(recent, key=lambda v: -_w(v))[:5]],
            "videos": [v["id"] for v in vids],
        })
    out.sort(key=lambda p: (-p["score"]))
    return out
