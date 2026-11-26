"""Plot serial runs: python myscript/plot_timing.py RESULTS_DIRECTORY."""

from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

import litellm
import typer
from jinja2 import Environment

if __package__:
    from .count_time import Task, analyze, read_harbor_task, read_tasks
else:
    from count_time import Task, analyze, read_harbor_task, read_tasks

COLORS = {"query": "#2563eb", "tool": "#94a3b8", "other": "#e2e8f0"}
TEMPLATE = Environment(autoescape=True)


def money(value: float | None) -> str:
    return "不可用" if value is None else f"${value:.6f}"


def timeline(task: Task, stats: dict, *, compact: bool = False) -> str:
    if stats["total"] is None:
        return '<span class="note">无计时数据</span>'
    total, origin = stats["total"], stats["origin"]
    segments, ticks, query_rows = [], [], []
    queries = [event for event in task.events if event.kind == "query"]
    counts = {"query": 0, "tool": 0}
    for event in stats["calls"]:
        counts[event.kind] += 1
        start, end = (event.start - origin).total_seconds(), (event.end - origin).total_seconds()
        x = 40 + max(0, start) / total * 1040
        width = max(0, min(total, end) - max(0, start)) / total * 1040
        label = f"{event.kind} #{counts[event.kind]}: {start:.3f}–{end:.3f}s · 耗时 {event.seconds:.3f}s"
        short_tokens = ""
        query_attributes = ""
        if event.kind == "query":
            index = queries.index(event)
            if not compact:
                query_attributes = f' class="query-hit" data-query="{index}" role="button" tabindex="0" aria-label="查看 Query {index + 1} 消息顺序"'
            price = money(task.query_costs.get(index))
            tokens = task.query_input_tokens.get(index)
            exact_tokens = "不可用" if tokens is None else f"{tokens:,}"
            label += f" · 输入 Token {exact_tokens} · 轨迹费用 {price}"
            if tokens is not None and not compact:
                short_tokens = str(tokens) if tokens < 1000 else f"{tokens / 1000:.1f}".removesuffix(".0") + "k"
                if tokens >= 1000 and width < 8 * len(short_tokens) + 4:
                    short_tokens = f"{tokens / 1000:.0f}k"
            if not compact:
                query_rows.append(
                    f'<tr><th scope="row"><button type="button" class="query-open" data-query="{index}">#{counts["query"]}</button></th><td>{start:.3f}–{end:.3f} s</td>'
                    f'<td>{event.seconds:.3f} s</td><td>{exact_tokens}</td><td>{price}</td></tr>'
                )
        segments.append(
            f'<rect x="{x:.6f}" y="30" width="{width:.6f}" height="48" '
            f'fill="{COLORS[event.kind]}"{query_attributes}><title>{escape(label)}</title></rect>'
        )
        if short_tokens and width >= 8 * len(short_tokens) + 4:
            segments.append(
                f'<text class="query-tokens" x="{x + width / 2:.6f}" y="58" text-anchor="middle">{short_tokens}</text>'
            )
    if not compact:
        for index in range(6):
            x = 40 + index / 5 * 1040
            ticks.append(f'<path d="M{x} 80v8" stroke="#64748b"/>'
                         f'<text x="{x}" y="110" text-anchor="middle">{total * index / 5:.2f}s</text>')
    axis = (
        f'<svg viewBox="{ "40 30 1040 48" if compact else "0 0 1120 135" }" '
        f'role="img" aria-label="等比例时间轴">'
        f'<rect x="40" y="30" width="1040" height="48" fill="{COLORS["other"]}"/>'
        f'{"".join(segments)}{"".join(ticks)}</svg>'
    )
    if not query_rows:
        return axis
    return (
        f'{axis}<details class="query-details"><summary>逐次 Query 明细（{len(query_rows)} 次）</summary>'
        '<div class="table-scroll"><table><thead><tr><th scope="col">Query</th><th scope="col">时间区间</th>'
        '<th scope="col">耗时</th><th scope="col">输入 Token</th><th scope="col">轨迹费用（USD）</th></tr></thead>'
        f'<tbody>{"".join(query_rows)}</tbody></table></div></details>'
    )


