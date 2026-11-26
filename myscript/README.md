# 实验监测与可视化

在仓库根目录运行以下命令。入口是 `myscript/plot_timing.py`，生成可离线打开的 HTML 报告。

下载的数据集、RTK 二进制和 wheel 位于 `myscript/assets/`，实验日志、轨迹和报告位于 `myscript/results/`。RTK 配置位于 `myscript/rtk.yaml`。

## 文件用途

| 文件 | 用途 |
| --- | --- |
| `plot_timing.py` | 命令行入口，生成多题耗时、Token、缓存命中率和费用报告 |
| `count_time.py` | 读取日志和轨迹，匹配题目、计时区间及调用费用，供入口脚本使用 |
| `count_tokens.py` | 汇总 API 记录的输入、输出和缓存 Token，供入口脚本使用 |

## 读取哪些文件

向入口脚本传入实验结果目录。脚本递归查找其中的 `minisweagent.log`，读取每个日志旁边及下一层题目目录里的 `*.traj.json`。

```text
myscript/results/example/
├── minisweagent.log
├── preds.json
├── results.json                  # 可选，正式评测汇总
├── astropy__astropy-12907/
│   └── astropy__astropy-12907.traj.json
└── ...
```

- `minisweagent.log` 提供 `run`、`query`、`execute_actions` 等计时记录。
- `*.traj.json` 提供题目、模型、退出状态、API 用量、缓存命中量和 LiteLLM 记录的费用。
- `results.json` 可提供正式评测结果，需要包含 `resolved_ids` 和 `unresolved_ids` 两个题目 ID 列表。也支持 `empty_patch_ids`、`error_ids`。
- `preds.json` 是 runner 输出的补丁文件，供后续正式评测使用。

单个日志内的实验应使用 `--workers 1`。报告可以汇总多个独立实验日志。

## 生成报告

使用默认输出位置。

```bash
.venv/bin/python myscript/plot_timing.py myscript/results/example
```

输出为 `myscript/results/plot_timing/YYYYMMDD-HHMMSS-微秒.html`，终端会打印完整路径。

指定输出文件并在 macOS 打开。

```bash
.venv/bin/python myscript/plot_timing.py myscript/results/example \
  --output myscript/results/example/timing-report.html \
&& open myscript/results/example/timing-report.html
```

输出路径的父目录会自动创建。重新生成时需使用新文件名，已有输出文件会触发报错。

指定正式评测结果文件。

```bash
.venv/bin/python myscript/plot_timing.py myscript/results/example \
  --evaluation /path/to/evaluation-summary.json \
  --output myscript/results/example/timing-report-evaluated.html
```

`--evaluation` 适用于输入目录中只有一个日志的情况。汇总多个实验时，把各自的 `results.json` 放在对应的日志旁。

## 完整示例

先启动 Docker，并在当前终端配置 `DEEPSEEK_API_KEY`。下面运行 SWE-bench Lite 测试集前 10 题，串行执行，然后生成并打开报告。

```bash
out="myscript/results/deepseek-lite-10-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python -m minisweagent.run.benchmarks.swebench \
  --subset lite \
  --split test \
  --slice '0:10' \
  --workers 1 \
  --model deepseek/deepseek-flash \
  --output "$out" \
  -c swebench.yaml \
  -c agent.step_limit=30 \
  -c agent.cost_limit=3 \
  -c model.cost_tracking=default \
  -c model.model_kwargs.api_base=https://api.deepseek.com \
  -c 'environment.run_args=["--rm","--platform=linux/amd64"]' \
  -c environment.pull_timeout=600 \
&& .venv/bin/python myscript/plot_timing.py "$out" \
  --output "$out/timing-report.html" \
&& open "$out/timing-report.html"
```

运行结果保存在 `$out`，HTML 报告为 `$out/timing-report.html`。其中 `agent.cost_limit=3` 表示每道题的 LiteLLM 费用预算为 3 美元。

## 结果含义

- 总耗时取自 Agent 的 `run`，镜像拉取和容器启动发生在这个区间之前。
- Query 明细提供每次调用的耗时、API 输入 Token 和轨迹费用。执行阶段使用 `execute_actions` 时包含该轮全部工具执行及结果处理。
- 费用总额以轨迹中的 LiteLLM 运行记录为准。DeepSeek Flash 的费用构成使用 API Token 用量及 LiteLLM 当前价表重建，并在报告中单独标注。`model_prices.yaml` 已退出计价流程。
- 运行时计价失败可能让旧轨迹的费用记录为零。事后重建金额可能因价表或峰谷时段变化而与原始费用不同。
- Token 总量取自 API 返回的 `usage`，报告会标注缺失记录。服务端不提供按消息角色拆分的用量；缓存命中率仅基于上报了有效缓存数据的调用。
- `Submitted` 表示 Agent 提交了补丁。正式通过情况取自评测汇总文件。

## k 窗口实验分支

`codex/k-window` 分支支持在上述 runner 命令中增加 `--k 3` 或 `--k 5`。`--k 0` 或省略参数表示全量保留，正整数表示保留最近对应轮数的工具结果。

每个实验使用单独的输出目录。将多个实验放在共同父目录下，再把父目录传给 `plot_timing.py`，可以在一个报告里浏览各组运行记录。

## Harbor 命令行

以下命令按本机 Harbor 0.27.0 编写，使用本地修改版 mini、DeepSeek Flash，每题上限 80 步，先跑 3 题，并发为 1。先启动 Docker，并确认 mini 的全局 `.env` 中配置了 `DEEPSEEK_API_KEY`。

### 公共参数

在仓库根目录执行一次，后面的命令在同一个 Bash 或 Zsh 终端中运行。

