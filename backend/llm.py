"""OpenRouter client: chat() sends one request; the budget guard covers the whole run.

- Usage accounting is on ("usage": {"include": true}), so every reply carries its
  token counts and its real cost in USD. No cost is estimated by hand.
- Rate limits and server errors are retried with exponential backoff.
- Once the run has spent config.BUDGET_USD, no new request is sent.
- The API key comes from .env and is never printed.
"""
import os
import random
import threading
import time

import requests

import config

RETRY_STATUS = {408, 429, 500, 502, 503, 504}  # worth another try


class LLMError(Exception):
    """A request failed in a way retrying won't fix (wrong key, no credits, unknown model, ...)."""


class BudgetExceeded(Exception):
    """The run has used up its budget, so no new requests are sent."""


class Budget:
    """Adds up the real cost of all replies. Thread-safe, for the parallel mode."""

    def __init__(self, limit_usd):
        self.limit_usd = limit_usd
        self.spent_usd = 0.0
        self._lock = threading.Lock()

    def check(self):
        with self._lock:
            if self.spent_usd >= self.limit_usd:
                raise BudgetExceeded(f"budget of ${self.limit_usd:.2f} used up (spent ${self.spent_usd:.4f})")

    def add(self, cost_usd):
        with self._lock:
            self.spent_usd += cost_usd


budget = Budget(config.BUDGET_USD)


def has_api_key():
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def model_prices(model_ids):
    """Check that the models exist on OpenRouter and get their list prices (free, no key needed)."""
    response = requests.get(f"{config.OPENROUTER_URL}/models", timeout=30)
    response.raise_for_status()
    available = {model["id"]: model for model in response.json()["data"]}
    prices = {}
    for model_id in model_ids:
        if model_id not in available:
            raise LLMError(f"model '{model_id}' is not available on OpenRouter - check config.py")
        pricing = available[model_id]["pricing"]
        prices[model_id] = {
            "input_per_million": round(float(pricing["prompt"]) * 1_000_000, 6),
            "output_per_million": round(float(pricing["completion"]) * 1_000_000, 6),
        }
    return prices


def key_limit_remaining():
    """USD left on the API key's own spending limit (None = no limit). Also checks that the key works."""
    response = requests.get(f"{config.OPENROUTER_URL}/key", headers=_headers(), timeout=30)
    if response.status_code in (401, 403):
        raise LLMError(f"OpenRouter rejected the API key (HTTP {response.status_code}) - check .env")
    response.raise_for_status()
    return response.json()["data"].get("limit_remaining")


def chat(model, messages):
    """Send one chat request. Returns the reply text, token counts and real cost."""
    body = {
        "model": model["id"],
        "messages": messages,
        "max_tokens": config.MAX_TOKENS,
        "reasoning": {**model["reasoning"], "exclude": True},  # we need the answer, not the thinking text
        "usage": {"include": True},  # token counts and real cost in every reply
    }
    for attempt in range(config.HTTP_RETRIES + 1):
        budget.check()
        retry_after = None
        try:
            response = requests.post(f"{config.OPENROUTER_URL}/chat/completions",
                                     json=body, headers=_headers(), timeout=config.REQUEST_TIMEOUT_S)
            if response.status_code == 200:
                data = response.json()
                if data.get("choices"):
                    return _reply(data, http_retries=attempt)
                problem = f"reply without choices: {str(data.get('error'))[:200]}"
            elif response.status_code in RETRY_STATUS:
                problem = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")
            else:
                raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
        except (requests.RequestException, ValueError) as error:  # timeout, dropped connection, broken JSON
            problem = type(error).__name__
        if attempt < config.HTTP_RETRIES:
            wait = _backoff_seconds(attempt, retry_after)
            print(f"    {model['id']}: {problem}, retrying in {wait:.0f} s")
            time.sleep(wait)
    raise LLMError(f"{model['id']}: giving up after {config.HTTP_RETRIES + 1} attempts ({problem})")


def _headers():
    return {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '').strip()}",
        "X-Title": "reading-ai-benchmark",  # shows up in your OpenRouter activity log
    }


def _backoff_seconds(attempt, retry_after):
    """2, 4, 8, 16 ... seconds plus a little jitter, or what the server asked for."""
    try:
        return min(float(retry_after), 60.0)
    except (TypeError, ValueError):
        return 2 ** (attempt + 1) + random.uniform(0, 1)


def _reply(data, http_retries):
    usage = data.get("usage") or {}
    if usage.get("cost") is None:
        # Without the real cost the budget guard can't work, so better stop here.
        raise LLMError("OpenRouter sent no cost in 'usage' - stopping to keep the budget safe")
    budget.add(usage["cost"])
    choice = data["choices"][0]
    return {
        "text": (choice.get("message") or {}).get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
        "cost_usd": usage["cost"],
        "provider": data.get("provider"),
        "http_retries": http_retries,
    }
