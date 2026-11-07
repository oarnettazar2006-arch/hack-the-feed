"""Sondages de la présidentielle 2027 comparés à la visibilité des candidats (vidéos et presse).

Source : page Wikipédia « Liste de sondages sur l'élection présidentielle française de 2027 », qui recense
les sondages publiés (institut, dates, échantillon). Pour chaque sondage on garde la première hypothèse
du tableau (la principale). Les scores sont ceux publiés par les instituts : on ne les modifie pas.

Indice de surexposition = part de visibilité du candidat ÷ sa part dans les sondages, calculées sur le même
ensemble de candidats. Au-dessus de 1, on parle plus de lui qu'il ne pèse dans les intentions de vote :
émergence possible ou bulle médiatique. Ce qui tranche, c'est l'ordre dans le temps (la visibilité monte-t-elle
avant le sondage ?), d'où les séries par jour.
"""
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from . import config, store

PAGE = "Liste_de_sondages_sur_l'élection_présidentielle_française_de_2027"
API = "https://fr.wikipedia.org/w/api.php"
SOURCE_URL = "https://fr.wikipedia.org/wiki/" + PAGE
MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
          "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).strip()


def fetch() -> str:
    r = httpx.get(API, params={"action": "parse", "page": PAGE, "prop": "text", "format": "json", "formatversion": 2},
                  headers={"User-Agent": "HackTheFeed/1.0 (https://github.com/oarnettazar2006-arch/hack-the-feed; student hackathon project) httpx"}, timeout=60)
    r.raise_for_status()
    return r.json()["parse"]["text"]


def _grid(table):
    """Tableau HTML → grille (texte, ligne d'origine, nb de colonnes couvertes), rowspan/colspan dépliés."""
    grid, pending = [], {}
    for r, tr in enumerate(table.find_all("tr")):
        row, col = [], 0
        cells = tr.find_all(["th", "td"], recursive=False)
        it = iter(cells)
        while True:
            if col in pending and pending[col][0] > 0:
                left, cell = pending[col]
                row.append(cell)
                pending[col] = (left - 1, cell)
                col += 1
                continue
            c = next(it, None)
            if c is None:
                break
            span, rspan = int(c.get("colspan", 1) or 1), int(c.get("rowspan", 1) or 1)
            for _ in range(span):
                cell = (c.get_text(" ", strip=True), r, span)
                row.append(cell)
                if rspan > 1:
                    pending[col] = (rspan - 1, cell)
                col += 1
        while col in pending and pending[col][0] > 0:
            left, cell = pending[col]
            row.append(cell)
            pending[col] = (left - 1, cell)
            col += 1
        grid.append(row)
    return grid


def _end_date(text: str, year: int) -> date | None:
    found = re.findall(r"(\d{1,2})(?:er)?\s+([a-zéû]+)", text.lower())
    months = [m for m in re.findall(r"[a-zéû]+", text.lower()) if m in MONTHS]
    if found and found[-1][1] in MONTHS:
        return date(year, MONTHS[found[-1][1]], int(found[-1][0]))
    days = re.findall(r"\d{1,2}", text)
    if days and months:
        return date(year, MONTHS[months[-1]], int(days[-1]))
    return None


def _score(text: str) -> tuple[float | None, str | None]:
    m = re.match(r"\s*(<\s*)?(\d+(?:[.,]\d+)?)\s*(.*)", text)
    if not m:
        return None, None
    value = float(m.group(2).replace(",", "."))
    return (0.5 if m.group(1) else value), (m.group(3).strip() or None)


