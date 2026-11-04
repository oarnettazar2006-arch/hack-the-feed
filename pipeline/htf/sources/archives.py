"""Historique de la presse sur 14 jours, à partir des sitemaps d'archives (gratuits, sans clé).

Les flux RSS ne gardent qu'un à deux jours : sans cet historique, un sujet traité il y a une semaine
passerait pour un angle mort. Chaque journal découpe ses archives à sa façon (par jour, par mois, par pages) ;
on garde les sous-sitemaps dont le nom ou la date de mise à jour tombe dans la période, puis les articles
publiés dans la période. Le titre vient de la balise news:title quand elle existe, sinon de l'adresse.
"""
import gzip
import hashlib
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from .. import store
from .media import UA

# (nom, groupe, index de sitemaps)
ARCHIVES = [
    ("Le Monde", "traditionnel", "https://www.lemonde.fr/sitemap_index.xml"),
    ("Le Figaro", "droite", "https://sitemaps.lefigaro.fr/lefigaro.fr/articles.xml"),
    ("franceinfo", "traditionnel", "https://www.franceinfo.fr/sitemap_index.xml"),
    ("Libération", "gauche", "https://www.liberation.fr/arc/outboundfeeds/sitemap.xml?outputType=xml"),
    ("20 Minutes", "traditionnel", "https://www.20minutes.fr/sitemap-index.xml"),
    ("BFMTV", "traditionnel", "https://www.bfmtv.com/sitemap_index_arbo_contenu.xml"),
    ("JDD", "droite", "https://www.lejdd.fr/sitemap.xml"),
    ("Mediapart", "gauche", "https://www.mediapart.fr/sitemap_index.xml"),
    # CNews : bloque les requêtes répétées (429) ; couvert par YouTube et, samedi, par ses comptes via Oriane.
    ("Le Parisien", "traditionnel", "https://www.leparisien.fr/arc/outboundfeeds/news-sitemap-index/?outputType=xml"),
]

# Rubriques sans enjeu d'actualité : inutile de les annoter.
SKIP = re.compile(r"/(sport|sports|football|rugby|tennis|horoscope|jeux|recettes?|cuisine|shopping|bons-plans|"
                  r"guide-achat|mode|beaute|voyages?|people|tele|series|programme-tv|meteo|loisirs|immobilier/annonces)/")
MAX_CHILDREN = 45  # Le Monde et Le Figaro : un sous-sitemap par jour
MAX_PER_SITE = 3000


def _get(url: str) -> str:
    r = httpx.get(html.unescape(url), headers=UA, timeout=60, follow_redirects=True)
    r.raise_for_status()
    data = r.content
    if data[:2] == b"\x1f\x8b":  # certains serveurs décompressent déjà les .gz
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace")


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        try:
            d = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _children(index_xml: str, since: datetime) -> list[str]:
    """Sous-sitemaps qui peuvent contenir la période.

    Les archives sont nommées d'après le début de leur période (jour, lundi de la semaine, 1er du mois) :
    on garde celles qui commencent au plus un mois avant la période. Sans date dans le nom, on se fie
    à la date de mise à jour. Les articles sont ensuite filtrés un par un sur leur date.
    """
    kids = re.findall(r"<sitemap>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", index_xml)
    earliest = (since - timedelta(days=31)).strftime("%Y-%m-%d")
    dated, by_mod = [], []
    for loc, mod in kids:
        found = [a or (b + "-01") for a, b in re.findall(r"(\d{4}-\d{2}-\d{2})|(\d{4}-\d{2})(?!-\d)", loc)]
        if found:
            if max(found) >= earliest:
                dated.append((max(found), loc))
            continue
        m = _parse_date(mod)
        if m is None or m >= since:
            by_mod.append(loc)
    # Les plus récents d'abord : la limite ne doit couper que le plus ancien.
    dated.sort(reverse=True)
    return ([loc for _, loc in dated] or by_mod)[:MAX_CHILDREN]


def _slug_title(url: str) -> str:
    slug = html.unescape(url).split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|php)$", "", slug)
    words = re.split(r"[-_]+", slug)
    # Identifiants techniques (hash, numéros, dates horodatées) : on coupe au premier.
    for i, w in enumerate(words):
        if re.fullmatch(r"[0-9a-f]{12,}|\d{5,}|[a-z]?\d{6,}", w):
            words = words[:i]
            break
    return " ".join(words).strip().capitalize()


def _articles(xml: str, since: datetime) -> list[tuple[str, str, datetime]]:
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", block)
        date = (re.search(r"<news:publication_date>([^<]+)<", block) or re.search(r"<lastmod>([^<]+)<", block))
        title = re.search(r"<news:title>(?:<!\[CDATA\[)?([^<\]]+)", block)
        when = _parse_date(date.group(1)) if date else None
        if not loc or not when or when < since or SKIP.search(loc.group(1)):
            continue
        url = html.unescape(loc.group(1).strip())
        out.append((url, html.unescape(title.group(1)).strip() if title else _slug_title(url), when))
    return out


def collect_site(name: str, group: str, index_url: str, since: datetime) -> list[dict]:
    index = _get(index_url)
    children = _children(index, since) if "<sitemapindex" in index else [index_url]
    found: dict[str, dict] = {}
    undated = "<sitemapindex" in index and children and not re.search(r"\d{4}-\d{2}", children[0])
    if undated:
        probe = _articles(_get(children[0]), since)
        if not probe:
            kids = re.findall(r"<sitemap>\s*<loc>([^<]+)</loc>", index)
            children = list(reversed(kids))[:MAX_CHILDREN]
    for child in children:
        xml = index if child == index_url else _get(child)
        if "<sitemapindex" in xml:  # un niveau de plus (index d'index)
            for sub in _children(xml, since)[:5]:
                for url, title, when in _articles(_get(sub), since):
                    found.setdefault(url, (title, when))
            continue
        for url, title, when in _articles(xml, since):
            found.setdefault(url, (title, when))
        if len(found) >= MAX_PER_SITE:
            break
    return [{
        "id": "media:" + hashlib.sha1(url.encode()).hexdigest()[:16], "kind": "media", "source": "archive",
        "account": name, "account_group": group, "published_at": when.isoformat(), "url": url,
        "text": title, "metrics": {},
    } for url, (title, when) in list(found.items())[:MAX_PER_SITE]]


def collect(days: int = 14) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    report, items = {}, []

    def one(entry):
        name, group, url = entry
        try:
            got = collect_site(name, group, url, since)
            dates = sorted(i["published_at"][:10] for i in got)
            return name, got, f"{len(got)} articles" + (f" ({dates[0]} → {dates[-1]})" if dates else "")
        except Exception as e:
            return name, [], f"erreur : {e.__class__.__name__} {str(e)[:80]}"

    with ThreadPoolExecutor(max_workers=5) as pool:
        for name, got, line in pool.map(one, ARCHIVES):
            items += got
            report[name] = line
    report["nouveaux"] = store.upsert_items(items)
    return report
