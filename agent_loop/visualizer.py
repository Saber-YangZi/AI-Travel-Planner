"""
AgentLoop 可视化工具

生成方式：
  - ASCII/Unicode 终端仪表板
  - JSON 数据（供自定义前端消费）
  - HTML 内嵌图表
  - CSV 原始数据导出
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from agent_loop.metrics import LoopSummary, IterationMetrics


class LoopVisualizer:
    """循环效率可视化"""

    # ------------------------------------------------------------------
    # 终端仪表板
    # ------------------------------------------------------------------

    @staticmethod
    def terminal_dashboard(summary: LoopSummary) -> str:
        """打印终端友好的仪表板"""
        s = summary
        bar_width = 30
        efficiency_bar = "█" * int(s.efficiency_score / 100 * bar_width) + \
                         "░" * (bar_width - int(s.efficiency_score / 100 * bar_width))

        return f"""
╔══════════════════════════════════════════════════╗
║          🌀 AgentLoop 性能仪表板               ║
╠══════════════════════════════════════════════════╣
║  任务: {s.task[:45]:<45} ║
╠══════════════════════════════════════════════════╣
║  总耗时:     {s.total_duration_ms/1000:>8.2f}s                     ║
║  迭代次数:   {s.total_iterations:>8}                        ║
║  首Token延迟:{s.ttft_ms:>8.1f}ms                      ║
║  Token 产出: {s.total_output_tokens:>8}                        ║
║  工具调用:   {s.total_tool_calls:>8}                        ║
║  错误次数:   {s.total_errors:>8}                        ║
║  重试次数:   {s.total_retries:>8}                        ║
╠══════════════════════════════════════════════════════╣
║  效率评分: {s.efficiency_score:>6.1f}/100                   ║
║  [{efficiency_bar}]  ║
║  速率:      {s.tokens_per_second:>8.1f} tok/s                  ║
║  工具占比:  {s.tool_efficiency:>8.1%}                       ║
╚══════════════════════════════════════════════════════╝
""" + (LoopVisualizer._format_warnings(s) if s.warnings else "")

    @staticmethod
    def _format_warnings(summary: LoopSummary) -> str:
        lines = ["\n⚠️  优化建议:"]
        for w in summary.warnings:
            lines.append(f"  • {w}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # HTML 可视化
    # ------------------------------------------------------------------

    @staticmethod
    def to_html(summary: LoopSummary, iterations: list[IterationMetrics],
                output_path: str | Path) -> Path:
        """生成包含图表的 HTML 报告"""
        out = Path(output_path)

        # 准备迭代时序数据
        iter_labels = json.dumps([it.iteration for it in iterations])
        iter_durations = json.dumps([round(it.duration_ms, 1) for it in iterations])

        # 按步骤类型着色
        step_colors = []
        for it in iterations:
            if it.error:
                step_colors.append('"#dc3545"')
            elif it.tool_name:
                step_colors.append('"#ffc107"')
            elif it.step_name == "agent_reason":
                step_colors.append('"#17a2b8"')
            else:
                step_colors.append('"#6c757d"')

        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>AgentLoop 性能报告</title>
<style>
body{{font-family:system-ui;max-width:1200px;margin:0 auto;padding:20px;background:#f0f2f5}}
.card{{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}
.metric{{text-align:center;padding:16px;border-radius:8px;background:#f8f9fa}}
.metric .value{{font-size:28px;font-weight:700;color:#1a1a2e}}
.metric .label{{font-size:13px;color:#666;margin-top:4px}}
.progress-bg{{background:#eee;border-radius:8px;height:24px;overflow:hidden}}
.progress-fg{{background:linear-gradient(90deg,#667eea,#764ba2);height:100%;transition:width .3s}}
.warn{{background:#fff3cd;border-left:4px solid #ffc107;padding:12px;margin:8px 0;border-radius:0 8px 8px 0}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f8f9fa}}tr:hover{{background:#f8f9fa}}
.badge{{padding:2px 8px;border-radius:4px;font-size:12px}}
.badge-ok{{background:#d4edda;color:#155724}}
.badge-warn{{background:#fff3cd;color:#856404}}
.badge-err{{background:#f8d7da;color:#721c24}}
</style></head><body>
<h1>🌀 AgentLoop 性能报告</h1>
<div class="card">
<h3>📊 核心指标</h3>
<div class="metrics">
<div class="metric"><div class="value">{summary.total_duration_ms/1000:.1f}s</div><div class="label">总耗时</div></div>
<div class="metric"><div class="value">{summary.total_iterations}</div><div class="label">迭代次数</div></div>
<div class="metric"><div class="value">{summary.ttft_ms:.0f}ms</div><div class="label">首Token延迟</div></div>
<div class="metric"><div class="value">{summary.total_output_tokens}</div><div class="label">输出Tokens</div></div>
<div class="metric"><div class="value">{summary.total_tool_calls}</div><div class="label">工具调用</div></div>
<div class="metric"><div class="value">{summary.tokens_per_second:.1f}</div><div class="label">Token/秒</div></div>
<div class="metric"><div class="value">{summary.total_errors}</div><div class="label">错误次数</div></div>
<div class="metric"><div class="value">{summary.total_retries}</div><div class="label">重试次数</div></div>
</div></div>
<div class="card">
<h3>⚡ 效率评分: {summary.efficiency_score:.1f}/100</h3>
<div class="progress-bg"><div class="progress-fg" style="width:{summary.efficiency_score}%"></div></div>
<p>Token 速率: {summary.tokens_per_second:.1f} tok/s | 工具耗时占比: {summary.tool_efficiency:.1%}</p>
</div>
{''.join(f'<div class="warn">⚠️ {w}</div>' for w in summary.warnings)}
<div class="card"><h3>📋 迭代明细</h3>
<div style="max-height:60vh;overflow:auto"><table><thead><tr>
<th>#</th><th>步骤</th><th>耗时</th><th>输入Token</th><th>输出Token</th><th>工具</th><th>工具耗时</th><th>状态</th></tr></thead><tbody>
{''.join(
    f'<tr><td>{it.iteration}</td><td>{it.step_name}</td>'
    f'<td>{it.duration_ms:.0f}ms</td><td>{it.input_tokens}</td><td>{it.output_tokens}</td>'
    f'<td>{it.tool_name}</td><td>{it.tool_duration_ms:.0f}ms</td>'
    f'<td><span class="badge {"badge-err" if it.error else "badge-ok"}">'
    f'{"错误" if it.error else "正常"}</span></td></tr>'
    for it in iterations
)}
</tbody></table></div></div>
<p style="text-align:center;color:#999;margin-top:24px">生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>"""
        out.write_text(html, encoding="utf-8")
        return out

    # ------------------------------------------------------------------
    # CSV 导出
    # ------------------------------------------------------------------

    @staticmethod
    def to_csv(summary: LoopSummary, iterations: list[IterationMetrics],
               output_path: str | Path) -> Path:
        """导出 CSV 原始数据"""
        import csv
        out = Path(output_path)

        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["iteration", "step", "duration_ms", "input_tokens",
                             "output_tokens", "tool_name", "tool_duration_ms", "error"])
            for it in iterations:
                writer.writerow([
                    it.iteration, it.step_name, round(it.duration_ms, 1),
                    it.input_tokens, it.output_tokens,
                    it.tool_name, round(it.tool_duration_ms, 1),
                    it.error,
                ])
            # 汇总行
            writer.writerow([])
            writer.writerow(["SUMMARY", "total_duration_ms", "total_tool_calls",
                             "total_errors", "efficiency_score"])
            writer.writerow(["", round(summary.total_duration_ms, 1),
                             summary.total_tool_calls, summary.total_errors,
                             round(summary.efficiency_score, 1)])

        return out
