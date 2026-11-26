import json
from copy import deepcopy

import pytest

from minisweagent.models.extra.tool_result_tail import ToolResultTailModel
from minisweagent.models.litellm_model import LitellmModel


@pytest.mark.parametrize(("window",), [(0,), (3,)])
def test_tool_results_move_to_appendix_with_stable_history(window):
    model = ToolResultTailModel(model_name="deepseek/deepseek-flash", tool_result_tail_rounds=window)
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    prepared = []
    for index in range(5):
        call_id = f"call_{index}"
        messages.extend([
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "reasoning",
                "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": call_id, "content": f"output {index}"},
        ])
        original = deepcopy(messages)
        current = model._prepare_messages_for_api(messages)
        assert messages == original
        assert current[:-1][:len(prepared)] == prepared
        assert current[2]["reasoning_content"] == "reasoning"
        assert [message["role"] for message in current] == ["system", "user"] + ["assistant", "tool"] * (index + 1) + ["user"]
        results = json.loads(current[-1]["content"].split("<tool_results>\n")[1].split("\n</tool_results>")[0])
        start = max(0, index + 1 - window) if window else 0
        assert results == [{"tool_call_id": f"call_{number}", "output": f"output {number}"} for number in range(start, index + 1)]
        assert all("appendix" in message["content"] for message in current if message["role"] == "tool")
        prepared = current[:-1]
    assert LitellmModel(model_name="deepseek/deepseek-flash")._prepare_messages_for_api(messages) == messages
