"""
配置中心 —— 统一管理环境变量、LLM 实例、MCP 连接参数。
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
from langchain_community.chat_models.tongyi import ChatTongyi

load_dotenv()

# ========== 修复 langchain_community ChatTongyi 流式 tool_calls 的 KeyError ==========
# 上游 bug: subtract_client_response 访问 prev_function["name"] / ["arguments"]
# 前没有检查 key 是否存在。流式首个 tool_call chunk 可能不含这些 key。


def _patched_subtract(self, resp, prev_resp):
    import json

    resp_copy = json.loads(json.dumps(resp))
    message = resp_copy["output"]["choices"][0]["message"]
    prev_message = json.loads(json.dumps(prev_resp))["output"]["choices"][0]["message"]

    message["content"] = message["content"].replace(
        prev_message.get("content", "") or "", ""
    )

    if message.get("tool_calls") and prev_message.get("tool_calls"):
        for index, tool_call in enumerate(message["tool_calls"]):
            function = tool_call["function"]
            prev_function = prev_message["tool_calls"][index]["function"]

            if "name" in function and "name" in prev_function:
                function["name"] = function["name"].replace(prev_function["name"], "")
            if "arguments" in function and "arguments" in prev_function:
                function["arguments"] = function["arguments"].replace(
                    prev_function["arguments"], ""
                )

    return resp_copy


ChatTongyi.subtract_client_response = _patched_subtract
# ========== 修复结束 ==========


@dataclass
class Config:
    """全局配置，单例语义 —— 模块级 CONFIG 实例"""

    # API 密钥
    api_key: str = field(
        default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", "")
    )

    # LLM
    model_name: str = "qwen3-max"
    temperature: float = 0.7

    # MCP 连接（阿里百炼高德地图）
    mcp_transport: str = "http"
    mcp_url: str = "https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/mcp"

    # 工具领域映射
    tool_domains: dict = field(default_factory=lambda: {
        "poi":     ["maps_text_search", "maps_search_detail"],
        "weather": ["maps_weather"],
        "route":   [
            "maps_direction_walking_by_address",
            "maps_direction_driving_by_address",
            "maps_direction_transit_integrated_by_address",
        ],
    })

    def __post_init__(self):
        # 临时注释掉，用于演示模式（不调用真实API）
        # if not self.api_key:
        #     raise ValueError("请配置 DASHSCOPE_API_KEY")
        pass

    # 创建模型实例对象
    def create_llm(self) -> ChatTongyi:
        return ChatTongyi(
            model=self.model_name,
            api_key=self.api_key,
            temperature=self.temperature,
            streaming=True,          # ← 启用水龙头，流式输出最远走到这里
        )


CONFIG = Config()
