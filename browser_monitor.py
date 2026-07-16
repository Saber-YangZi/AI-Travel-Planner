"""
浏览器前端错误自动监控系统
=================================
基于 Playwright + Microsoft Edge，通过 CDP (Chrome DevTools Protocol)
自动捕获、分类、记录前端应用中的各类错误，并生成结构化报告。

支持的错误类型：
  - JavaScript 运行时错误 (window.onerror)
  - 未处理的 Promise 拒绝 (unhandledrejection)
  - 控制台错误日志 (console.error 拦截)
  - 网络请求失败 (4xx/5xx 状态码、fetch/XHR 失败)
  - 资源加载失败 (img/script/link/iframe 加载失败)

用法：
  python browser_monitor.py http://localhost:8503          # 监控指定 URL
  python browser_monitor.py http://localhost:8503 --depth 5 # 深度爬取页面
  python browser_monitor.py --help                          # 查看帮助
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections import defaultdict


# ---------------------------------------------------------------------------
# 错误分类体系
# ---------------------------------------------------------------------------

class ErrorSeverity(str, Enum):
    """错误严重等级"""
    CRITICAL = "critical"   # 导致页面崩溃/白屏
    HIGH = "high"           # 核心功能受阻
    MEDIUM = "medium"       # 部分功能异常
    LOW = "low"             # 用户体验问题
    INFO = "info"           # 仅记录信息


class ErrorCategory(str, Enum):
    """错误类别"""
    JS_RUNTIME = "js_runtime"               # JavaScript 运行时错误
    JS_UNHANDLED_REJECTION = "js_unhandled_rejection"  # 未处理 Promise 拒绝
    CONSOLE_ERROR = "console_error"         # console.error()
    NETWORK_FAILURE = "network_failure"     # 网络请求失败
    RESOURCE_LOAD = "resource_load"         # 资源加载失败
    SECURITY = "security"                   # 安全策略违规 (CSP/CORS)
    OTHER = "other"                         # 其他


CATEGORY_TO_SEVERITY: dict[ErrorCategory, ErrorSeverity] = {
    ErrorCategory.JS_RUNTIME:              ErrorSeverity.CRITICAL,
    ErrorCategory.JS_UNHANDLED_REJECTION:  ErrorSeverity.HIGH,
    ErrorCategory.CONSOLE_ERROR:           ErrorSeverity.MEDIUM,
    ErrorCategory.NETWORK_FAILURE:         ErrorSeverity.HIGH,
    ErrorCategory.RESOURCE_LOAD:           ErrorSeverity.MEDIUM,
    ErrorCategory.SECURITY:                ErrorSeverity.HIGH,
    ErrorCategory.OTHER:                   ErrorSeverity.LOW,
}


# ---------------------------------------------------------------------------
# 错误记录数据模型
# ---------------------------------------------------------------------------

@dataclass
class CapturedError:
    """单条捕获的错误记录"""
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    source: str = ""              # 出错文件 URL
    line: int = 0
    column: int = 0
    stack: str = ""               # 完整调用栈
    timestamp: str = ""           # ISO 8601
    page_url: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d


# ---------------------------------------------------------------------------
# CDP 注入脚本 — 在浏览器端运行
# ---------------------------------------------------------------------------

INJECTION_SCRIPT = r"""
// ===== 浏览器端错误收集器 =====
(() => {
    if (window.__browser_monitor_injected__) return;
    window.__browser_monitor_injected__ = true;
    const errors = [];

    function pushError(category, severity, message, source, line, column, stack, ctx) {
        errors.push({
            category, severity, message: String(message).slice(0, 500),
            source: source || '', line: line || 0, column: column || 0,
            stack: (stack || '').slice(0, 2000),
            timestamp: new Date().toISOString(),
            pageUrl: location.href,
            context: Object.assign({
                userAgent: navigator.userAgent,
                viewport: `${window.innerWidth}x${window.innerHeight}`,
            }, ctx || {})
        });
    }

    // 1) JavaScript 运行时错误
    const _origOnerror = window.onerror;
    window.onerror = function(msg, src, line, col, err) {
        pushError(
            'js_runtime', 'critical', String(msg),
            String(src || ''), Number(line) || 0, Number(col) || 0,
            err ? (err.stack || '') : '', null
        );
        if (_origOnerror) return _origOnerror.apply(this, arguments);
        return false;
    };

    // 2) 未处理 Promise 拒绝
    window.addEventListener('unhandledrejection', function(evt) {
        const reason = evt.reason;
        pushError(
            'js_unhandled_rejection', 'high',
            reason instanceof Error ? reason.message : String(reason),
            '', 0, 0,
            reason instanceof Error ? (reason.stack || '') : '',
            {}
        );
    });

    // 3) console.error 拦截
    const origConsoleError = console.error;
    console.error = function(...args) {
        origConsoleError.apply(console, args);
        const msg = args.map(a => {
            try { return typeof a === 'object' ? JSON.stringify(a) : String(a); }
            catch(_) { return String(a); }
        }).join(' ');
        pushError('console_error', 'medium', msg, '', 0, 0, '', {});
    };

    // 4) 资源加载失败 (img, script, link, iframe)
    window.addEventListener('error', function(evt) {
        if (evt.target === window) return; // window.onerror 已处理
        const tag = (evt.target && evt.target.tagName || '').toLowerCase();
        const src = evt.target && (evt.target.src || evt.target.href || '');
        if (tag && src) {
            pushError(
                'resource_load', 'medium',
                `资源加载失败: <${tag}> src="${src}"`,
                src, 0, 0, '', { tagName: tag }
            );
        }
    }, true); // 捕获阶段

    // 5) 安全策略违规 (CSP)
    if (window.SecurityPolicyViolationEvent) {
        window.addEventListener('securitypolicyviolation', function(evt) {
            pushError(
                'security', 'high',
                `CSP 违规: ${evt.violatedDirective} — ${evt.blockedURI}`,
                evt.sourceFile || '', evt.lineNumber || 0, evt.columnNumber || 0,
                '', { blockedURI: evt.blockedURI, violatedDirective: evt.violatedDirective }
            );
        });
    }

    // 暴露读取接口
    window.__collectErrors = () => errors.splice(0, errors.length);
})();
"""


# ---------------------------------------------------------------------------
# 核心监控引擎
# ---------------------------------------------------------------------------

class BrowserErrorMonitor:
    """
    启动 Edge 浏览器 → 注入错误收集脚本 → 导航目标页面 →
    等待页面加载 → 收集所有错误 → 生成报告
    """

    def __init__(
        self,
        headless: bool = False,
        timeout_ms: int = 30_000,
        wait_after_load_ms: int = 3_000,
    ):
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._wait_after_load_ms = wait_after_load_ms
        self._errors: list[CapturedError] = []

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def monitor_url(self, url: str) -> list[CapturedError]:
        """监控单个 URL，返回捕获的全部错误"""
        from playwright.async_api import async_playwright

        self._errors.clear()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self._headless,
                channel="msedge",                           # ← 使用 Microsoft Edge
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
                ),
            )

            # 监听网络响应状态
            page = await context.new_page()
            self._attach_network_listener(page)

            # 注入错误收集脚本
            await page.add_init_script(INJECTION_SCRIPT)

            page.on("pageerror", self._on_page_error)

            # 导航
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            except Exception as exc:
                self._record_error(
                    ErrorCategory.NETWORK_FAILURE,
                    f"页面导航失败: {exc}",
                    source=url,
                    context={"navigation_error": str(exc)},
                )

            # 等待后续异步错误
            await page.wait_for_timeout(self._wait_after_load_ms)

            # 提取注入脚本收集的错误
            injected_errors: list[dict] = await page.evaluate("window.__collectErrors()")
            for e in injected_errors:
                self._record_injected_error(e)

            await browser.close()

        return list(self._errors)

    async def monitor_crawl(
        self, start_url: str, max_depth: int = 3
    ) -> list[CapturedError]:
        """
        广度优先爬取，监控起始页面及其可达子页面
        """
        from playwright.async_api import async_playwright

        self._errors.clear()
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(start_url, 0)]
        base_origin = _extract_origin(start_url)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self._headless,
                channel="msedge",
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(viewport={"width": 1440, "height": 900})

            while queue:
                url, depth = queue.pop(0)
                if url in visited or depth > max_depth:
                    continue
                visited.add(url)

                page = await context.new_page()
                await page.add_init_script(INJECTION_SCRIPT)
                page.on("pageerror", self._on_page_error)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                except Exception as exc:
                    self._record_error(
                        ErrorCategory.NETWORK_FAILURE,
                        f"页面导航失败: {exc}",
                        source=url, context={"navigation_error": str(exc)},
                    )
                    await page.close()
                    continue

                await page.wait_for_timeout(self._wait_after_load_ms)
                injected = await page.evaluate("window.__collectErrors()")
                for e in injected:
                    self._record_injected_error(e)

                # 收集同源链接供后续爬取
                links: list[str] = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href).filter(h => h.startsWith('http'));
                }""")
                for link in links:
                    if _extract_origin(link) == base_origin and link not in visited:
                        queue.append((link, depth + 1))

                await page.close()

            await browser.close()

        return list(self._errors)

    # ------------------------------------------------------------------
    # 网络监听
    # ------------------------------------------------------------------

    def _attach_network_listener(self, page):
        """监听所有网络响应，记录 4xx/5xx 及请求失败"""

        async def on_response(resp):
            status = resp.status
            if status >= 400:
                self._record_error(
                    ErrorCategory.NETWORK_FAILURE,
                    f"HTTP {status}: {resp.request.method} {resp.url}",
                    source=resp.url,
                    context={
                        "status_code": status,
                        "method": resp.request.method,
                        "url": resp.url,
                    },
                )

        async def on_request_failed(request):
            self._record_error(
                ErrorCategory.NETWORK_FAILURE,
                f"请求失败: {request.failure} | {request.method} {request.url}",
                source=request.url,
                context={"failure": request.failure, "method": request.method},
            )

        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)

    # ------------------------------------------------------------------
    # 错误记录处理
    # ------------------------------------------------------------------

    def _on_page_error(self, err):
        """接收 Playwright 层面的 pageerror 事件"""
        self._record_error(
            ErrorCategory.JS_RUNTIME,
            err.message if hasattr(err, "message") else str(err),
            source=getattr(err, "page", ""),
            stack=getattr(err, "stack", "") if hasattr(err, "stack") else "",
        )

    def _record_injected_error(self, raw: dict):
        """将注入脚本收集的原始数据转为 CapturedError"""
        cat = raw.get("category", "other")
        try:
            category = ErrorCategory(cat)
        except ValueError:
            category = ErrorCategory.OTHER

        self._errors.append(CapturedError(
            category=category,
            severity=CATEGORY_TO_SEVERITY.get(category, ErrorSeverity.LOW),
            message=raw.get("message", ""),
            source=raw.get("source", ""),
            line=raw.get("line", 0),
            column=raw.get("column", 0),
            stack=raw.get("stack", ""),
            timestamp=raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
            page_url=raw.get("pageUrl", ""),
            context=raw.get("context", {}),
        ))

    def _record_error(
        self,
        category: ErrorCategory,
        message: str,
        source: str = "",
        line: int = 0,
        column: int = 0,
        stack: str = "",
        context: dict | None = None,
    ):
        self._errors.append(CapturedError(
            category=category,
            severity=CATEGORY_TO_SEVERITY.get(category, ErrorSeverity.LOW),
            message=message,
            source=source,
            line=line,
            column=column,
            stack=stack,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context=context or {},
        ))


