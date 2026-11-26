"""Run a locally built mini-SWE-agent wheel with Harbor's mini adapter."""

from pathlib import Path
from shlex import quote

from harbor.agents.installed.mini_swe_agent import MiniSweAgent, MiniSweAgentOptions
from harbor.environments.base import BaseEnvironment


class LocalMiniOptions(MiniSweAgentOptions):
    local_wheel: str
    rtk_binary: str | None = None


class LocalMini(MiniSweAgent):
    options_model = LocalMiniOptions
    options: LocalMiniOptions

    @staticmethod
    def _is_litellm_config(config: dict | None) -> bool:
        return MiniSweAgent._is_litellm_config(config) or (
            ((config or {}).get("model") or {}).get("model_class")
            == "minisweagent.models.extra.tool_result_tail.ToolResultTailModel"
        )

    async def install(self, environment: BaseEnvironment) -> None:
        wheel = Path(self.options.local_wheel).expanduser().resolve()
        if not (wheel.name.startswith("mini_swe_agent-") and wheel.suffix == ".whl" and wheel.is_file()):
            raise ValueError(f"Expected a local mini-SWE-agent wheel: {wheel}")

        if self.options.rtk_binary:
            await environment.upload_file(Path(self.options.rtk_binary).expanduser().resolve(), "/installed-agent/rtk")
            await self.exec_as_root(
                environment,
                command=(
                    "install -m 755 /installed-agent/rtk /usr/local/bin/rtk && rtk --version && "
                    "if [ -f /etc/apt/sources.list.d/debian.sources ]; then "
                    "sed -i 's|http://deb.debian.org|https://deb.debian.org|g' "
                    "/etc/apt/sources.list.d/debian.sources; fi"
                ),
            )
        await self.ensure_system_dependencies(environment, ("curl", "bash", "build_tools", "git"))
        target = f"/installed-agent/{wheel.name}"
        await environment.upload_file(wheel, target)
        await self.exec_as_root(environment, command=f"chmod a+r {quote(target)}")
        await self.exec_as_agent(
            environment,
            command=(
                'set -euo pipefail; export PATH="$HOME/.local/bin:$PATH"; '
                'if ! command -v uv >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi; '
                'uv python install 3.12 && '
                f'uv tool install --force --python 3.12 {quote(target)} '
                "--with 'litellm[mcp]' --with orjson --with fastapi && mini-swe-agent --help"
            ),
        )
