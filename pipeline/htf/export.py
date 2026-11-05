"""Export de topics.json et brief.json vers Supabase (API REST, clé service_role)."""
import json
import os

import httpx

from . import annotate, config, store


def _client() -> httpx.Client:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY doivent être remplis dans .env")
    return httpx.Client(
        base_url=url.rstrip("/") + "/rest/v1",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Prefer": "return=minimal"},
        timeout=60,
    )


def _insert(http: httpx.Client, table: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), 500):
        r = http.post(f"/{table}", content=json.dumps(rows[i:i + 500], ensure_ascii=False, default=str))
        if r.status_code >= 400:
            hint = " (lancer supabase/reload_schema.sql si une colonne vient d'être ajoutée)" if "column" in r.text else ""
            raise RuntimeError(f"Supabase {r.status_code} sur {table} : {r.text[:300]}{hint}")


def run() -> dict:
    topics = json.loads((config.OUT_DIR / "topics.json").read_text())
    brief_path = config.OUT_DIR / "brief.json"
    brief = json.loads(brief_path.read_text()) if brief_path.exists() else []
    # Garde-fou : un brief ne part que s'il désigne les mêmes sujets, avec les mêmes titres, que l'analyse.
    titles = {t["id"]: t.get("titre") for t in topics}
    if any(titles.get(b["sujet"]) != b["titre"] for b in brief):
        brief = []
    people_path = config.OUT_DIR / "people.json"
    persons = json.loads(people_path.read_text()) if people_path.exists() else []
    notes = annotate.notes()
    items = {i["id"]: i for i in store.load_items("social")}

    topic_rows, positions, coverage, videos = [], [], [], []
    for t in topics:
        s = t["signaux"]
        topic_rows.append({
            "id": t["id"], "rang": t["rang"], "etat": t["etat"], "titre": t.get("titre"), "sujet_type": t["sujet_type"],
            "politique": t["politique"], "themes": t["themes"], "videos_total": t["videos_total"],
            "videos_recentes": t["videos_recentes"], "acceleration": s["acceleration"],
            "createurs_recents": s["createurs_recents"], "surperformance": s["surperformance_mediane"],
            "engagement": s["engagement"], "score": t["score"], "tons": t["tons"],
            "pourquoi_ca_monte": t.get("pourquoi_ca_monte"), "angle_brut": t.get("angle_brut"),
            "prudence": t.get("prudence"), "couvert": t["couvert"], "couvert_par_brut": t["couvert_par_brut"],
            "serie": t["serie"], "video_declencheur": t["video_declencheur"], "imprevu": t.get("imprevu", False),
            "couverture_presse_depuis": t.get("couverture_presse_depuis"),
            "couverture_concurrents_depuis": t.get("couverture_concurrents_depuis"),
            "couverture_complete": t.get("couverture_complete", False),
            "format_brut": t.get("format_brut"),
            "declencheur_avant": (t.get("declencheur_effet") or {}).get("avant_48h"),
            "declencheur_apres": (t.get("declencheur_effet") or {}).get("apres_48h"),
            "part_hors_legende": (t.get("preuve") or {}).get("part_hors_legende"),
            "videos_lues": (t.get("preuve") or {}).get("videos_lues"),
            "canaux": (t.get("preuve") or {}).get("canaux"),
            "reactions": (t.get("preuve") or {}).get("reactions"),
            "citations": (t.get("preuve") or {}).get("citations"),
        })
        position_of = {}
        for n, p in enumerate(t.get("positions", [])):
            positions.append({"topic_id": t["id"], "ordre": n, "libelle": p["libelle"], "resume": p["resume"],
                              "nb_videos": p["nb_videos"], "vues": p["vues"], "partages": p["partages"]})
            position_of.update({v: p["libelle"] for v in p["videos"]})
        coverage += [{"topic_id": t["id"], **{k: c[k] for k in ("media", "groupe", "titre", "url", "date", "similarite")}}
                     for c in t["couverture"]]
        for vid in t["videos"]:
            v, n, m = items[vid], notes[vid], items[vid]["metrics"]
            videos.append({
                "id": v["id"], "topic_id": t["id"], "position": position_of.get(v["id"]), "account": v["account"],
                "platform": m.get("platform"), "published_at": v["published_at"], "url": v["url"], "contenu": v["text"],
                "sujet": n["sujet"], "ton": n["ton"], "affirmation": n["affirmation"],
                "canal": n.get("canal"), "legende_suffit": n.get("legende_suffit"), "citation": n.get("citation"),
                "reaction_public": n.get("reaction_public"), "miniature": m.get("thumbnail"),
                "views": m.get("views"), "likes": m.get("likes"), "shares": m.get("shares"),
                "comments": m.get("comments"), "followers": m.get("followers"),
                "est_declencheur": v["id"] == t["video_declencheur"], "est_phare": v["id"] in t["videos_phares"],
            })

    with _client() as http:
        # Instantané : on vide puis on remplit. Les tables filles partent en cascade.
        http.delete("/brief", params={"id": "not.is.null"}).raise_for_status()
        http.delete("/topics", params={"id": "not.is.null"}).raise_for_status()
        http.delete("/personnalites", params={"id": "not.is.null"}).raise_for_status()
        _insert(http, "topics", topic_rows)
        _insert(http, "topic_positions", positions)
        _insert(http, "topic_coverage", coverage)
        _insert(http, "videos", videos)
        _insert(http, "brief", [{"ordre": n, "topic_id": b["sujet"], "titre": b["titre"], "etat": b["etat"],
                                 "pourquoi": b["pourquoi"], "angle": b["angle"], "format": b.get("format"),
                                 "deja_traite_par": b["deja_traite_par"]} for n, b in enumerate(brief)])
        _insert(http, "personnalites", [{"rang": n + 1, **{k: p[k] for k in (
            "nom", "hors_liste", "videos_total", "videos_recentes", "acceleration", "createurs_recents", "score",
            "tons", "affirmations")}, "reactions": p.get("reactions"), "vues": p.get("vues"),
            "interactions": p.get("interactions")} for n, p in enumerate(persons)])
    return {"sujets": len(topic_rows), "positions": len(positions), "couverture": len(coverage),
            "vidéos": len(videos), "brief": len(brief) or "aucun (lancer showcase après analyze)",
            "fiches Opus": sum(1 for t in topics if t.get("titre")), "personnalités": len(persons)}
