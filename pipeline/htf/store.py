"""Stockage local SQLite : contenus collectés, cache des appels LLM et des embeddings, dépenses."""
import json
import sqlite3
from contextlib import contextmanager

import numpy as np

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,            -- 'social' ou 'media'
    source TEXT NOT NULL,          -- 'oriane', 'fake', 'rss', 'youtube'
    account TEXT,                  -- créateur ou média
    account_group TEXT,            -- pour les médias : 'brut', 'concurrent', 'traditionnel', 'droite', 'gauche'
    published_at TEXT NOT NULL,    -- ISO 8601
    url TEXT,
    text TEXT NOT NULL,            -- ce qu'on donne au LLM
    metrics TEXT                   -- JSON : views, likes, shares, comments, followers
);
CREATE TABLE IF NOT EXISTS annotations (
    item_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    key TEXT PRIMARY KEY,
    vector BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS costs (
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT,
    model TEXT,
    purpose TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    usd REAL
);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=60)  # écritures concurrentes des threads
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_items(items: list[dict]) -> int:
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.executemany(
            """INSERT INTO items (id, kind, source, account, account_group, published_at, url, text, metrics)
               VALUES (:id, :kind, :source, :account, :account_group, :published_at, :url, :text, :metrics)
               ON CONFLICT(id) DO UPDATE SET metrics = excluded.metrics""",
            [{**{"account_group": None, "url": None}, **i, "metrics": json.dumps(i.get("metrics") or {})} for i in items],
        )
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] - before


def existing_ids(ids: list[str]) -> set[str]:
    with connect() as conn:
        marks = ",".join("?" * len(ids)) or "''"
        return {r["id"] for r in conn.execute(f"SELECT id FROM items WHERE id IN ({marks})", ids)}


def load_items(kind: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM items WHERE kind = ? ORDER BY published_at", (kind,)).fetchall()
    return [{**dict(r), "metrics": json.loads(r["metrics"] or "{}")} for r in rows]


def get_annotations(version: str) -> dict[str, dict]:
    with connect() as conn:
        rows = conn.execute("SELECT item_id, data FROM annotations WHERE version = ?", (version,)).fetchall()
    return {r["item_id"]: json.loads(r["data"]) for r in rows}


def save_annotations(version: str, annotations: dict[str, dict]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO annotations (item_id, version, data) VALUES (?, ?, ?)",
            [(k, version, json.dumps(v, ensure_ascii=False)) for k, v in annotations.items()],
        )


def get_embeddings(keys: list[str]) -> dict[str, np.ndarray]:
    found = {}
    with connect() as conn:
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT key, vector FROM embeddings WHERE key IN ({marks})", chunk):
                found[r["key"]] = np.frombuffer(r["vector"], dtype=np.float32)
    return found


def save_embeddings(vectors: dict[str, np.ndarray]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO embeddings (key, vector) VALUES (?, ?)",
            [(k, v.astype(np.float32).tobytes()) for k, v in vectors.items()],
        )


def cache_get(key: str):
    with connect() as conn:
        row = conn.execute("SELECT data FROM llm_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row["data"]) if row else None


def cache_set(key: str, data) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO llm_cache (key, data) VALUES (?, ?)", (key, json.dumps(data, ensure_ascii=False)))


def record_cost(run_id: str, model: str, purpose: str, usage, usd: float) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO costs (run_id, model, purpose, input_tokens, output_tokens, cache_read_tokens, usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, model, purpose, usage.input_tokens, usage.output_tokens, usage.cache_read_input_tokens or 0, usd),
        )


def spent(run_id: str | None = None) -> float:
    with connect() as conn:
        if run_id:
            row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM costs WHERE run_id = ?", (run_id,)).fetchone()
        else:
            row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM costs").fetchone()
    return float(row[0])


def cost_report() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT model, purpose, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens,
                      SUM(output_tokens) AS output_tokens, ROUND(SUM(usd), 4) AS usd
               FROM costs GROUP BY model, purpose ORDER BY usd DESC"""
        ).fetchall()
    return [dict(r) for r in rows]
