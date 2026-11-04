"""Preuve sur le passé : une histoire reprise par la presse était-elle visible avant sur TikTok et Instagram ?

1. `candidates()` (gratuit) : dans les archives de presse, les histoires reprises par plusieurs rédactions,
   avec la date du premier article.
2. `measure()` (Oriane, ~15 petits appels) : nombre de vidéos par jour sur l'histoire, avant et après
   le premier article ; avance = premier jour où les vidéos dépassent le quart de leur niveau du jour J.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from . import annotate, config, llm, store
from .embed import embed
from .snowball import SYSTEM as SEARCH_SYSTEM, Expressions
from .sources import oriane


def candidates(min_outlets: int = 4, min_age_days: int = 6, top: int = 15) -> list[dict]:
    notes = store.get_annotations(annotate.VERSION)
    press = [m for m in store.load_items("media") if m["id"] in notes and m["source"] in ("archive", "rss", "brut")]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).date().isoformat()
    vectors = embed([notes[m["id"]]["sujet"] for m in press])
    labels = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=0.25).fit_predict(vectors)
    out = []
    for label in set(labels):
        members = [press[i] for i in np.where(labels == label)[0]]
        outlets = {m["account"] for m in members}
        first = min(m["published_at"][:10] for m in members)
        if len(outlets) < min_outlets or first > cutoff:
            continue
        out.append({
            "histoire": Counter(notes[m["id"]]["sujet"] for m in members).most_common(1)[0][0],
            "premier_article": first,
            "premiere_redaction": min(members, key=lambda m: m["published_at"])["account"],
            "redactions": len(outlets), "articles": len(members),
            "titres": [m["text"][:100] for m in sorted(members, key=lambda m: m["published_at"])[:3]],
        })
    out.sort(key=lambda c: (-c["redactions"], -c["articles"]))
    return out[:top]


def measure(run_id: str, story: str, press_day: str, before: int = 10, after: int = 3) -> dict:
    found = llm.structured(run_id=run_id, purpose="preuve sur le passé", model=config.MODEL_BULK,
                           effort=config.EFFORT_BULK, system=SEARCH_SYSTEM, schema=Expressions,
                           max_tokens=400, thinking=False, prompt=f"Sujet : {story}")
    api = oriane.Oriane()
    completeness = store.cache_get("oriane:day_completeness") or {}
    d0 = date.fromisoformat(press_day)
    series = []
    for offset in range(-before, after + 1):
        day = (d0 + timedelta(days=offset)).isoformat()
        _, total = api.search({"format": {"includes": ["video"]}, "publishedAt": {"after": day, "before": day}},
                              [oriane.FRENCH, oriane.theme_query("preuve", found.expressions[:5])],
                              limit=1, projection="basic")
        c = completeness.get(day, 1.0) or 1.0
        series.append({"jour": day, "ecart": offset, "videos": round(total / c)})
    on_day = next(p["videos"] for p in series if p["ecart"] == 0) or max(p["videos"] for p in series) or 1
    rising = [p for p in series if p["ecart"] <= 0 and p["videos"] >= on_day / 4]
    lead = -rising[0]["ecart"] if rising else 0
    return {"histoire": story, "premier_article": press_day, "expressions": found.expressions[:5],
            "avance_reseaux_jours": lead, "serie": series, "appels": api.calls,
            "phrase": (f"Sur TikTok et Instagram, le sujet montait {lead} jour(s) avant le premier article de presse."
                       if lead else "Pas d'avance mesurable des réseaux sur la presse pour cette histoire.")}
