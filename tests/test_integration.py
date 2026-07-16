"""集成测试 — 端到端验证旅行规划完整流程"""

import pytest
from pathlib import Path


@pytest.mark.integration
class TestEndToEnd:
    """端到端集成测试"""

    def test_config_loads(self):
        """配置加载测试"""
        from config import CONFIG
        assert CONFIG.model_name == "qwen3-max"
        assert "poi" in CONFIG.tool_domains
        assert "weather" in CONFIG.tool_domains
        assert "route" in CONFIG.tool_domains

    def test_mcp_returns_tools(self):
        """MCP 返回假数据工具（离线测试）"""
        import asyncio
        from mcp_client import McpClientManager

        async def check():
            mcp = McpClientManager()
            tools = await mcp.get_all_tools()
            assert len(tools) == 5
            names = {t.name for t in tools}
            assert "maps_weather" in names
            assert "maps_text_search" in names
            return True

        assert asyncio.run(check())

    def test_prompts_load(self):
        """提示词加载"""
        import prompts
        assert len(prompts.PLANNER_AGENT_PROMPT) > 100
        assert "JSON" in prompts.PLANNER_AGENT_PROMPT
        assert len(prompts.WEATHER_AGENT_PROMPT) > 10
        assert len(prompts.HOTEL_AGENT_PROMPT) > 10
        assert len(prompts.ATTRACTION_AGENT_PROMPT) > 10

    def test_render_parse_plan_valid(self):
        """解析合法 JSON"""
        from render import parse_plan
        result = parse_plan('''{"city":"长沙","days":[]}''')
        assert result is not None
        assert result["city"] == "长沙"

    def test_render_parse_plan_invalid(self):
        """解析非法 JSON 返回 None"""
        from render import parse_plan
        result = parse_plan("这不是合法的 JSON")
        assert result is None

    def test_render_parse_plan_embedded(self):
        """解析嵌入在文本中的 JSON"""
        from render import parse_plan
        text = "行程规划结果如下：\n```json\n{\"city\":\"北京\"}\n```\n希望对你有帮助。"
        result = parse_plan(text)
        assert result is not None
        assert result["city"] == "北京"

    def test_weather_icon_mapping(self):
        """天气图标映射"""
        from render import _weather_icon
        assert _weather_icon("晴") == "☀️"
        assert _weather_icon("小雨") == "🌧️"
        assert _weather_icon("雪") == "❄️"
        assert _weather_icon("未知天气") == "🌡️"

    def test_build_prompt(self):
        """测试 prompt 构建（需要模拟 Streamlit date）"""
        from app import build_prompt
        import datetime

        result = build_prompt(
            city="长沙",
            start_date=datetime.date(2026, 5, 21),
            end_date=datetime.date(2026, 5, 23),
            transport=["公共交通", "步行"],
            hotel_type="经济型",
            preferences=["历史文化", "美食"],
            extra="不要太累",
        )
        assert "长沙" in result
        assert "3" in result  # 3天
        assert "经济型" in result
        assert "历史文化" in result
        assert "不要太累" in result

    def test_auth_token_flow(self):
        """完整的 Token 生命周期"""
        from auth.token import TokenManager, TokenConfig
        from auth.exceptions import TokenTypeError, TokenRevokedError, AuthError

        config = TokenConfig(
            secret_key="integration-test-key",
            access_token_expire_minutes=30,
            refresh_token_expire_days=1,
        )
        mgr = TokenManager(config)

        # 1. 生成
        pair = mgr.create_token_pair("user_001", {"roles": ["user"]})
        assert pair.access_token != pair.refresh_token

        # 2. 校验
        payload = mgr.validate_access_token(pair.access_token)
        assert payload["sub"] == "user_001"

        # 3. 类型隔离
        with pytest.raises(TokenTypeError):
            mgr.validate_access_token(pair.refresh_token)

        # 4. 刷新
        new_pair = mgr.refresh(pair.refresh_token)
        assert new_pair.access_token != pair.access_token

        # 5. 撤销
        mgr.revoke(new_pair.access_token)
        with pytest.raises(TokenRevokedError):
            mgr.validate_access_token(new_pair.access_token)

    def test_agent_loop_metrics_flow(self):
        """AgentLoop 指标采集完整流程"""
        from agent_loop.metrics import MetricsCollector

        collector = MetricsCollector(task="integration_test")
        collector.start()

        # 模拟 Agent 循环
        steps = [
            ("agent_reason", 0, 20, "", ""),
            ("tool_call", 0, 5, "maps_weather", ""),
            ("agent_reason", 0, 30, "", ""),
            ("tool_call", 0, 8, "maps_text_search", ""),
            ("agent_reason", 0, 50, "", ""),
        ]
        for step_name, inp, out, tool, err in steps:
            collector.record_step_start(step_name)
            collector.record_step_end(
                step_name, input_tokens=inp, output_tokens=out,
                tool_name=tool, error=err,
            )

        summary = collector.summarize()
        assert summary.total_iterations == 5
        assert summary.total_tool_calls == 2
        assert summary.total_errors == 0
        assert summary.total_output_tokens == 113
        assert 0 <= summary.efficiency_score <= 100
