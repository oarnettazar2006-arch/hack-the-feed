"""Couverture médias : flux RSS de presse et flux RSS des chaînes YouTube (gratuits, sans clé)."""
import hashlib
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from .. import store

# group : 'brut' (référence), 'concurrent' (né sur les réseaux), 'traditionnel', 'droite', 'gauche'.
PRESS_FEEDS = [
    ("Le Monde", "traditionnel", "https://www.lemonde.fr/rss/une.xml"),
    ("franceinfo", "traditionnel", "https://www.francetvinfo.fr/titres.rss"),
    ("Le Figaro", "droite", "https://www.lefigaro.fr/rss/figaro_actualites.xml"),
    ("Libération", "gauche", "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml"),
    ("20 Minutes", "traditionnel", "https://www.20minutes.fr/feeds/rss-une.xml"),
    ("BFMTV", "traditionnel", "https://www.bfmtv.com/rss/news-24-7/"),
    ("Mediapart", "gauche", "https://www.mediapart.fr/articles/feed"),
    ("JDD", "droite", "https://www.lejdd.fr/rss.xml"),
]

# Identifiants vérifiés le 3/11/2026 (titre du flux contrôlé).
YOUTUBE_CHANNELS = [
    ("Brut", "brut", "UCYti3yTb2QWvLQExSmxnE2A"),
    ("HugoDécrypte", "concurrent", "UCAcAnMF0OrCtUep3Y4M-ZPw"),
    ("Konbini", "concurrent", "UCHQda5vLxrH0Ff0I0kMq4zw"),
    ("Loopsider", "concurrent", "UC6bn_ABjeTwbJFGFMQbZFlw"),
    ("Blast", "concurrent", "UC__xRB5L4toU9yYawt_lIKg"),
    ("Le Crayon", "concurrent", "UCbXWhsd805LfcbAy7xL9d-A"),
    ("Le Monde", "traditionnel", "UCYpRDnhk5H8h16jpS84uqsA"),
    ("franceinfo", "traditionnel", "UCO6K_kkdP-lnSCiO3tPx7WA"),
    ("CNews", "droite", "UCXKJrYczY2_fJEZgFPGY0HQ"),
    ("Frontières", "droite", "UCDfP-0yRKYOEqleFIQHiIKw"),
    ("Le Média", "gauche", "UCT67YOMntJxfRnO_9bXDpvw"),
]

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9"}


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def _items_from_feed(name: str, group: str, source: str, url: str, since: datetime) -> list[dict]:
    feed = feedparser.parse(httpx.get(url, headers=UA, timeout=30, follow_redirects=True).content)
    items = []
    for e in feed.entries:
        when = _published(e)
        if not when or when < since:
            continue
        title = _clean(e.get("title"))
        summary = _clean(e.get("summary") or e.get("media_description") or "")[:600]
        link = e.get("link")
        items.append({
            "id": "media:" + hashlib.sha1((link or title).encode()).hexdigest()[:16],
            "kind": "media",
            "source": source,
            "account": name,
            "account_group": group,
            "published_at": when.isoformat(),
            "url": link,
            "text": f"{title}. {summary}".strip(),
            "metrics": {},
        })
    return items


def collect(days: int = 14) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    report, items = {}, []
    for name, group, url in PRESS_FEEDS:
        try:
            got = _items_from_feed(name, group, "rss", url, since)
            items += got
            report[f"RSS {name}"] = len(got)
        except Exception as e:  # un flux cassé ne doit pas bloquer les autres
            report[f"RSS {name}"] = f"erreur : {e.__class__.__name__}"
    for name, group, cid in YOUTUBE_CHANNELS:
        try:
            got = _items_from_feed(name, group, "youtube", f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", since)
            items += got
            report[f"YouTube {name}"] = len(got)
        except Exception as e:
            report[f"YouTube {name}"] = f"erreur : {e.__class__.__name__}"
    report["nouveaux"] = store.upsert_items(items)
    return report