# ---------------------------------------------------------------------------
# 报告生成器
# ---------------------------------------------------------------------------

class ErrorReporter:
    """将错误列表转换为结构化报告"""

    @staticmethod
    def summarize(errors: list[CapturedError]) -> dict:
        """生成统计数据"""
        by_category: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        for e in errors:
            by_category[e.category.value] += 1
            by_severity[e.severity.value] += 1

        return {
            "total": len(errors),
            "by_category": dict(by_category),
            "by_severity": dict(by_severity),
        }

    @staticmethod
    def to_json(errors: list[CapturedError], output_path: str | Path) -> Path:
        """输出 JSON 报告"""
        out = Path(output_path)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool": "browser_error_monitor",
            "summary": ErrorReporter.summarize(errors),
            "errors": [e.to_dict() for e in errors],
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    @staticmethod
    def to_markdown(errors: list[CapturedError], output_path: str | Path) -> Path:
        """输出 Markdown 报告"""
        out = Path(output_path)
        summary = ErrorReporter.summarize(errors)
        lines = [
            "# 🛡️ 前端错误监控报告",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**错误总数**: {summary['total']}",
            "",
            "## 📊 统计概览",
            "",
            "| 严重等级 | 数量 |",
            "|----------|------|",
        ]
        for sev in ("critical", "high", "medium", "low", "info"):
            cnt = summary["by_severity"].get(sev, 0)
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "🔵"}.get(sev, "")
            lines.append(f"| {emoji} {sev} | {cnt} |")

        lines += [
            "",
            "| 错误类别 | 数量 |",
            "|----------|------|",
        ]
        for cat, cnt in sorted(summary["by_category"].items()):
            lines.append(f"| {cat} | {cnt} |")

        lines += ["", "---", "", "## 📋 错误详情", ""]
        for i, e in enumerate(errors, 1):
            lines += [
                f"### {i}. [{e.severity.value.upper()}] {e.category.value}",
                f"- **消息**: {e.message}",
                f"- **来源**: {e.source}",
                f"- **位置**: {e.source}:{e.line}:{e.column}" if e.line else "",
                f"- **时间**: {e.timestamp}",
                f"- **页面**: {e.page_url}",
            ]
            if e.stack:
                lines.append(f"\n```\n{e.stack[:1000]}\n```\n")
            if e.context:
                lines.append(f"**上下文**: `{json.dumps(e.context, ensure_ascii=False)}`")
            lines.append("")

        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    @staticmethod
    def to_html(errors: list[CapturedError], output_path: str | Path) -> Path:
        """输出 HTML 可视化报告"""
        out = Path(output_path)
        summary = ErrorReporter.summarize(errors)

        def sev_color(s: str) -> str:
            return {"critical": "#dc3545", "high": "#fd7e14", "medium": "#ffc107",
                    "low": "#28a745", "info": "#17a2b8"}.get(s, "#6c757d")

        rows = ""
        for e in errors:
            rows += f"""<tr>
                <td><span style="background:{sev_color(e.severity.value)};color:#fff;padding:2px 8px;border-radius:4px">{e.severity.value}</span></td>
                <td>{e.category.value}</td>
                <td>{_escape_html(e.message[:200])}</td>
                <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{_escape_html(e.source)}">{_escape_html(e.source[:80])}</td>
                <td>{e.line}:{e.column}</td>
                <td>{e.timestamp[:19]}</td>
            </tr>"""

        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>前端错误监控报告</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:1400px;margin:0 auto;padding:24px;background:#f5f5f5}}
