"""Embeddings locaux (bge-m3 via Ollama), mis en cache dans SQLite. Gratuits."""
import hashlib

import httpx
import numpy as np

from . import config, store


def _key(text: str) -> str:
    return config.EMBED_MODEL + ":" + hashlib.sha256(text.encode()).hexdigest()


def embed(texts: list[str], batch: int = 32) -> np.ndarray:
    """Renvoie une matrice (len(texts), dim) de vecteurs normalisés."""
    keys = [_key(t) for t in texts]
    known = store.get_embeddings(list(set(keys)))
    missing = list({k: t for k, t in zip(keys, texts) if k not in known}.items())
    for i in range(0, len(missing), batch):
        chunk = missing[i:i + batch]
        r = httpx.post(
            f"{config.OLLAMA_URL}/api/embed",
            json={"model": config.EMBED_MODEL, "input": [t for _, t in chunk]},
            timeout=300,
        )
        r.raise_for_status()
        fresh = {k: np.asarray(v, dtype=np.float32) for (k, _), v in zip(chunk, r.json()["embeddings"])}
        store.save_embeddings(fresh)
        known.update(fresh)
    matrix = np.stack([known[k] for k in keys]) if keys else np.zeros((0, 1024), dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)
