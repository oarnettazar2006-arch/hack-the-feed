"""Contrôle humain : 30 vidéos annotées à la main, à l'aveugle, comparées à Haiku.

1. `controle-echantillon` : tire 30 vidéos politiques des sujets exportés (dont 8 que Haiku juge ironiques,
   pour tester l'ironie), écrit la grille vierge `docs/controle/grille-30-videos.csv` (sans les réponses
   de Haiku) et garde les réponses de Haiku dans `data/out/controle-haiku.json` (hors GitHub).
2. `controle-comparer <grille remplie.csv>` : accord ton x/30, accord « légende suffit » x/30, sujet
   (similarité des phrases, bge-m3), personnalités, et la liste des désaccords.
"""
import csv
import json
import random

from . import annotate, config, store

GRID = config.ROOT / "docs" / "controle" / "grille-30-videos.csv"
HAIKU = config.OUT_DIR / "controle-haiku.json"
FIELDS = ["n", "lien", "compte", "plateforme", "date", "paroles_et_texte_a_l_ecran", "legende",
          "VOTRE_sujet", "VOTRE_ton", "VOTRE_legende_suffit", "VOTRE_personnalites", "VOTRE_remarque"]


def sample(n: int = 30, ironic: int = 8, seed: int = 7) -> dict:
    topics = json.loads((config.OUT_DIR / "topics.json").read_text())
    notes = annotate.notes()
    items = {i["id"]: i for i in store.load_items("social")}
    pool = [vid for t in topics if t["politique"] for vid in t["videos"]
            if vid in notes and items.get(vid) and items[vid]["url"] and not items[vid]["metrics"].get("lien_compte")
            and ("Paroles" in items[vid]["text"] or "Texte à l'écran" in items[vid]["text"])]
    pool = list(dict.fromkeys(pool))
    rng = random.Random(seed)
    iro = [v for v in pool if notes[v]["ton"] == "ironique"]
    chosen = rng.sample(iro, min(ironic, len(iro)))
    rest = [v for v in pool if v not in chosen]
    chosen += rng.sample(rest, n - len(chosen))
    rng.shuffle(chosen)
    rows, answers = [], {}
    for k, vid in enumerate(chosen, 1):
        it, m, note = items[vid], items[vid]["metrics"], notes[vid]
        # Texte de la vidéo : « Paroles : … / Texte à l'écran : … / Légende : … / Commentaires populaires : … »
        text = it["text"].split("Commentaires populaires :", 1)[0]
        caption = ""
        if "Légende :" in text:
            text, caption = text.split("Légende :", 1)
        rows.append({"n": k, "lien": it["url"], "compte": it["account"], "plateforme": m.get("platform"),
                     "date": it["published_at"][:10], "paroles_et_texte_a_l_ecran": text.strip()[:1500],
                     "legende": caption.strip()[:400], "VOTRE_sujet": "", "VOTRE_ton": "",
                     "VOTRE_legende_suffit": "", "VOTRE_personnalites": "", "VOTRE_remarque": ""})
        answers[str(k)] = {"id": vid, "sujet": note["sujet"], "ton": note["ton"],
                           "legende_suffit": note.get("legende_suffit"),
                           "personnalites": annotate.names(note)}
    GRID.parent.mkdir(parents=True, exist_ok=True)
    with GRID.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
    HAIKU.write_text(json.dumps(answers, ensure_ascii=False, indent=1))
    return {"grille": str(GRID.relative_to(config.ROOT)), "vidéos": len(rows),
            "dont ironiques selon Haiku": sum(1 for a in answers.values() if a["ton"] == "ironique")}


def _yes(v: str) -> bool | None:
    v = (v or "").strip().lower()
    return True if v in ("oui", "o", "yes", "vrai", "1") else False if v in ("non", "n", "no", "faux", "0") else None


def compare(path: str) -> dict:
    import numpy as np
    from .analyze import _name_key
    from .embed import embed
    answers = json.loads(HAIKU.read_text())
    with open(path, encoding="utf-8-sig") as f:
        sample_ = f.read(4096)
        f.seek(0)
        rows = list(csv.DictReader(f, delimiter=";" if sample_.count(";") > sample_.count(",") else ","))
    tone_ok = cap_ok = cap_n = 0
    pairs, disagreements, people_ok, people_n = [], [], 0, 0
    by_tone: dict[str, list[int]] = {}
    for r in rows:
        h = answers.get(str(r["n"]).strip())
        human_tone = (r.get("VOTRE_ton") or "").strip().lower()
        if not h or not human_tone:
            continue
        same = human_tone == h["ton"]
        tone_ok += same
        by_tone.setdefault(h["ton"], [0, 0])
        by_tone[h["ton"]][0] += same
        by_tone[h["ton"]][1] += 1
        if not same:
            disagreements.append({"n": r["n"], "humain": human_tone, "haiku": h["ton"], "lien": r["lien"]})
        cap = _yes(r.get("VOTRE_legende_suffit"))
        if cap is not None and h["legende_suffit"] is not None:
            cap_n += 1
            cap_ok += cap == h["legende_suffit"]
        if r.get("VOTRE_sujet", "").strip():
            pairs.append((r["VOTRE_sujet"].strip(), h["sujet"]))
        human_people = {_name_key(x) for x in (r.get("VOTRE_personnalites") or "").replace(";", ",").split(",") if x.strip()}
        if human_people or h["personnalites"]:
            people_n += 1
            people_ok += human_people == {_name_key(x) for x in h["personnalites"]}
    n = sum(v[1] for v in by_tone.values())
    sims = []
    if pairs:
        a, b = embed([p[0] for p in pairs]), embed([p[1] for p in pairs])
        sims = [float(x) for x in (a * b).sum(axis=1)]
    out = {"vidéos comparées": n, "accord sur le ton": f"{tone_ok}/{n}",
           "accord par ton de Haiku": {k: f"{v[0]}/{v[1]}" for k, v in by_tone.items()},
           "accord « légende suffit »": f"{cap_ok}/{cap_n}",
           "même sujet (similarité ≥ 0,75)": f"{sum(s >= 0.75 for s in sims)}/{len(sims)}" if sims else None,
           "mêmes personnalités": f"{people_ok}/{people_n}", "désaccords sur le ton": disagreements}
    (config.OUT_DIR / "controle-resultat.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out