def parse(html: str, since_year: int = 2026) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table", class_="wikitable"):
        heading = table.find_previous(["h2", "h3", "h4"])
        years = re.findall(r"20\d\d", heading.get_text() if heading else "")
        if not years or int(years[-1]) < since_year:
            continue
        year = int(years[-1])
        grid = _grid(table)
        if len(grid) < 4 or not grid[0] or not grid[0][0][0].startswith("Sondeur"):
            continue
        header_rows = 3
        # La ligne 2 de l'en-tête ne contient que les colonnes de candidats (Sondeur/Date/Échantillon sont en rowspan).
        cand_cols, others_col = {}, None
        for j, cell in enumerate(grid[1]):
            if j < 3:
                continue
            label = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", cell[0]).strip()
            if label == "Autres":
                others_col = j
            elif label:
                cand_cols[j] = re.sub(r"\s+", " ", label)
        seen = set()  # (sondage, candidat) déjà pris : l'hypothèse principale passe d'abord
        for r in range(header_rows, len(grid)):
            row = grid[r]
            if len(row) < 4 or max(c[2] for c in row) >= 8:
                continue  # ligne d'annonce sur toute la largeur
            first = row[0][1] == r  # première hypothèse du sondage
            pollster, when = re.sub(r"\[[^\]]*\]", "", row[0][0]).strip(), _end_date(row[1][0], year)
            if not pollster or not when:
                continue
            poll = (pollster, when.isoformat(), row[0][1])

            def add(name: str, value: float, others: bool = False) -> None:
                if (poll, name) in seen:
                    return
                seen.add((poll, name))
                out.append({"institut": pollster, "date": when.isoformat(), "candidat": name, "score": value,
                            "hypothese_principale": first, **({"autres": True} if others else {})})

            for j, label in cand_cols.items():
                if j >= len(row):
                    continue
                value, extra = _score(row[j][0])
                if value is None:
                    continue
                name = extra if label.lower().startswith("candidat") and extra else label
                if first:
                    add(name, value)
            # Colonne « Autres » : candidats testés sans colonne propre (« 3 Lisnard 2 Ruffin 1,5 Villepin »).
            # Un candidat absent de l'hypothèse principale est pris dans la première hypothèse qui le teste.
            if others_col is not None and others_col < len(row):
                for value, name in re.findall(r"(<?\s*\d+(?:,\d+)?)\s+([A-ZÉÈ][\w'-]+(?:\s+(?:de\s+)?[A-ZÉÈ][\w'-]+)?)",
                                              row[others_col][0]):
                    add(name, 0.5 if value.strip().startswith("<") else float(value.strip().replace(",", ".")), True)
    return out


def surname_map() -> dict[str, str]:
    """Nom de famille tel qu'écrit dans les sondages → nom complet de nos listes."""
    from .politics import AFFILIATIONS
    out = {}
    for full in AFFILIATIONS:
        parts = full.split()
        for k in range(1, len(parts)):
            out.setdefault(_norm(" ".join(parts[k:])), full)
    return out


def collect() -> dict:
    html = fetch()
    polls = parse(html)
    names = surname_map()
    for p in polls:
        p["nom"] = names.get(_norm(p["candidat"]))
    # On fusionne avec les relevés précédents : un sondage retiré de Wikipédia reste dans notre historique.
    previous = {(p["institut"], p["date"], p["candidat"]): p for p in store.cache_get("polls:rows") or []}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for p in polls:
        p["premier_releve"] = previous.get((p["institut"], p["date"], p["candidat"]), {}).get("premier_releve", now)
        previous[(p["institut"], p["date"], p["candidat"])] = p
    merged = sorted(previous.values(), key=lambda p: (p["date"], p["institut"], p["candidat"]))
    store.cache_set("polls:rows", merged)
    (config.OUT_DIR / "polls.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    snap = config.DATA_DIR / "polls"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / f"releve-{now[:16].replace(':', 'h')}.json").write_text(json.dumps(polls, ensure_ascii=False))
    new_polls = {(p["institut"], p["date"]) for p in polls if p["premier_releve"] == now}
    known = sorted({p["nom"] for p in polls if p["nom"]})
    return {"relevé": now, "nouveaux sondages depuis le dernier relevé": len(new_polls),
            "sondages": len({(p["institut"], p["date"]) for p in polls}), "scores": len(polls),
            "période": f"{min(p['date'] for p in polls)} → {max(p['date'] for p in polls)}" if polls else None,
            "candidats reconnus": known,
            "non reconnus": sorted({p["candidat"] for p in polls if not p["nom"]})[:15]}


def export() -> dict:
    """Envoie l'historique des sondages et le relevé dans Supabase (upsert : rien n'est effacé)."""
    from . import export as ex
    rows = store.cache_get("polls:rows") or []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = [{k: p.get(k) for k in ("institut", "date", "candidat", "nom", "score", "premier_releve")}
               | {"hypothese_principale": bool(p.get("hypothese_principale")), "autres": bool(p.get("autres")),
                  "dernier_releve": now} for p in rows]
    with ex._client() as http:
        for i in range(0, len(payload), 500):
            r = http.post("/sondages", params={"on_conflict": "institut,date,candidat"},
                          headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                          content=json.dumps(payload[i:i + 500], ensure_ascii=False))
            if r.status_code >= 400:
                raise RuntimeError(f"Supabase {r.status_code} sur sondages : {r.text[:300]}")
        r = http.post("/sondages_releves", content=json.dumps([{
            "releve_le": now, "sondages": len({(p["institut"], p["date"]) for p in rows}),
            "dernier_sondage": max((p["date"] for p in rows), default=None), "source": SOURCE_URL}]))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code} sur sondages_releves : {r.text[:300]}")
    return {"scores envoyés": len(payload)}


