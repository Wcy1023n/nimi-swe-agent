"""Estimate cumulative Chat Completions input tokens from saved messages."""

import json
from collections import Counter
from dataclasses import dataclass

import tiktoken

ENCODING = "o200k_base"


@dataclass
class InputTokens:
    by_role: Counter[str]
    rounds: int
    api_prompt: int | None
    cached_prompt: int
    cache_prompt: int
    cache_rounds: int

    @property
    def total(self) -> int:
        return sum(self.by_role.values())

    @property
    def cache_hit_rate(self) -> float | None:
        return self.cached_prompt / self.cache_prompt if self.cache_prompt else None


def api_prompt_tokens(response: object) -> int | None:
    if isinstance(response, dict):
        prompt = (response.get("usage") or {}).get("prompt_tokens")
        if type(prompt) is int and prompt >= 0:
            return prompt
    return None


def api_cached_prompt_tokens(usage: dict, prompt: int) -> int | None:
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None:
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    return cached if type(cached) is int and 0 <= cached <= prompt else None


@dataclass
class TokenBreakdown:
    uncached: int = 0
    cached: int = 0
    output: int = 0
    covered: int = 0
    responses: int = 0
    unknown_input: int = 0
    unknown_rounds: int = 0


def count_token_breakdown(messages: list[dict]) -> TokenBreakdown:
    tokens = TokenBreakdown()
    for message in messages:
        response = message.get("extra", {}).get("response")
        if not isinstance(response, dict):
            continue
        tokens.responses += 1
        usage = response.get("usage") or {}
        prompt = api_prompt_tokens(response)
        output = usage.get("completion_tokens")
        if prompt is None or type(output) is not int or output < 0:
            continue
        if (cached := api_cached_prompt_tokens(usage, prompt)) is None:
            tokens.unknown_input += prompt
            tokens.unknown_rounds += 1
        else:
            tokens.uncached += prompt - cached
            tokens.cached += cached
        tokens.output += output
        tokens.covered += 1
    return tokens


def count_input_tokens(messages: list[dict]) -> InputTokens | None:
    encoding = tiktoken.get_encoding(ENCODING)
    history: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    rounds = 0
    api_prompt = 0
    usage_rounds = 0
    cached_prompt = cache_prompt = cache_rounds = 0
    for message in messages:
        response = message.get("extra", {}).get("response")
        if isinstance(response, dict) and response.get("choices"):
            totals.update(history)
            rounds += 1
            usage = response.get("usage") or {}
            if (prompt := api_prompt_tokens(response)) is not None:
                api_prompt += prompt
                usage_rounds += 1
                if (cached := api_cached_prompt_tokens(usage, prompt)) is not None:
                    cached_prompt += cached
                    cache_prompt += prompt
                    cache_rounds += 1
        role = message.get("role")
        if role in ("system", "user", "assistant", "tool"):
            payload = {key: value for key, value in message.items() if key != "extra" and value is not None}
            history[role] += len(encoding.encode_ordinary(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
    if rounds and totals:
        return InputTokens(
            totals,
            rounds,
            api_prompt if usage_rounds == rounds else None,
            cached_prompt=cached_prompt,
            cache_prompt=cache_prompt,
            cache_rounds=cache_rounds,
        )
    return None
