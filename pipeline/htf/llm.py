"""Appels à Claude avec cache, comptage des coûts et plafond de dépense."""
import hashlib
import json
import time
from types import SimpleNamespace

import anthropic
import pydantic
from pydantic import BaseModel

from . import config, store


class BudgetExceeded(RuntimeError):
    pass


_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3)
    return _client


def cost_usd(model: str, usage) -> float:
    price_in, price_out, price_cache = config.PRICES[model]
    cache_read = usage.cache_read_input_tokens or 0
    cache_write = usage.cache_creation_input_tokens or 0
    return (
        usage.input_tokens * price_in
        + cache_write * price_in * 1.25
        + cache_read * price_cache
        + usage.output_tokens * price_out
    ) / 1_000_000


def _check_budget(run_id: str, model: str, max_tokens: int, prompt_chars: int) -> None:
    # Pire cas : toute la sortie utilisée, ~3,5 caractères par token en entrée.
    price_in, price_out, _ = config.PRICES[model]
    worst = (prompt_chars / 3.5 * price_in + max_tokens * price_out) / 1_000_000
    total, run = store.spent(), store.spent(run_id)
    if total + worst > config.BUDGET_TOTAL_USD:
        raise BudgetExceeded(f"Budget total atteint : {total:.2f} $ dépensés sur {config.BUDGET_TOTAL_USD} $.")
    if run + worst > config.BUDGET_RUN_USD:
        raise BudgetExceeded(f"Plafond de l'exécution atteint : {run:.2f} $ sur {config.BUDGET_RUN_USD} $.")


def structured(
    *,
    run_id: str,
    purpose: str,
    model: str,
    effort: str,
    system: str,
    prompt: str,
    schema: type[BaseModel],
    max_tokens: int,
    thinking: bool = True,
):
    """Un appel qui renvoie un objet pydantic validé. Le résultat est mis en cache sur le contenu exact de la requête."""
    key = hashlib.sha256(json.dumps([model, effort, thinking, system, prompt, schema.__name__]).encode()).hexdigest()
    cached = store.cache_get(key)
    if cached is not None:
        return schema.model_validate(cached)

    _check_budget(run_id, model, max_tokens, len(system) + len(prompt))
    for attempt in range(3):
        try:
            response = client().messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": effort},
                output_format=schema,
                **({} if thinking else {"thinking": {"type": "disabled"}}),
            )
            break
        except pydantic.ValidationError as e:
            # JSON coupé : la sortie a atteint max_tokens. L'usage réel est perdu, on compte le pire cas.
            worst = SimpleNamespace(input_tokens=int((len(system) + len(prompt)) / 3.5), output_tokens=max_tokens,
                                    cache_read_input_tokens=0, cache_creation_input_tokens=0)
            store.record_cost(run_id, model, purpose + " (échec)", worst, cost_usd(model, worst))
            raise RuntimeError(f"Réponse tronquée ou invalide ({purpose}) : augmenter max_tokens") from e
        except (anthropic.RateLimitError, anthropic.OverloadedError, anthropic.InternalServerError):
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))

    usd = cost_usd(model, response.usage)
    store.record_cost(run_id, model, purpose, response.usage, usd)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Refus du modèle ({purpose}), requête {response._request_id}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"Réponse tronquée ({purpose}) : augmenter max_tokens")
    result = response.parsed_output
    store.cache_set(key, result.model_dump())
    return result
