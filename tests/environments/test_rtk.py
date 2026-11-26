import pytest

from minisweagent.environments import get_environment
from minisweagent.exceptions import Submitted


def test_rtk_submission_preserves_raw_patch(tmp_path):
    patch = "\ndiff --git a/example.py b/example.py\n--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n"
    (tmp_path / "submitted patch.txt").write_text(patch)
    env = get_environment(
        {"environment_class": "minisweagent.environments.rtk.RTKEnvironment", "cwd": str(tmp_path)}
    )
    with pytest.raises(Submitted) as exc:
        env.execute({"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat 'submitted patch.txt'"})
    assert exc.value.messages[0]["content"] == patch
    assert exc.value.messages[0]["extra"]["exit_status"] == "Submitted"