.card{{background:#fff;border-radius:8px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.stats{{display:flex;gap:16px;flex-wrap:wrap}}
.stat{{flex:1;min-width:120px;text-align:center;padding:16px;border-radius:8px;color:#fff}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f8f9fa;position:sticky;top:0}}tr:hover{{background:#f8f9fa}}
</style></head><body>
<h1>🛡️ 前端错误监控报告</h1>
<p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 错误总数: <strong>{summary['total']}</strong></p>
<div class="stats">
{"".join(f'<div class="stat" style="background:{sev_color(k)}">{k}<br><strong>{v}</strong></div>' for k, v in summary["by_severity"].items())}
</div>
<div class="card"><h2>错误明细</h2><div style="max-height:70vh;overflow:auto"><table><thead><tr>
<th>严重等级</th><th>类别</th><th>消息</th><th>来源</th><th>位置</th><th>时间</th></tr></thead><tbody>{rows}</tbody></table></div></div>
</body></html>"""
        out.write_text(html, encoding="utf-8")
        return out


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _extract_origin(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="前端错误自动监控系统 — 基于 Playwright + Microsoft Edge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python browser_monitor.py http://localhost:8503
  python browser_monitor.py http://localhost:8503 --depth 3
  python browser_monitor.py http://localhost:8503 --headless --report-dir ./reports
        """,
    )
    parser.add_argument("url", help="目标页面 URL")
    parser.add_argument("--depth", type=int, default=0,
                        help="爬取深度（0=仅当前页，>0=爬取同源子页面）")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器窗口）")
    parser.add_argument("--timeout", type=int, default=30_000, help="页面加载超时(ms)")
    parser.add_argument("--wait", type=int, default=3_000, help="页面加载后等待时间(ms)")
    parser.add_argument("--report-dir", default=".", help="报告输出目录")
    args = parser.parse_args()

    monitor = BrowserErrorMonitor(
        headless=args.headless,
        timeout_ms=args.timeout,
        wait_after_load_ms=args.wait,
    )

    print(f"🔍 开始监控: {args.url}")
    if args.depth > 0:
        errors = await monitor.monitor_crawl(args.url, max_depth=args.depth)
    else:
        errors = await monitor.monitor_url(args.url)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    reporter = ErrorReporter()
    json_path = reporter.to_json(errors, report_dir / f"errors_{ts}.json")
    md_path = reporter.to_markdown(errors, report_dir / f"errors_{ts}.md")
    html_path = reporter.to_html(errors, report_dir / f"errors_{ts}.html")

    summary = reporter.summarize(errors)
    print(f"\n✅ 监控完成")
    print(f"   错误总数: {summary['total']}")
    for cat, cnt in summary["by_category"].items():
        print(f"     {cat}: {cnt}")
    print(f"\n📄 报告已生成:")
    print(f"   JSON : {json_path}")
    print(f"   MD   : {md_path}")
    print(f"   HTML : {html_path}")

    # 非零退出码方便 CI 集成
    if errors:
        critical_count = summary["by_severity"].get("critical", 0) + summary["by_severity"].get("high", 0)
        if critical_count > 0:
            print(f"\n⚠️  检测到 {critical_count} 个严重/高危错误")
            sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
