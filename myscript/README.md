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
