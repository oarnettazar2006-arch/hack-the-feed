"""Regroupement des vidéos en sujets, score d'émergence, état et couverture médias. Aucun appel payant."""
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


def _state(accel: float, recent: int, total: int, covered: bool) -> str:
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
        return "angle mort durable"
    return state


def run(now: datetime | None = None) -> list[dict]:
    notes = store.get_annotations(annotate.VERSION)
    videos = [v for v in store.load_items("social") if v["id"] in notes]
    medias = [m for m in store.load_items("media") if m["id"] in notes]
    if not videos:
        return []
    now = now or max(_day(v["published_at"]) for v in videos)
    recent_start = now - timedelta(days=config.WINDOW_RECENT)
    base_start = recent_start - timedelta(days=config.WINDOW_BASELINE)

    # On ne regroupe que les vidéos d'intérêt public ; le reste est compté à part.
    kept = [v for v in videos if notes[v["id"]]["interet_public"]]
    vectors = embed([notes[v["id"]]["sujet"] for v in kept])
    labels = _cluster(vectors)
    media_vectors = embed([notes[m["id"]]["sujet"] for m in medias]) if medias else np.zeros((0, vectors.shape[1]))

    topics = []
    for label in sorted(set(labels)):
        idx = np.where(labels == label)[0]
        members = [kept[i] for i in idx]
        if len(members) < config.MIN_VIDEOS or len({v["account"] for v in members}) < config.MIN_CREATORS:
            continue
        recent = [v for v in members if _day(v["published_at"]) >= recent_start]
        base = [v for v in members if base_start <= _day(v["published_at"]) < recent_start]
        recent_per_day = len(recent) / config.WINDOW_RECENT
        base_per_day = len(base) / config.WINDOW_BASELINE
        accel = (recent_per_day + 1) / (base_per_day + 1)
        creators_recent = len({v["account"] for v in recent})
        ratios = [v["metrics"].get("views", 0) / max(v["metrics"].get("followers", 0), 1) for v in recent] or [0]
        overperf = float(np.median(ratios))
        views = sum(v["metrics"].get("views", 0) for v in recent)
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

        days = Counter(_day(v["published_at"]).date().isoformat() for v in members)
        first_day = (now - timedelta(days=config.WINDOW_RECENT + config.WINDOW_BASELINE)).date()
        series = [{"jour": (first_day + timedelta(days=d)).isoformat(),
                   "videos": days.get((first_day + timedelta(days=d)).isoformat(), 0)}
                  for d in range(config.WINDOW_RECENT + config.WINDOW_BASELINE + 1)]

        member_notes = [notes[v["id"]] for v in members]
        themes = Counter(t for n in member_notes for t in n["themes"])
        tones = Counter(n["ton"] for n in member_notes)
        # Vidéo qui a lancé le sujet : la plus ancienne parmi celles qui ont surperformé.
        launchers = sorted(members, key=lambda v: (_day(v["published_at"]),))
        launcher = next((v for v in launchers
                         if v["metrics"].get("views", 0) / max(v["metrics"].get("followers", 1), 1) >= 2), launchers[0])
        top_videos = sorted(members, key=lambda v: -v["metrics"].get("views", 0))[:12]

        topics.append({
            "id": f"t{label}",
            "sujet_type": Counter(n["sujet"] for n in member_notes).most_common(1)[0][0],
            "politique": sum(n["politique"] for n in member_notes) > len(member_notes) / 2,
            "themes": [t for t, _ in themes.most_common(3)],
            "videos_total": len(members),
            "videos_recentes": len(recent),
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
            "etat": _state(accel, len(recent), len(members), covered),
            "serie": series,
            "video_declencheur": launcher["id"],
            "videos_phares": [v["id"] for v in top_videos],
            "affirmations": [{"video": v["id"], "ton": notes[v["id"]]["ton"], "affirmation": notes[v["id"]]["affirmation"]}
                             for v in members][:60],
        })

    topics.sort(key=lambda t: -t["score"])
    for rank, t in enumerate(topics, 1):
        t["rang"] = rank
        t["score"] = round(float(t["score"]), 3)
    return topics
