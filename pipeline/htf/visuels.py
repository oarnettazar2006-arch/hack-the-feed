"""Graphiques pour le deck et le README (PNG dans docs/visuels/). Gratuit : lit data/out et le cache.

Règles suivies : un seul axe par graphique (deux mesures → deux panneaux), couleurs par entité,
divergent bleu (favorable) ↔ gris ↔ rouge (critique), étiquettes directes, grille discrète.
"""
import json
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from . import config, store  # noqa: E402

OUT = config.ROOT / "docs" / "visuels"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, RED, NEUTRAL = "#2a78d6", "#eb6834", "#e34948", "#c9c8c2"
DIVERGING = LinearSegmentedColormap.from_list("solde", [RED, "#f0efec", BLUE])

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "text.color": INK,
    "axes.axisbelow": True, "axes.titlelocation": "left", "axes.titleweight": "bold", "axes.titlesize": 12,
})


def _weekly(history: list[dict]) -> tuple[list[date], list[int]]:
    weeks: dict[date, int] = {}
    for x in history:
        d = date.fromisoformat(x["jour"])
        monday = d - timedelta(days=d.weekday())
        weeks[monday] = weeks.get(monday, 0) + x["videos"]
    keys = sorted(weeks)
    return keys, [weeks[k] for k in keys]


def lead_chart(names: list[str], start: date = date(2026, 9, 1)) -> str | None:
    """Pour chaque personnalité : vidéos par semaine (haut) et sondages (bas), même axe du temps."""
    polls = store.cache_get("polls:rows") or []
    cols = [n for n in names if store.cache_get(f"polls:history:{n}")]
    if not cols:
        return None
    fig, axes = plt.subplots(2, len(cols), figsize=(6.2 * len(cols), 6.4), sharex="col",
                             gridspec_kw={"height_ratios": [1, 1], "hspace": 0.25, "wspace": 0.22}, squeeze=False)
    for j, name in enumerate(cols):
        weeks, counts = _weekly(store.cache_get(f"polls:history:{name}"))
        top, bottom = axes[0][j], axes[1][j]
        top.bar(weeks, counts, width=5.2, color=BLUE if j == 0 else ORANGE, align="edge")
        top.set_title(f"{name} : vidéos TikTok et Instagram qui le citent, par semaine")
        top.set_ylabel("vidéos")
        pts = sorted((date.fromisoformat(p["date"]), p["score"]) for p in polls
                     if p.get("nom") == name and date.fromisoformat(p["date"]) >= start)
        if pts:
            bottom.scatter([d for d, _ in pts], [s for _, s in pts], s=36, color=BLUE if j == 0 else ORANGE,
                           edgecolor=SURFACE, linewidth=1.5, zorder=3)
            # Moyenne glissante sur 14 jours, pour lire la tendance sans masquer les points.
            xs = sorted({d for d, _ in pts})
            avg = [sum(s for d2, s in pts if x - timedelta(days=14) < d2 <= x) /
                   max(1, sum(1 for d2, _ in pts if x - timedelta(days=14) < d2 <= x)) for x in xs]
            bottom.plot(xs, avg, color=INK2, linewidth=2)
            bottom.set_ylim(0, max(s for _, s in pts) * 1.35)
        bottom.set_title("Sondages (intentions de vote au 1er tour, %), un point par sondage")
        bottom.set_ylabel("%")
        bottom.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m"))
    fig.text(0.01, 0.005, "Sources : Oriane (vidéos FR, TikTok et Instagram) ; sondages recensés par Wikipédia. "
             "Ligne grise : moyenne des sondages sur 14 jours. Ce n'est pas un sondage : on compte des vidéos.",
             color=INK2, fontsize=9)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "avance-videos-sur-sondages.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return str(path.relative_to(config.ROOT))


