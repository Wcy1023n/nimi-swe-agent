"""Local command execution with RTK's command-specific output compression."""

import os
import subprocess
from typing import Any

from minisweagent.environments.local import LocalEnvironment


class RTKEnvironment(LocalEnvironment):
    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = action.get("command", "")
        if "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in command:
            return super().execute(action, cwd, timeout=timeout)
        rewrite = subprocess.run(
            ["rtk", "rewrite", command],
            cwd=cwd or self.config.cwd or None,
            env=os.environ | self.config.env,
            capture_output=True,
            text=True,
            timeout=timeout or self.config.timeout,
        )
        # Exit 3 is also a rewrite; RTK delegates command approval to the caller.
        if rewrite.returncode not in (0, 1, 3):
            rewrite.check_returncode()
        command = command if rewrite.returncode == 1 else rewrite.stdout.rstrip("\n")
        output = super().execute(action | {"command": command}, cwd, timeout=timeout)
        output.setdefault("extra", {})["rtk_command"] = command
        return output
