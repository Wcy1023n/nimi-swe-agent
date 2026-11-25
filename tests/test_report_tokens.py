import pytest

from myscript.count_time import Task
from myscript.count_tokens import count_token_breakdown
from myscript.plot_timing import render_report


@pytest.mark.parametrize(
    ("message",),
    [
        ({"role": "assistant", "extra": {"response": {"usage": {"prompt_tokens": 120, "completion_tokens": 30, "prompt_cache_hit_tokens": 80}}}},),
        ({"object": "response", "usage": {"input_tokens": 120, "output_tokens": 30, "input_tokens_details": {"cached_tokens": 80}}},),
        ({"role": "user", "extra": {"interrupt_type": "FormatError", "response": {"usage": {"prompt_tokens": 120, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 80}}}}},),
    ],
)
def test_usage_survives_history_replacement(message):
    messages = [{"role": "tool", "content": "original output"}, message]
    assert count_token_breakdown(messages).input == 120
    messages[0]["content"] = "[tool result is clean,please redo]"
    tokens = count_token_breakdown(messages)
    assert (tokens.input, tokens.uncached, tokens.cached, tokens.output) == (120, 40, 80, 30)
    assert (tokens.responses, tokens.input_covered, tokens.output_covered, tokens.covered) == (1, 1, 1, 1)
    assert tokens.cache_hit_rate == 80 / 120


def test_partial_usage_is_counted_independently_and_reported():
    tokens = count_token_breakdown(
        [
            {"extra": {"response": {"usage": {"prompt_tokens": 120, "prompt_cache_hit_tokens": 20}}}},
            {"extra": {"response": {"usage": {"prompt_tokens": 90, "completion_tokens": 7, "prompt_cache_hit_tokens": 100}}}},
            {"object": "response", "usage": {"output_tokens": 13}},
            {"role": "assistant", "extra": {"response": {}}},
        ]
    )
    assert (tokens.input, tokens.output, tokens.cached, tokens.unknown_input) == (210, 20, 20, 90)
    assert (tokens.responses, tokens.input_covered, tokens.output_covered, tokens.covered) == (4, 2, 2, 1)
    assert tokens.cache_hit_rate == 20 / 120
    report = render_report([Task("partial", "test", [], api_calls=5, token_breakdown=tokens)])
    assert '累计输入 <strong>210</strong>' in report
    assert '累计输出 <strong>20</strong>' in report
    assert '输入记录覆盖 2 / 5' in report
    assert '缓存记录覆盖 1 / 5' in report
    assert '累计估算' not in report


def test_missing_usage_and_zero_usage_are_distinct():
    assert count_token_breakdown([{"role": "assistant", "content": "No usage"}]).input_covered == 0
    tokens = count_token_breakdown([{"extra": {"response": {"usage": {"prompt_tokens": 0, "completion_tokens": 0}}}}])
    assert (tokens.input, tokens.output, tokens.input_covered, tokens.output_covered) == (0, 0, 1, 1)
    assert tokens.cache_hit_rate is None
    assert '累计输入 <strong>0</strong>' in render_report([Task("zero", "test", [], token_breakdown=tokens)])
