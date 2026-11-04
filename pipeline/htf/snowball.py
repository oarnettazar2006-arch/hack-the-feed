"""Relance ciblée (« boule de neige ») des sujets imprévus.

Un sujet trouvé par le filet aveugle n'est connu que par ses vidéos les plus virales : on sait qu'il buzze,
pas combien il pèse. Haiku propose des expressions de recherche propres au sujet, puis Oriane donne
le nombre réel de vidéos par jour (1 appel minuscule par jour). Le volume, l'accélération et la courbe
du sujet sont alors remplacés par ces mesures.
"""
from datetime import datetime, timedelta

from pydantic import BaseModel

from . import analyze, config, llm, store
from .sources import oriane

SYSTEM = """Tu prépares une recherche dans un moteur de vidéos TikTok et Instagram françaises.
On te donne un sujet et ce qu'en disent des vidéos. Propose 3 à 5 expressions de recherche de 2 à 4 mots
qui retrouvent les vidéos de CE sujet précis et pas d'autres : noms propres, lieux, mots rares du sujet. Ignore les blagues et le second degré des vidéos.
Chaque expression exige que tous ses mots soient présents. Évite les mots courts ou génériques."""


class Expressions(BaseModel):
    expressions: list[str]


def _accel(series: list[dict], now: datetime) -> tuple[float, int, int]:
    recent_start = (now - timedelta(days=config.WINDOW_RECENT)).date().isoformat()
    base_start = (now - timedelta(days=config.WINDOW_RECENT + config.WINDOW_BASELINE)).date().isoformat()
    recent = sum(p["videos"] for p in series if p["jour"] >= recent_start)
    base = sum(p["videos"] for p in series if base_start <= p["jour"] < recent_start)
    accel = (recent / config.WINDOW_RECENT + 1) / (base / config.WINDOW_BASELINE + 1)
    return accel, recent, recent + base


def measure(run_id: str, topics: list[dict], max_topics: int = 3) -> dict:
    """Mesure le vrai volume des sujets imprévus les mieux classés. Modifie `topics` en place."""
    targets = [t for t in topics if t.get("imprevu")][:max_topics]
    if not targets:
        return {"sujets imprévus": 0}
    api = oriane.Oriane()
    completeness = store.cache_get("oriane:day_completeness") or {}
    days = sorted(p["jour"] for p in targets[0]["serie"])
    report = {}
    for topic in targets:
        found = llm.structured(
            run_id=run_id, purpose="relance ciblée", model=config.MODEL_BULK, effort=config.EFFORT_BULK,
            system=SYSTEM, schema=Expressions, max_tokens=400, thinking=False,
            prompt=f"Sujet : {topic['sujet_type']}\n" + "\n".join(f"- {a['affirmation']}" for a in topic["affirmations"][:15]),
        )
        query = oriane.theme_query("relance", found.expressions[:5])
        series = []
        for day in days:
            _, total = api.search({"format": {"includes": ["video"]}, "publishedAt": {"after": day, "before": day}},
                                  [oriane.FRENCH, query], limit=1, projection="basic")
            c = completeness.get(day, 1.0)
            series.append({"jour": day, "videos": round(total / c) if c else 0})
        complete = [d for d in days if completeness.get(d, 1.0) >= 0.5]
        now = datetime.fromisoformat((max(complete) if complete else days[-1]) + "T23:59:59+00:00")
        accel, recent, total = _accel(series, now)
        topic.update({
            "serie": series, "videos_total": total, "videos_recentes": recent,
            "signaux": {**topic["signaux"], "acceleration": round(accel, 2)},
            "volume_mesure": True, "expressions_relance": found.expressions[:5],
        })
        topic["etat"] = analyze._state(accel, recent, total, topic["couvert"])
        report[topic["sujet_type"][:60]] = {"expressions": found.expressions[:5], "vidéos mesurées": total,
                                            "accélération": round(accel, 2), "état": topic["etat"]}
    # Le classement tient compte des nouvelles accélérations.
    for t in topics:
        s = t["signaux"]
        t["score"] = round(s["acceleration"] * s["createurs_recents"] ** 0.5 * max(s["surperformance_mediane"], 0.01), 3)
    topics.sort(key=lambda t: -t["score"])
    for rank, t in enumerate(topics, 1):
        t["rang"] = rank
    report["appels Oriane"] = api.calls
    return report
