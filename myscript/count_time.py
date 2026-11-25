"""Load task records from serial run logs and compute timing statistics."""

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import typer

if __package__:
    from .count_tokens import InputTokens, TokenBreakdown, api_prompt_tokens, count_input_tokens, count_token_breakdown
else:
    from count_tokens import InputTokens, TokenBreakdown, api_prompt_tokens, count_input_tokens, count_token_breakdown

PATTERN = re.compile(
    r"^(?P<end>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .*? - "
    r"[\w.]+\.(?P<method>run|query|execute_actions|execute): Elapsed time (?P<seconds>\S+) secs\s*$",
)
SAVED = re.compile(r"^\d{4}-\d{2}-\d{2} .*? - .*? - INFO - Saved trajectory to '(?P<path>.*)'\s*$")
TOLERANCE = 0.01


@dataclass(frozen=True)
class Event:
    kind: str
    end: datetime
    seconds: float

    @property
    def start(self) -> datetime:
        return self.end - timedelta(seconds=self.seconds)


@dataclass
class Task:
    id: str
    source: str
    events: list[Event]
    title: str = ""
    status: str = "未知"
    cost: float | None = None
    api_calls: int | None = None
    query_costs: dict[int, float] = field(default_factory=dict)
    query_input_tokens: dict[int, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    input_tokens: InputTokens | None = None
    token_breakdown: TokenBreakdown = field(default_factory=TokenBreakdown)
    model_name: str | None = None
    benchmark_status: str | None = None
    tool_result_window: str = "未记录"


def parse_event(match: re.Match) -> Event:
    seconds = float(match["seconds"])
    if not math.isfinite(seconds) or seconds < 0:
        raise typer.BadParameter("计时必须是有限的非负秒数。")
    return Event(
        {"execute": "tool", "execute_actions": "tool"}.get(match["method"], match["method"]),
        datetime.strptime(match["end"], "%Y-%m-%d %H:%M:%S,%f"),
        seconds,
    )


def finite_number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def add_trajectory(task: Task, path: Path | None) -> None:
    if path is None or not path.is_file():
        task.title = task.id
        task.warnings.append("缺少轨迹文件，题名、状态和 query 费用不可用。")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("instance_id", task.id) != task.id:
        raise typer.BadParameter(f"轨迹 ID 与日志不一致：{path}")
    info = data.get("info", {})
    config = info.get("config", {})
    model = config.get("model") or {}
    agent = config.get("agent") or {}
    task.model_name = model.get("model_name")
    for settings, key in ((agent, "tool_result_retention_rounds"), (model, "tool_result_keep_rounds")):
        if key in settings:
            value = settings[key]
            if value is None:
                task.tool_result_window = "不限"
            elif type(value) is int and value >= 0:
                task.tool_result_window = str(value)
            break
    stats = info.get("model_stats", {})
    task.cost = finite_number(stats.get("instance_cost"))
    task.api_calls = stats.get("api_calls")
    task.status = info.get("exit_status") or "未完成"
    messages = data.get("messages", [])
    task.input_tokens = count_input_tokens(messages)
    task.token_breakdown = count_token_breakdown(messages)
    prompt = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    description = re.search(r"<pr_description>(.*?)</pr_description>", prompt, re.DOTALL) if isinstance(prompt, str) else None
    task.title = next(
        (line.strip() for line in description[1].splitlines() if line.strip() and line.strip() != "Consider the following PR description:"),
        task.id,
    ) if description else task.id

    queries = [event for event in task.events if event.kind == "query"]
    records = []
    for message in messages:
        extra = message.get("extra", {})
        tokens = api_prompt_tokens(extra.get("response"))
        if "cost" in extra or tokens is not None:
            records.append((extra, tokens))
    candidates = []
    for record, _ in records:
        timestamp = finite_number(record.get("timestamp"))
        candidates.append([
            index for index, event in enumerate(queries)
            if timestamp is not None
            and event.start.timestamp() - TOLERANCE <= timestamp <= event.end.timestamp() + TOLERANCE
        ])
    for (record, tokens), matches in zip(records, candidates):
        if len(matches) != 1 or sum(matches[0] in other for other in candidates) != 1:
            continue
        if (cost := finite_number(record.get("cost"))) is not None:
            task.query_costs[matches[0]] = cost
        if tokens is not None:
            task.query_input_tokens[matches[0]] = tokens
    if task.cost is None:
        task.warnings.append("轨迹没有有效的累计费用；不根据模型名猜测价格。")
    if len(task.query_costs) != len(queries) or len(task.query_costs) != sum("cost" in record for record, _ in records):
        task.warnings.append("部分 Query 费用无法按时间戳唯一对应；未匹配的费用显示不可用，不按序号猜配。")
    if task.cost is not None and not math.isclose(sum(task.query_costs.values()), task.cost, abs_tol=1e-8):
        task.warnings.append("累计费用包含未匹配到色块的费用，可能来自格式错误等调用；以轨迹累计值为准。")


def read_benchmark_statuses(path: Path) -> dict[str, str]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not {"resolved_ids", "unresolved_ids"} <= report.keys():
        raise typer.BadParameter(f"{path}: SWE-bench 评测汇总应包含 resolved_ids 和 unresolved_ids。")
    statuses = {}
    for key, status in (
        ("resolved_ids", "passed"),
        ("unresolved_ids", "failed"),
        ("empty_patch_ids", "empty-patch"),
        ("error_ids", "error"),
    ):
        ids = report.get(key, [])
        if not isinstance(ids, list) or any(not isinstance(instance_id, str) for instance_id in ids):
            raise typer.BadParameter(f"{path}: {key} 应为题目 ID 列表。")
        for instance_id in ids:
            if instance_id in statuses and statuses[instance_id] != status:
                raise typer.BadParameter(f"{path}: {instance_id} 的评测结果冲突。")
            statuses[instance_id] = status
    return statuses


def read_tasks(log: Path, source: str, evaluation: Path | None = None) -> list[Task]:
    tasks, pending, used = [], [], set()
    trajectories = sorted(set(log.parent.glob("*/*.traj.json")) | set(log.parent.glob("*.traj.json")))
    report = evaluation or log.with_name("results.json")
    statuses = read_benchmark_statuses(report) if report.is_file() else {}

    def append(events: list[Event], path: Path | None = None, instance_id: str = "") -> None:
        if path is not None:
            used.add(path)
        task = Task(instance_id or f"run-{len(tasks) + 1}", source, events)
        add_trajectory(task, path)
        tasks.append(task)

    for line in log.read_text(encoding="utf-8").splitlines():
        if match := PATTERN.match(line):
            pending.append(parse_event(match))
        elif saved := SAVED.match(line):
            if sum(event.kind == "run" for event in pending) > 1:
                raise typer.BadParameter(f"{log}: 多个 run 共用保存边界，无法确定题目归属。")
            # Resolve only inside this result directory, even when the log contains an old absolute path.
            filename = Path(saved["path"]).name
            instance_id = filename.removesuffix(".traj.json")
            paths = [path for path in trajectories if path.name == filename]
            if len(paths) > 1 or (paths and paths[0] in used):
                raise typer.BadParameter(f"{log}: 轨迹文件重复使用，无法确定每次运行的费用：{filename}")
            append(pending, paths[0] if paths else None, instance_id)
            pending = []

    groups, current = [], []
    for event in pending:
        current.append(event)
        if event.kind == "run":
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    remaining = [path for path in trajectories if path not in used]
    if len(groups) == 1 and len(remaining) == 1:
        path = remaining[0]
        append(groups[0], path, path.name.removesuffix(".traj.json"))
    else:
        for group in groups:
            append(group)
    for path in trajectories:
        if path not in used:
            data = json.loads(path.read_text(encoding="utf-8"))
            append([], path, data.get("instance_id") or path.name.removesuffix(".traj.json"))

    previous_end = None
    for task in tasks:
        task.benchmark_status = statuses.get(task.id)
        run = next((event for event in task.events if event.kind == "run"), None)
        if run:
            if previous_end and (previous_end - run.start).total_seconds() > TOLERANCE:
                raise typer.BadParameter(f"{log}: run 区间重叠；仅支持 --workers 1 的串行日志。")
            previous_end = run.end
    return tasks


def analyze(task: Task) -> dict:
    runs = [event for event in task.events if event.kind == "run"]
    calls = sorted((event for event in task.events if event.kind != "run"), key=lambda event: event.start)
    warnings = list(task.warnings)
    if len(runs) > 1:
        raise typer.BadParameter(f"{task.id}: 同一题有多个 run，无法合并。")
    if not task.events:
        warnings.append("没有计时记录，耗时和图表不可用；不从轨迹时间戳伪造阶段耗时。")
        return {"total": None, "calls": [], "warnings": warnings, "scope": "无计时数据"}
    if runs:
        origin, total, scope = runs[0].start, runs[0].seconds, "完整 run"
    else:
        origin = calls[0].start
        total = (max(event.end for event in calls) - origin).total_seconds()
        scope = "观测区间（非完整 run）"
        warnings.append("没有 run 记录：仅展示已记录调用覆盖的时间区间，不代表任务总耗时。")
    if total <= 0:
        raise typer.BadParameter(f"{task.id}: 时间区间为零，无法生成占比图。")
    latest_end = origin
    for event in calls:
        if (event.start - origin).total_seconds() < -TOLERANCE or (event.end - origin).total_seconds() > total + TOLERANCE:
            raise typer.BadParameter(f"{task.id}: 调用超出 run 区间；可能混入并行任务或系统时钟发生跳变。")
        if (latest_end - event.start).total_seconds() > TOLERANCE:
            raise typer.BadParameter(f"{task.id}: 调用明显重叠；仅支持串行调用，不支持多 worker 或嵌套计时。")
        latest_end = max(latest_end, event.end)
    totals = {kind: sum(event.seconds for event in calls if event.kind == kind) for kind in ("query", "tool")}
    if sum(totals.values()) > total + TOLERANCE:
        raise typer.BadParameter(f"{task.id}: 累计阶段耗时超过总区间。")
    totals["other"] = max(0, total - sum(totals.values()))
    for kind in ("query", "tool"):
        if not any(event.kind == kind for event in calls):
            warnings.append(f"没有 {kind} 记录：可能未加计时装饰器或没有调用，不能据此认定实际耗时为零。")
    return {"total": total, "origin": origin, "calls": calls, "totals": totals, "warnings": warnings, "scope": scope}