def charts(task: Task, stats: dict) -> str:
    if stats["total"] is None:
        return ""
    circles, rows, offset = [], [], 0.0
    labels = {"query": "Query · 查询阶段", "tool": "Tool · 工具阶段", "other": "其他或未记录"}
    for kind, seconds in stats["totals"].items():
        percent = seconds / stats["total"] * 100
        if percent:
            circles.append(
                f'<circle cx="120" cy="120" r="88" fill="none" stroke="{COLORS[kind]}" '
                f'stroke-width="32" pathLength="100" stroke-dasharray="{percent:.7f} {100 - percent:.7f}" '
                f'stroke-dashoffset="{-offset:.7f}" transform="rotate(-90 120 120)">'
                f'<title>{labels[kind]}: {seconds:.3f}s ({percent:.2f}%)</title></circle>'
            )
        offset += percent
        count = str(sum(event.kind == kind for event in stats["calls"])) if kind != "other" else "—"
        rows.append(
            f'<tr><td><span class="swatch" style="background:{COLORS[kind]}"></span>{labels[kind]}</td>'
            f'<td>{seconds:.3f} s</td><td>{percent:.2f}%</td><td>{count}</td></tr>'
        )
    return TEMPLATE.from_string('''
<section><h2>1. 总体时间占比</h2><div class="overview">
<svg class="donut" viewBox="0 0 240 240" role="img" aria-label="总体时间占比">
{{ circles | safe }}
<text x="120" y="106" text-anchor="middle" style="font-size:24px;fill:#0f172a">{{ '%.2f' | format(total) }}s</text>
<text x="120" y="129" text-anchor="middle" style="font-size:12px">{{ scope }}</text>
<text x="120" y="149" text-anchor="middle" style="font-size:12px">轨迹总费用 {{ cost }}</text></svg>
<div class="table-scroll"><table><thead><tr><th>类别</th><th>累计耗时</th><th>占比</th><th>阶段次数</th></tr></thead>
<tbody>{{ rows | safe }}</tbody></table></div></div>
<p class="note">run 已包含 query、tool 和其他处理时间，不能重复相加。</p></section>
<section><h2>2. 线性时间轴</h2>
<p><span class="swatch" style="background:#2563eb"></span>Query
　<span class="swatch" style="background:#94a3b8"></span>Tool
　<span class="swatch" style="background:#e2e8f0"></span>其他或未记录</p>
<div class="timeline">{{ timeline | safe }}</div>
<p class="note">上下文压缩：无独立计时记录，无法标注发生时间和耗时。</p>
<p class="note">点击蓝色 Query 色块或明细中的编号，查看该次请求的消息顺序和长度。时间轴长度与秒数成比例，色块数字为 API 输入 Token（k = 千）。
execute_actions 包含一轮全部工具执行及结果处理，并非单个工具；旧版 execute 仍表示单个工具。
query 包含模型请求及 agent 前后处理。位置由日志结束时间减去耗时近似还原（毫秒精度），不是精确 tracing。
区间不包含 run 之前的镜像拉取和容器启动。</p></section>
''').render(circles="".join(circles), rows="".join(rows), total=stats["total"], scope=stats["scope"], cost=money(task.cost), timeline=timeline(task, stats))


def price_breakdown(task: Task) -> tuple[Decimal, ...] | None:
    model = task.model_name
    if model == "openai/deepseek-flash":
        model = "deepseek/deepseek-flash"
    tokens = task.token_breakdown
    if (
        model != "deepseek/deepseek-flash"
        or tokens.unknown_rounds
        or tokens.input_covered != tokens.covered
        or tokens.output_covered != tokens.covered
    ):
        return None
    rates = litellm.model_cost.get(model, {})
    keys = ("input_cost_per_token", "input_cost_per_token_cache_hit", "output_cost_per_token")
    if any(rates.get(key) is None for key in keys):
        return None
    tokens = task.token_breakdown
    return tuple(
        count * Decimal(str(rates[key]))
        for count, key in zip(
            (tokens.uncached, tokens.cached, tokens.output),
            keys,
        )
    )