def exposure_chart() -> str | None:
    """Part dans les sondages (x) contre part des vues (y), échelle log ; couleur = solde du traitement."""
    persons = json.loads((config.OUT_DIR / "people.json").read_text())
    pool = [p for p in persons if p.get("sondage") and p.get("vues")]
    if len(pool) < 3:
        return None
    poll_total = sum(p["sondage"] for p in pool)
    views_total = sum(p["vues"] for p in pool)
    xs = [100 * p["sondage"] / poll_total for p in pool]
    ys = [100 * p["vues"] / views_total for p in pool]
    fig, ax = plt.subplots(figsize=(9, 7))
    lo, hi = min(xs + ys) * 0.6, max(xs + ys) * 1.6
    ax.plot([lo, hi], [lo, hi], color=INK2, linewidth=1, linestyle="--")
    ax.text(hi * 0.55, hi * 0.75, "visibilité = poids\ndans les sondages", color=INK2, fontsize=9, ha="right")
    sc = ax.scatter(xs, ys, c=[p["solde"] for p in pool], cmap=DIVERGING, vmin=-1, vmax=1, s=90,
                    edgecolor=INK2, linewidth=0.6, zorder=3)
    for x, y, p in zip(xs, ys, pool):
        ax.annotate(p["nom"].split()[-1] if p["nom"] != "Marine Le Pen" else "Le Pen", (x, y),
                    xytext=(6, 4), textcoords="offset points", fontsize=9.5, color=INK)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("part dans les sondages (%, entre ces candidats)")
    ax.set_ylabel("part des vues des vidéos qui les citent (%)")
    ax.set_title("Au-dessus de la diagonale : on en parle plus qu'il ne pèse dans les sondages")
    cb = fig.colorbar(sc, ax=ax, shrink=0.6, pad=0.02)
    cb.set_label("comment les vidéos le présentent\n(−1 critique, +1 favorable)", color=INK2)
    cb.outline.set_visible(False)
    fig.text(0.01, 0.005, "Vidéos lues sur TikTok et Instagram (Oriane), 17 jours ; sondages des 21 derniers jours "
             "(Wikipédia). Ce n'est pas un sondage.", color=INK2, fontsize=9)
    path = OUT / "surexposition.png"
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return str(path.relative_to(config.ROOT))


def camps_chart() -> str | None:
    """Par camp : part des vues des vidéos et part dans les sondages, côte à côte."""
    from .politics import CAMP_ORDER
    persons = json.loads((config.OUT_DIR / "people.json").read_text())
    pool = [p for p in persons if p.get("sondage") and p.get("vues")]
    if len(pool) < 3:
        return None
    camps = [c for c in CAMP_ORDER if any(p["camp"] == c for p in pool)]
    views = {c: sum(p["vues"] for p in pool if p["camp"] == c) for c in camps}
    poll = {c: sum(p["sondage"] for p in pool if p["camp"] == c) for c in camps}
    tv, tp = sum(views.values()), sum(poll.values())
    fig, ax = plt.subplots(figsize=(9, 0.6 * len(camps) + 1.6))
    y = range(len(camps))
    ax.barh([i + 0.2 for i in y], [100 * views[c] / tv for c in camps], height=0.36, color=BLUE,
            label="part des vues des vidéos")
    ax.barh([i - 0.2 for i in y], [100 * poll[c] / tp for c in camps], height=0.36, color=ORANGE,
            label="part dans les sondages")
    ax.set_yticks(list(y), camps)
    ax.invert_yaxis()
    ax.set_xlabel("%")
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Par camp : visibilité dans les vidéos et poids dans les sondages")
    fig.text(0.01, 0.005, "Candidats présents dans les sondages récents. Camps classés par l'équipe, à vérifier.",
             color=INK2, fontsize=9)
    path = OUT / "camps.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return str(path.relative_to(config.ROOT))


def run() -> dict:
    return {"avance": lead_chart(["David Lisnard", "Bruno Retailleau"]),
            "surexposition": exposure_chart(), "camps": camps_chart()}