def latest(polls: list[dict], ref: date, window_days: int = 21) -> dict[str, dict]:
    """Moyenne des sondages publiés dans les `window_days` jours avant `ref`, par candidat."""
    start = (ref - timedelta(days=window_days)).isoformat()
    out = {}
    for p in polls:
        if p["nom"] and start <= p["date"] <= ref.isoformat():
            out.setdefault(p["nom"], []).append(p)
    return {n: {"moyenne": round(sum(x["score"] for x in rows) / len(rows), 1), "sondages": len(rows),
                "dernier": max(rows, key=lambda x: x["date"])} for n, rows in out.items()}


def series(polls: list[dict], name: str) -> list[dict]:
    return sorted(({"date": p["date"], "institut": p["institut"], "score": p["score"]}
                   for p in polls if p["nom"] == name), key=lambda x: x["date"])


def press_mentions(start: str, end: str) -> dict[str, int]:
    """Articles et vidéos de médias (titres) citant chaque personnalité classée, entre deux dates."""
    from .politics import AFFILIATIONS
    keys = {full: _norm(full.split()[-1] if len(full.split()) == 2 else " ".join(full.split()[1:]))
            for full in AFFILIATIONS}
    counts = dict.fromkeys(AFFILIATIONS, 0)
    for m in store.load_items("media"):
        if not (start <= m["published_at"][:10] <= end):
            continue
        text = f" {_norm(m['text'])} "
        for full, key in keys.items():
            if f" {key} " in text:
                counts[full] += 1
    return counts


def overexposure(persons: list[dict], ref: date) -> list[dict]:
    """Ajoute à chaque personnalité son score moyen dans les sondages et ses indices de surexposition."""
    polls = store.cache_get("polls:rows") or []
    if not polls:
        return persons
    avg = latest(polls, ref)
    start = (ref - timedelta(days=config.WINDOW_RECENT + config.WINDOW_BASELINE)).isoformat()
    press = press_mentions(start, ref.isoformat())
    pool = [p for p in persons if p["nom"] in avg]
    poll_total = sum(avg[p["nom"]]["moyenne"] for p in pool) or 1
    social_total = sum(p["vues"] for p in pool) or 1
    press_total = sum(press.get(p["nom"], 0) for p in pool) or 1
    for p in persons:
        a = avg.get(p["nom"])
        p["sondage"] = a["moyenne"] if a else None
        p["sondage_detail"] = f"moyenne de {a['sondages']} sondage(s), dernier {a['dernier']['institut']} " \
                              f"du {a['dernier']['date']}" if a else None
        p["mentions_presse"] = press.get(p["nom"])
        if a and a["moyenne"] > 0:
            share = a["moyenne"] / poll_total
            p["surexposition_videos"] = round(p["vues"] / social_total / share, 2)
            p["surexposition_presse"] = round(press.get(p["nom"], 0) / press_total / share, 2)
        else:
            p["surexposition_videos"] = p["surexposition_presse"] = None
        p["sondages_serie"] = series(polls, p["nom"])
        own = [x for x in polls if x["nom"] == p["nom"]]
        # Entrée dans les sondages : premier test, et premier test avec une colonne à son nom (hors « Autres »).
        p["teste_depuis"] = min((x["date"] for x in own), default=None)
        p["colonne_propre_depuis"] = min((x["date"] for x in own if not x.get("autres")), default=None)
    # Personnalités absentes des sondages récents : on dit seulement à qui elles ressemblent en visibilité
    # (jamais un « score estimé »). Ex. : « aussi visible que Lisnard, sondé à 6,2 % ».
    polled = [p for p in persons if p.get("sondage") and p.get("vues")]
    for p in persons:
        if p.get("sondage") is None and p.get("camp") not in (None, "international") and p.get("vues") and polled:
            near = min(polled, key=lambda q: abs(q["vues"] - p["vues"]))
            p["visibilite_comparable"] = f"aussi visible dans les vidéos que {near['nom']} (sondé à {near['sondage']} %)"
        else:
            p["visibilite_comparable"] = None
    return persons


def oriane_history(name: str, terms: list[str], start: date, end: date) -> list[dict]:
    """Nombre de vidéos FR par jour citant la personnalité (projection basic : 10 crédits par jour)."""
    from .sources import oriane
    api = oriane.Oriane()
    base = {"platform": {"includes": ["tiktok", "instagram"]}, "format": {"includes": ["video"]}}
    out, d = [], start
    while d <= end:
        day = d.isoformat()
        _, total = api.search({**base, "publishedAt": {"after": day, "before": day}},
                              [oriane.FRENCH, oriane.theme_query(name, terms)], limit=1, projection="basic")
        out.append({"jour": day, "videos": total})
        d += timedelta(days=1)
    store.cache_set(f"polls:history:{name}", out)
    return out
