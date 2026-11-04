"""Le jour J : `check` vérifie tout avant de commencer, `run` enchaîne la chaîne complète."""
import json
import os
import time

import httpx

from . import analyze, annotate, config, export, llm, showcase, store
from .sources import media, oriane


def check(with_oriane: bool = False) -> dict:
    """Vérifications gratuites (sauf --oriane : 1 appel minuscule)."""
    report = {}
    for key in ("ANTHROPIC_API_KEY", "ORIANE_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        report[f".env {key}"] = "ok" if os.environ.get(key) else "MANQUANT"

    try:
        ids = {m.id for m in llm.client().models.list()}
        report["Anthropic"] = "ok" if {config.MODEL_BULK, config.MODEL_SHOWCASE} <= ids else f"modèles absents : {ids}"
    except Exception as e:
        report["Anthropic"] = f"ERREUR {e.__class__.__name__}"
    spent = store.spent()
    report["budget Claude"] = f"{spent:.2f} $ dépensés sur {config.BUDGET_TOTAL_USD} $ (reste {config.BUDGET_TOTAL_USD - spent:.2f} $)"

    try:
        tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).json()
        names = {m["name"].split(":")[0] for m in tags.get("models", [])}
        report["Ollama"] = "ok" if config.EMBED_MODEL in names else f"modèle {config.EMBED_MODEL} absent (ollama pull {config.EMBED_MODEL})"
    except Exception:
        report["Ollama"] = "ÉTEINT : lancer l'application Ollama"

    try:
        with export._client() as http:
            missing = [t for t in ("topics", "topic_positions", "topic_coverage", "videos", "brief", "personnalites")
                       if http.get(f"/{t}", params={"select": "*", "limit": 1}).status_code != 200]
        report["Supabase"] = "ok" if not missing else f"tables inaccessibles : {missing}"
    except Exception as e:
        report["Supabase"] = f"ERREUR {str(e)[:100]}"

    if with_oriane:
        try:
            ping = oriane.ping()
            report["Oriane"] = f"ok ({ping['authentification']}, {ping['résultats sur 2 jours pour « loyer »']} vidéos test)"
        except Exception as e:
            report["Oriane"] = f"ERREUR {str(e)[:150]}"
    else:
        report["Oriane"] = "non testé (ajouter --oriane : 1 appel)"
    report["prêt"] = all(v == "ok" or k in ("budget Claude", "Oriane") for k, v in report.items()) and \
        not str(report.get("Oriane", "")).startswith("ERREUR")
    return report


def run(run_id: str, days: int, per_day: int, top: int, collect: bool, ask) -> dict:
    """Collecte → annotation → analyse → fiches → export. `ask(question)` renvoie True pour continuer."""
    steps, started = {}, time.time()

    def step(name, fn):
        t = time.time()
        print(f"\n▶ {name}", flush=True)
        result = fn()
        steps[name] = {"durée (s)": round(time.time() - t), "résultat": result}
        print(json.dumps(result, ensure_ascii=False, default=str)[:600], flush=True)
        return result

    if collect:
        print(json.dumps(oriane.plan(days, per_day), ensure_ascii=False, indent=1))
        if not ask("Lancer la collecte Oriane (crédits) ?"):
            return {"arrêt": "collecte annulée"}
        step("collecte Oriane (thèmes + filet aveugle)", lambda: oriane.collect_social(days, per_day))
        step("collecte Oriane (comptes médias)", oriane.collect_media)
    step("collecte presse et YouTube", media.collect)
    step("annotation des vidéos (Haiku)", lambda: annotate.annotate_social(run_id))
    step("annotation des médias (Haiku)", lambda: annotate.annotate_media(run_id))

    def do_analyze():
        topics = analyze.run()
        config.OUT_DIR.mkdir(parents=True, exist_ok=True)
        (config.OUT_DIR / "brief.json").unlink(missing_ok=True)
        (config.OUT_DIR / "topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=2))
        persons = analyze.people()
        (config.OUT_DIR / "people.json").write_text(json.dumps(persons, ensure_ascii=False, indent=2))
        return {"sujets": len(topics), "imprévus": sum(t["imprevu"] for t in topics),
                "personnalités hors liste": [p["nom"] for p in persons if p["hors_liste"]][:5]}

    step("regroupement et score", do_analyze)

    def do_showcase():
        topics = json.loads((config.OUT_DIR / "topics.json").read_text())
        cards = showcase.build_cards(run_id, topics, top)
        brief = showcase.morning_brief(cards)
        (config.OUT_DIR / "topics.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2))
        (config.OUT_DIR / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
        return {"fiches": min(top, len(cards)), "brief": [b["titre"] for b in brief]}

    step("fiches Opus et brief", do_showcase)
    step("export Supabase", export.run)
    return {"durée totale (min)": round((time.time() - started) / 60, 1),
            "dépense Claude de l'exécution ($)": round(store.spent(run_id), 3),
            "dépense Claude totale ($)": round(store.spent(), 3)}