```bash
cd /Users/wcy/workspace/mini-swe-agent

export PYTHONPATH="$PWD"
export DOCKER_DEFAULT_PLATFORM=linux/amd64
export LITELLM_LOCAL_MODEL_COST_MAP=True

mini_args=(
  --agent myscript.harbor_mini:LocalMini
  --model deepseek/deepseek-flash
  --ak "local_wheel=$PWD/myscript/assets/wheels/rtk/mini_swe_agent-2.4.6-py3-none-any.whl"
  --ak 'config={"agent":{"step_limit":80}}'
  --ak cost_limit=3
  --env-file "$HOME/Library/Application Support/mini-swe-agent/.env"
  --n-concurrent 1
  --n-tasks 3
  --jobs-dir "$PWD/myscript/results/harbor"
)
```

这个 wheel 包含 RTK Environment，公共参数默认使用普通 LocalEnvironment。修改 `src/` 后，可以先重新打包当前代码。

```bash
uv build --wheel --out-dir myscript/assets/wheels/rtk
```

### SWE-bench

下面使用 Harbor 已注册的 SWE-bench Verified 数据集。

```bash
.venv-harbor/bin/harbor run "${mini_args[@]}" \
  --dataset swe-bench/swe-bench-verified \
  --job-name "swe-verified-$(date +%Y%m%d-%H%M%S)"
```

### SWE-bench Pro V2

使用已经下载到本地的官方 Pro V2 任务。任务自带 verifier，模型访问通过 `--allow-agent-host` 放行。

```bash
.venv-harbor/bin/harbor run "${mini_args[@]}" \
  --path myscript/assets/SWE-bench_Pro-os/v2/tasks \
  --allow-agent-host api.deepseek.com \
  --job-name "swe-pro-v2-$(date +%Y%m%d-%H%M%S)"
```

Harbor 目录中的 `scale-ai/swe-bench-pro` 当前对应 731 题版本，上面的本地路径对应官方 V2。版本和评测流程见 [Pro V2 官方说明](https://github.com/scaleapi/SWE-bench_Pro-os/blob/main/v2/README.md)。

### Terminal-Bench 1.x

旧版任务使用 `task.yaml`，需要先迁移成 Harbor 格式。将下面 `--input` 的占位路径替换为实际下载的旧版任务目录。

```bash
.venv-harbor/bin/harbor tasks migrate \
  --input /你的路径/terminal-bench-1任务目录 \
  --output myscript/assets/terminal-bench-1-harbor
```

迁移后检查任务配置和 verifier，再运行。

```bash
.venv-harbor/bin/harbor run "${mini_args[@]}" \
  --path myscript/assets/terminal-bench-1-harbor \
  --job-name "terminal-1-$(date +%Y%m%d-%H%M%S)"
```

迁移工具可能需要人工修正部分任务，见 [Harbor 迁移说明](https://github.com/harbor-framework/docs/blob/main/cli/tasks.mdx#harbor-tasks-migrate)。当前 `terminal-bench/terminal-bench` 已指向持续更新的版本，最新发布为 4.1，选择旧版任务时请确认具体版本。[Terminal-Bench 发布记录](https://github.com/harbor-framework/terminal-bench/releases)

### Terminal-Bench 2.0

```bash
.venv-harbor/bin/harbor run "${mini_args[@]}" \
  --dataset terminal-bench/terminal-bench-2 \
  --job-name "terminal-2-$(date +%Y%m%d-%H%M%S)"
```

此前试跑的是 Terminal-Bench 2.1，本地已有任务，可以直接运行。

```bash
.venv-harbor/bin/harbor run "${mini_args[@]}" \
  --path myscript/assets/terminal-bench-2-1 \
  --job-name "terminal-2-1-$(date +%Y%m%d-%H%M%S)"
```

数据集名称和版本可在 [Terminal-Bench 数据集目录](https://hub.harborframework.com/datasets/terminal-bench) 查询。

### OfficeQA

本地尚未准备 OfficeQA 的 Harbor 任务。需要取得 Hugging Face 数据权限，下载问题和文档语料，再生成带 verifier 的 Harbor 任务目录。[OfficeQA 官方说明](https://github.com/databricks/officeqa)

假设生成后的任务位于 `myscript/assets/officeqa/tasks`，准备完成后的运行入口如下。

```bash
.venv-harbor/bin/harbor run "${mini_args[@]}" \
  --path myscript/assets/officeqa/tasks \
  --job-name "officeqa-$(date +%Y%m%d-%H%M%S)"
```

### 调整参数和查看结果

| 参数 | 含义 |
| --- | --- |
| `--n-tasks 3` / `-l 3` | 最多跑 3 题，跑全量时从公共参数中删除这一项 |
| `--n-concurrent 1` / `-n 1` | 并发运行的题数 |
| `--include-task-name git-multibranch` / `-i git-multibranch` | 指定题目，支持通配符，可以重复传入 |
| `--ak 'config={"agent":{"step_limit":80}}'` | mini 每题步数上限 |
| `--ak cost_limit=3` | 每题按 LiteLLM 记录计费的费用上限，单位为 USD |
| `--n-attempts 1` / `-k 1` | 每题尝试次数；Harbor 中的 `-k` 表示尝试次数 |
| `--jobs-dir` | 作业输出目录 |
| `--job-name` | 本次作业名称，上面的命令用时间戳区分运行 |

Harbor 会运行任务自带的 verifier。完成后启动结果查看器，终端会打印浏览器访问地址。

```bash
.venv-harbor/bin/harbor view myscript/results/harbor
```

查看当前可用数据集及完整参数。

```bash
.venv-harbor/bin/harbor datasets list
.venv-harbor/bin/harbor run --help
```
