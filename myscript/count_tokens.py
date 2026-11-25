"""Aggregate token usage recorded in API responses."""

from dataclasses import dataclass


def api_prompt_tokens(response: object) -> int | None:
    if isinstance(response, dict):
        usage = response.get("usage") or {}
        prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
        if type(prompt) is int and prompt >= 0:
            return prompt
    return None


def api_cached_prompt_tokens(usage: dict, prompt: int) -> int | None:
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None:
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        cached = details.get("cached_tokens")
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
    input_covered: int = 0
    output_covered: int = 0

    @property
    def input(self) -> int:
        return self.uncached + self.cached + self.unknown_input

    @property
    def cache_rounds(self) -> int:
        return self.input_covered - self.unknown_rounds

    @property
    def cache_hit_rate(self) -> float | None:
        known = self.uncached + self.cached
        return self.cached / known if known else None


def count_token_breakdown(messages: list[dict]) -> TokenBreakdown:
    tokens = TokenBreakdown()
    for message in messages:
        response = message if message.get("object") == "response" else message.get("extra", {}).get("response")
        if not isinstance(response, dict):
            continue
        tokens.responses += 1
        usage = response.get("usage") or {}
        prompt = api_prompt_tokens(response)
        output = usage.get("completion_tokens", usage.get("output_tokens"))
        valid_output = type(output) is int and output >= 0
        if prompt is not None:
            tokens.input_covered += 1
            if (cached := api_cached_prompt_tokens(usage, prompt)) is None:
                tokens.unknown_input += prompt
                tokens.unknown_rounds += 1
            else:
                tokens.uncached += prompt - cached
                tokens.cached += cached
        if valid_output:
            tokens.output += output
            tokens.output_covered += 1
        tokens.covered += int(prompt is not None and valid_output)
    return tokens