def render_report(tasks: list[Task]) -> str:
    windows = sorted({"0" if task.tool_result_window == "不限" else task.tool_result_window for task in tasks})
    rtk_modes = {task.rtk_enabled for task in tasks}
    rtk_label = "/".join(label for mode, label in ((False, "关闭"), (True, "开启"), (None, "未记录")) if mode in rtk_modes)
    title = f"Agent 耗时与 Token 分析 · k={'/'.join(windows)} · RTK={rtk_label}"
    items = []
    for task in tasks:
        stats = analyze(task)
        items.append({"task": task, "stats": stats, "duration": f'{stats["total"]:.3f} s' if stats["total"] is not None else "不可用",
                      "price": price_breakdown(task), "money": money(task.cost), "preview": timeline(task, stats, compact=True), "charts": charts(task, stats)})
    return TEMPLATE.from_string('''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title><style>
body { margin:32px auto; padding:0 24px; max-width:1120px; color:#0f172a; background:#f8fafc; font:16px/1.6 system-ui,sans-serif; }
h1 { margin-bottom:0; } h2 { margin-top:0; } section { background:white; border:1px solid #e2e8f0; border-radius:12px; padding:24px; margin:24px 0; }
.task-list { max-height:300px; overflow-y:auto; display:grid; gap:8px; padding:4px; }
.task-button { display:grid; grid-template-columns:minmax(180px,1fr) minmax(150px,1.2fr) 130px; gap:16px; align-items:center; width:100%; padding:12px; border:1px solid #cbd5e1; border-radius:8px; background:white; color:inherit; text-align:left; cursor:pointer; font:inherit; }
.task-button[aria-pressed="true"] { border-color:#2563eb; background:#eff6ff; box-shadow:0 0 0 1px #2563eb; }
.task-button[data-result="passed"] { border-inline-start:4px solid #15803d; background:#dcfce7; }
.task-button[data-result="failed"] { border-inline-start:4px solid #b91c1c; background:#fee2e2; }
.bench-status { display:block; color:#475569; font-size:13px; }
[data-result="passed"] .bench-status { color:#166534; }
[data-result="failed"] .bench-status { color:#991b1b; }
.task-button:focus-visible { outline:3px solid #2563eb; outline-offset:2px; }
.task-name { display:block; font-size:13px; color:#475569; overflow-wrap:anywhere; } .task-id { overflow-wrap:anywhere; }
.preview svg { width:100%; height:20px; display:block; border-radius:3px; } .metrics { text-align:right; font-size:14px; }
.overview { display:flex; align-items:center; flex-wrap:wrap; gap:24px; } .donut { width:240px; height:240px; flex-shrink:0; }
.table-scroll { overflow-x:auto; flex:1; } table { border-collapse:collapse; width:100%; } th,td { text-align:right; padding:12px; white-space:nowrap; }
th:first-child,td:first-child { text-align:left; } tr { border-bottom:1px solid #e2e8f0; }
.swatch { display:inline-block; width:12px; height:12px; margin-right:8px; border-radius:3px; }
.warning { padding:12px 16px; background:#fef3c7; border-left:4px solid #f59e0b; }
.note { color:#475569; font-size:14px; overflow-wrap:anywhere; } .summary { display:flex; flex-wrap:wrap; gap:8px 28px; }
.timeline { overflow-x:auto; } .timeline svg { width:100%; min-width:650px; } svg text { font:14px system-ui,sans-serif; fill:#475569; }
.timeline .query-tokens { fill:white; font-size:12px; pointer-events:none; }
.query-details summary { cursor:pointer; }
.token-bar { display:flex; height:20px; overflow:hidden; border-radius:4px; }
.token-bar span { flex:0 0 auto; }
.token-legend { display:flex; flex-wrap:wrap; gap:8px 28px; list-style:none; padding:0; }
.token-legend strong { white-space:nowrap; }
.query-hit { cursor:pointer; } .query-hit:hover,.query-hit:focus { stroke:#0f172a; stroke-width:2; outline:none; }
.query-open { color:#1d4ed8; background:none; border:0; cursor:pointer; font:inherit; text-decoration:underline; }
.message-dialog { width:min(1100px,92vw); max-height:85vh; border:1px solid #cbd5e1; border-radius:16px; padding:24px; color:#0f172a; }
.message-dialog::backdrop { background:rgb(15 23 42 / 55%); }
.dialog-header { display:flex; justify-content:space-between; align-items:center; gap:16px; }
.dialog-header h2 { margin:0; } .dialog-actions { display:flex; gap:8px; }
.dialog-actions button { padding:8px 12px; border:1px solid #cbd5e1; border-radius:6px; background:white; cursor:pointer; }
.message-bar { display:flex; height:56px; width:100%; background:#f1f5f9; border-radius:6px; overflow:hidden; }
.message-segment { flex-shrink:0; height:100%; box-sizing:border-box; border-right:1px solid rgb(255 255 255 / 65%); color:white; overflow:hidden; display:flex; align-items:center; justify-content:center; white-space:nowrap; font-size:12px; }
.message-table { max-height:35vh; overflow:auto; margin-top:16px; }
.message-table th { position:sticky; top:0; background:white; }
[hidden] { display:none !important; } @media(max-width:650px) { .task-button { grid-template-columns:1fr 110px; } .preview { grid-column:1/-1; grid-row:2; } section { padding:16px; } }
</style></head><body>
{% macro breakdown_bar(values, number_format, suffix='', unknown_input=0) %}
{% set total = (values | sum) + unknown_input %}
{% set segments = [
    ('Prefill · 缓存未命中', '#1d4ed8', values[0]),
    ('Prefill · 缓存命中', '#4495ec', values[1]),
    ('Decode · 输出', '#6b7280', values[2]),
] %}
{% if unknown_input %}{% set segments = segments[:2] + [('Prefill · 缓存状态未知', '#0e7490', unknown_input)] + segments[2:] %}{% endif %}
{% if total > 0 %}
<div class="token-bar" aria-hidden="true">
{% for label, color, value in segments if value > 0 %}
<span style="width:{{ '%.9f' | format(100 * (value / total)) }}%;background:{{ color }}" title="{{ label }} · {{ number_format.format(value) }}{{ suffix }}"></span>
{% endfor %}
</div>
{% endif %}
<ul class="token-legend">
{% for label, color, value in segments %}
<li><span class="swatch" style="background:{{ color }}"></span>{{ label }} <strong>{{ number_format.format(value) }}{% if total > 0 %} · {{ '%.1f' | format(100 * (value / total)) }}%{% endif %}</strong></li>
{% endfor %}
</ul>
{% endmacro %}
<h1>{{ title }}</h1><p>{{ items | length }} 个运行记录 · 离线报告</p>
<section><h2>选择题目</h2><p class="note">上下滚动查看题目，点击切换下方图表和 Token 统计。同一 ID 的不同运行由来源路径区分。
缩略轴各自压缩到相同宽度，仅比较阶段分布；跨题总耗时请看秒数。</p>
{% set benchmark_labels = {'passed': '评测成功', 'failed': '评测失败', 'empty-patch': '评测失败 · 空补丁', 'error': '评测出错'} %}
<div class="task-list" aria-label="题目列表">
{% for item in items %}
{% set benchmark = item.task.benchmark_status %}
{% set run_failed = item.task.status not in ('未知', '未完成', 'Submitted') %}
{% set result = 'passed' if benchmark == 'passed' else ('failed' if benchmark in ('failed', 'empty-patch', 'error') or run_failed else 'unknown') %}
<button type="button" class="task-button" data-result="{{ result }}" data-task="{{ loop.index0 }}" aria-controls="task-{{ loop.index0 }}" aria-pressed="{{ 'true' if loop.first else 'false' }}">
<span><strong class="task-id">{{ item.task.id }}</strong><span class="bench-status">{{ benchmark_labels.get(benchmark, '运行失败 · ' ~ item.task.status if run_failed else '无评测结果') }}</span><span class="task-name">{{ item.task.title }}</span><span class="task-name">{{ item.task.source }} · k={{ item.task.tool_result_window }}</span></span>
<span class="preview">{{ item.preview | safe }}</span><span class="metrics">{{ item.duration }}<br>轨迹 {{ item.money }}</span></button>{% endfor %}
</div></section>
{% for item in items %}<article id="task-{{ loop.index0 }}" class="task-panel" {% if not loop.first %}hidden{% endif %}>
<h2>{{ item.task.id }}</h2><p>{{ item.task.title }}</p><p class="note">来源：{{ item.task.source }}</p>
<div class="summary"><strong>{{ item.stats.scope }}：{{ item.duration }}</strong>
{% if item.stats.total is none %}<strong>轨迹总费用：{{ item.money }}</strong>{% endif %}
<span>API 调用：{{ item.task.api_calls if item.task.api_calls is not none else '不可用' }}</span><span>Agent 状态：{{ item.task.status }}</span><span>工具结果保留轮数：k={{ item.task.tool_result_window }}</span></div>
{% for warning in item.stats.warnings %}<p class="warning">{{ warning }}</p>{% endfor %}
{{ item.charts | safe }}
{% set tokens = item.task.token_breakdown %}
{% set calls = [tokens.responses, item.task.api_calls or 0] | max %}
{% set coverage %}覆盖 {{ tokens.covered }} / {{ calls }} 次 API 调用{% endset %}
{% set usage_missing %}{{ calls - tokens.covered }} 次调用的输入或输出用量记录不完整，各项已知用量仍计入累计值。{% endset %}
<section><h2>API Token 用量</h2>
<p>累计输入 <strong>{{ '{:,}'.format(tokens.input) if tokens.input_covered else '不可用' }}</strong> Token · 输入记录覆盖 {{ tokens.input_covered }} / {{ calls }} 次调用</p>
<p>累计输出 <strong>{{ '{:,}'.format(tokens.output) if tokens.output_covered else '不可用' }}</strong> Token · 输出记录覆盖 {{ tokens.output_covered }} / {{ calls }} 次调用</p>
{% if tokens.input_covered < calls %}<p class="warning">输入总量仅包含已记录 usage 的调用，其余 {{ calls - tokens.input_covered }} 次调用的输入用量不可用。</p>{% endif %}
<p class="note">输入累计包含缓存命中和未命中 Token。每次请求按该次 API 返回的 usage 计入一次。</p>
{% if tokens.input_covered or tokens.output_covered %}
<p><strong>{{ '{:,}'.format(tokens.input + tokens.output) }} 输入与输出 Token</strong> · 输入记录覆盖 {{ tokens.input_covered }} / {{ calls }} 次，输出记录覆盖 {{ tokens.output_covered }} / {{ calls }} 次</p>
{{ breakdown_bar([tokens.uncached, tokens.cached, tokens.output], '{:,}', ' Token', tokens.unknown_input) }}
{% if tokens.unknown_rounds %}<p class="note">{{ tokens.unknown_rounds }} 次调用缺少有效的缓存命中数，其输入归为「缓存状态未知」。</p>{% endif %}
{% if tokens.covered < calls %}<p class="note">{{ usage_missing }}</p>{% endif %}
{% else %}
<p class="note">没有同时提供有效输入和输出 Token 数的调用（{{ coverage }}）。</p>
{% endif %}
<h3>按角色累计输入（轨迹估算）</h3>
{% if tokens.estimated_input_rounds %}
<p>覆盖 {{ tokens.estimated_input_rounds }} 轮请求，累计估算 <strong>{{ '{:,}'.format(tokens.estimated_input_by_role.values() | sum) }}</strong> 输入 Token。</p>
<div class="table-scroll"><table><thead><tr><th>角色</th><th>累计估算输入 Token</th><th>占估算输入</th></tr></thead><tbody>
{% set estimated_total = tokens.estimated_input_by_role.values() | sum %}
{% for role in ('system', 'user', 'assistant', 'tool') %}
{% set count = tokens.estimated_input_by_role.get(role, 0) %}
<tr><td>{{ role }}</td><td>{{ '{:,}'.format(count) }}</td><td>{{ '%.1f' | format(100 * count / estimated_total if estimated_total else 0) }}%</td></tr>
{% endfor %}
</tbody></table></div>
<p class="note">使用 o200k_base 对最终轨迹的消息 JSON 估算，每次请求携带的历史消息重复计入。历史清理或压缩可能导致重建值偏低，模型分词及请求封装也会产生差异。</p>
{% else %}
<p class="note">当前轨迹缺少可用于按角色重建的 Chat Completions 回复记录。</p>
{% endif %}
<p class="note">服务端 usage 提供实际累计用量；上方按角色拆分由轨迹估算，服务端未提供对应拆分。</p>
</section>
<section><h2>费用构成</h2>
<p>LiteLLM 原始记录总费用 <strong>{{ item.money }} USD</strong></p>
{% if item.price is not none and tokens.covered %}
<p>按 LiteLLM 当前价表重建 <strong>{{ '${:,.6f}'.format(item.price | sum) }} USD</strong> · {{ coverage }}</p>
{{ breakdown_bar(item.price, '${:,.6f}') }}
<p class="note">分类金额使用 API Token 用量和 LiteLLM 的 DeepSeek Flash 价表计算，原始总费用读取轨迹记录。</p>
{% endif %}
{% if item.task.cost == 0 %}<p class="note">原始费用记录为零，可能是运行时计价失败；分类金额为事后重建，实际扣款以官方账单为准。</p>{% endif %}
</section>
<section><h2>输入缓存命中率</h2>
{% if tokens.cache_hit_rate is not none %}
<p><strong>{{ '{:.1%}'.format(tokens.cache_hit_rate) }}</strong>（{{ '{:,}'.format(tokens.cached) }} / {{ '{:,}'.format(tokens.uncached + tokens.cached) }} 输入 Token）</p>
{% else %}<p>不可用</p>{% endif %}
<p class="note">缓存记录覆盖 {{ tokens.cache_rounds }} / {{ calls }} 次调用。命中率分母为已提供有效缓存用量的调用输入总量。</p>
</section>
<script type="application/json" class="message-data">{{ {'messages': item.task.message_sizes, 'queries': item.task.query_contexts, 'input': item.task.query_input_tokens, 'window': item.task.tool_result_window} | tojson }}</script>
</article>{% endfor %}
<p class="note">轨迹费用（USD）由 LiteLLM 在运行时记录。
仅支持单个日志内 --workers 1 的串行运行；不同独立日志可以汇总。报告为生成时的快照，不会自动刷新。</p>
<dialog class="message-dialog" id="message-dialog" aria-labelledby="message-title">
<div class="dialog-header"><h2 id="message-title"></h2><div class="dialog-actions"><button type="button" id="query-previous">上一轮</button><button type="button" id="query-next">下一轮</button><button type="button" id="query-close">关闭</button></div></div>
<p id="message-task" class="note"></p><p id="message-summary"></p><p id="message-cache"></p>
<div class="token-legend"><span><i class="swatch" style="background:#8b5cf6"></i>system</span><span><i class="swatch" style="background:#0d9488"></i>user</span><span><i class="swatch" style="background:#2563eb"></i>assistant</span><span><i class="swatch" style="background:#94a3b8"></i>tool</span></div>
<div class="message-bar" id="message-bar" role="img" aria-label="按原始顺序排列的请求消息，宽度与估算 Token 数成比例"></div>
<p class="note">每个色块对应一条消息，悬停查看长度。宽度按 o200k_base 对消息 JSON 的 Token 估算分配。API 缓存用量展示实际命中总数，服务端未提供逐消息命中位置。</p>
<p class="warning" id="message-warning" hidden></p>
<div class="message-table"><table><thead><tr><th>消息序号</th><th>role</th><th>估算 Token</th><th>字符数</th><th>占比</th><th>tool_call_id</th></tr></thead><tbody id="message-rows"></tbody></table></div>
</dialog>
<script>
const buttons = document.querySelectorAll('.task-button');
const panels = document.querySelectorAll('.task-panel');
buttons.forEach(button => button.addEventListener('click', () => {
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  panels.forEach(panel => { panel.hidden = panel.id !== 'task-' + button.dataset.task; });
}));
const dialog = document.getElementById('message-dialog');
const roleColors = {system:'#8b5cf6', user:'#0d9488', assistant:'#2563eb', tool:'#94a3b8'};
let currentPanel, currentQuery;
const formatNumber = value => value.toLocaleString('en-US');
function showQuery(panel, index) {
  currentPanel = panel;
  currentQuery = index;
  const data = JSON.parse(panel.querySelector('.message-data').textContent);
  const context = data.queries[index];
  const messages = context ? (context.messages || data.messages.slice(0, context.end)) : [];
  const total = messages.reduce((sum, message) => sum + message.tokens, 0);
  const characters = messages.reduce((sum, message) => sum + message.characters, 0);
  const toolTokens = messages.filter(message => message.role === 'tool').reduce((sum, message) => sum + message.tokens, 0);
  document.getElementById('message-title').textContent = `Query #${index + 1} · 请求消息`;
  document.getElementById('message-task').textContent = panel.querySelector('h2').textContent;
  document.getElementById('message-summary').textContent = context ? `${messages.length} 条消息 · 估算 ${formatNumber(total)} Token · ${formatNumber(characters)} 字符 · tool 占 ${total ? (100 * toolTokens / total).toFixed(1) : '0'}%` : '该 Query 缺少可唯一匹配的请求历史。';
  const prompt = data.input[index];
  const cached = context?.cached;
  document.getElementById('message-cache').textContent = `API 输入 ${prompt == null ? '不可用' : formatNumber(prompt)} Token · 缓存命中 ${cached == null ? '不可用' : formatNumber(cached) + ' Token'}${cached != null && prompt > 0 ? ' · 命中率 ' + (100 * cached / prompt).toFixed(1) + '%' : ''}`;
  const warning = document.getElementById('message-warning');
  warning.hidden = !(Number(data.window) > 0) || Boolean(context?.messages);
  warning.textContent = '当前轨迹启用了历史清理，图表根据最终保存的消息重建。较早请求中的原始工具输出已丢失，长度可能偏低，无法据此确定真实缓存失效位置。';
  const bar = document.getElementById('message-bar');
  const rows = document.getElementById('message-rows');
  bar.replaceChildren();
  rows.replaceChildren();
  messages.forEach((message, position) => {
    const percent = total ? 100 * message.tokens / total : 0;
    const segment = document.createElement('span');
    segment.className = 'message-segment';
    segment.style.width = percent + '%';
    segment.style.background = roleColors[message.role];
    segment.textContent = percent >= 7 ? message.role : '';
    segment.title = `#${position + 1} ${message.role} · ${formatNumber(message.tokens)} Token · ${formatNumber(message.characters)} 字符 · ${percent.toFixed(1)}%`;
    bar.append(segment);
    const row = document.createElement('tr');
    [position + 1, message.role, formatNumber(message.tokens), formatNumber(message.characters), percent.toFixed(1) + '%', message.tool_call_id || '—'].forEach(value => {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.append(cell);
    });
    rows.append(row);
  });
  const count = panel.querySelectorAll('.query-hit').length;
  document.getElementById('query-previous').disabled = index <= 0;
  document.getElementById('query-next').disabled = index >= count - 1;
  if (!dialog.open) dialog.showModal();
}
document.querySelectorAll('.query-hit,.query-open').forEach(target => {
  const open = () => showQuery(target.closest('.task-panel'), Number(target.dataset.query));
  target.addEventListener('click', open);
  if (target.classList.contains('query-hit')) target.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); }
  });
});
document.getElementById('query-close').addEventListener('click', () => dialog.close());
document.getElementById('query-previous').addEventListener('click', () => showQuery(currentPanel, currentQuery - 1));
document.getElementById('query-next').addEventListener('click', () => showQuery(currentPanel, currentQuery + 1));
</script></body></html>''').render(items=items, title=title)


def main(
    results: Path = typer.Argument(..., exists=True, file_okay=False, readable=True, help="包含串行运行日志和轨迹的结果目录"),
    output: Path | None = typer.Option(None, "--output", "-o", help="HTML 输出路径，默认放在 myscript/results/plot_timing"),
    evaluation: Path | None = typer.Option(
        None, "--evaluation", exists=True, dir_okay=False, readable=True,
        help="单次运行对应的 SWE-bench 评测汇总 JSON，默认读取日志旁的 results.json",
    ),
) -> None:
    output = output or Path(__file__).parent / "results" / "plot_timing" / f"{datetime.now():%Y%m%d-%H%M%S-%f}.html"
    if output.exists():
        raise typer.BadParameter(f"输出文件已存在，请换一个路径：{output}")
    logs = sorted(results.rglob("minisweagent.log"))
    harbor_logs = sorted(path for path in results.rglob("mini-swe-agent.txt") if path.with_name("mini-swe-agent.trajectory.json").is_file())
    if not logs and not harbor_logs:
        raise typer.BadParameter("没有找到 minisweagent.log 或带轨迹的 Harbor mini-swe-agent.txt。")
    if evaluation is not None and (len(logs) != 1 or harbor_logs):
        raise typer.BadParameter("--evaluation 需要结果目录内只有一个 minisweagent.log；汇总多次运行时请将各自的 results.json 放在对应日志旁。")
    tasks = [task for path in logs for task in read_tasks(path, str(path.relative_to(results)), evaluation)]
    tasks.extend(read_harbor_task(path, str(path.relative_to(results))) for path in harbor_logs)
    if not tasks:
        raise typer.BadParameter("没有找到计时记录或轨迹文件。")
    report = render_report(tasks)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        file.write(report)
    typer.echo(f"报告已生成（{len(tasks)} 个运行记录）：{output.resolve()}")


if __name__ == "__main__":
    typer.run(main)
