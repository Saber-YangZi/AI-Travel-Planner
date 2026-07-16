# AI智能旅行规划工具 AI-Travel-Planner

基于 **Multi-Agent 架构**的智能旅行规划系统，集成高德地图 MCP 服务与阿里百炼大模型，输入目的地和偏好即可自动生成完整的旅行方案。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/LangChain-0.1+-green?logo=langchain" alt="LangChain">
  <img src="https://img.shields.io/badge/Streamlit-1.0+-red?logo=streamlit" alt="Streamlit">
  <img src="https://img.shields.io/badge/LLM-通义千问_qwen3--max-orange" alt="LLM">
  <img src="https://img.shields.io/badge/Test-65+_cases-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/License-MIT-lightgrey" alt="License">
</p>

---

## 目录

- [项目概览](#项目概览)
- [系统架构](#系统架构)
- [核心特性](#核心特性)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [核心模块](#核心模块)
- [AgentLoop 性能优化](#agentloop-性能优化)
- [JWT 认证体系](#jwt-认证体系)
- [测试覆盖](#测试覆盖)
- [技术栈](#技术栈)
- [设计模式](#设计模式)

---

## 项目概览

用户用自然语言描述旅行需求，系统自动调用高德地图 API 查询天气、搜索景点酒店、规划路线，最终输出结构化的旅行计划 JSON + 可视化页面 + 可下载 Markdown。

**核心能力：**

| 能力 | 说明 |
|------|------|
| 🌤️ 天气查询 | 通过高德 MCP `maps_weather` 获取目的地实时天气预报 |
| 🏛️ 景点推荐 | `maps_text_search` 按城市+偏好搜索 POI，AI 智能筛选 |
| 🏨 酒店推荐 | 统一 POI 搜索，按位置+类型推荐附近酒店 |
| 🗺️ 路线规划 | 支持步行/驾车/公交三种方式的路径规划 |
| 📊 预算汇总 | 自动汇总门票、酒店、餐饮、交通各项费用 |
| 📥 导出下载 | Web 界面一键下载 Markdown 旅行计划 |
| 🔐 JWT 认证 | 双令牌机制，支持 API 访问控制和会话管理 |
| 📈 性能监控 | AgentLoop 指标采集、效率评分、可视化报告 |

**运行方式：**

```bash
# CLI 模式
python Agent.py

# Web 模式（Streamlit 图形界面）
streamlit run app.py

# 运行测试
python -m pytest tests/ -v
```

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        入口层                                 │
│   Agent.py (CLI)              app.py (Streamlit Web)          │
│   browser_monitor.py (前端错误检测)                            │
└─────────────────────┬────────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────────┐
│                      核心 Agent 层                            │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐   │
│   │              TripPlanner (总控 Agent)                 │   │
│   │   system_prompt: PLANNER_AGENT_PROMPT                │   │
│   │   tools: [search_hotel, search_attraction,           │   │
│   │           query_weather, route_tools...]             │   │
│   └───┬──────────────┬──────────────┬────────────────────┘   │
│       │              │              │                        │
│       ▼              ▼              ▼                        │
│   ┌──────┐  ┌───────┐  ┌─────────┐  ┌──────────────────┐    │
│   │Hotel │  │Attrc  │  │Weather  │  │  MCP 路线工具     │    │
│   │Agent │  │Agent  │  │Agent    │  │  (直接调用)       │    │
│   └──┬───┘  └──┬───┘  └──┬──────┘  └────────┬─────────┘    │
│      │         │          │                   │              │
│      └────┬────┘     ┌────┘                   │              │
│           ▼          ▼                        │              │
│   ┌───────────────────────────────────────────▼──────────┐   │
│   │            McpClientManager (单例)                     │   │
│   │   transport: http → 阿里百炼高德地图 MCP 服务          │   │
│   │   工具按领域分组: poi / weather / route               │   │
│   └──────────────────────┬───────────────────────────────┘   │
└──────────────────────────┼────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────┐
│                    增强模块                                    │
│                                                              │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐     │
│   │ agent_loop/  │ │    auth/     │ │     utils/       │     │
│   │ 性能监控      │ │  JWT 认证    │ │  日志 & 监控     │     │
│   │ 循环保护      │ │  中间件      │ │                  │     │
│   │ 可视化报告    │ │  Token管理   │ │                  │     │
│   └──────────────┘ └──────────────┘ └──────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

**架构特点：**

1. **三层 Agent 嵌套**：Planner (总控) → SpecialistAgent (领域) → MCP Tools (底层 API)
2. **子 Agent 作为 Tool**：领域专家 Agent 被 `@tool` 装饰器包装，对 Planner 透明
3. **生产级增强**：AgentLoop 性能监控 + JWT 认证 + 前端错误检测

---

## 核心特性

### 1. Multi-Agent 协同

- **Planner Agent**：总控编排，理解用户意图，调度子 Agent，整合结果输出 JSON
- **SpecialistAgent**：领域专家，持有领域专属工具集，遵循最小权限原则
- **MCP 工具层**：通过 MCP 协议连接高德地图 15 个 API 工具

### 2. AgentLoop 优化体系

- **指标采集**：TTFT、TTI、Token 消耗、工具调用效率、错误率
- **循环保护**：三重防护（最大迭代 50 次 / 超时 120 秒 / 最大错误 5 次）
- **指数退避重试**：`delay = base × 2^attempt`，最大化瞬时故障恢复成功率
- **工具降级**：MCP 不可用时返回兜底数据，保证系统不崩溃
- **可视化**：终端仪表板 + HTML 性能报告 + CSV 数据导出

### 3. JWT 认证体系

- 双令牌机制（Access Token 15min + Refresh Token 7day）
- jti 唯一 ID 防重放攻击
- `@require_auth` 中间件，即插即用

### 4. 工程化保障

- 65+ 单元/集成测试，覆盖核心模块
- 模块化设计，职责清晰
- `.gitignore` 排除敏感信息，安全合规

---

## 项目结构

```
AI-Travel-Planner/
├── Agent.py                 # CLI 入口
├── app.py                   # Streamlit Web 入口
├── config.py                # 配置中心：API Key + Monkey-Patch
├── prompts.py               # 5个 System Prompt 集中管理
├── render.py                # 渲染引擎：JSON 解析 + CLI 格式化
├── mcp_client.py            # MCP 客户端管理器（单例模式）
├── mcp_server.py            # MCP 服务端工具定义
├── amap_tools.py            # 高德地图工具函数
├── browser_monitor.py       # 前端运行时错误检测 & 报告
├── voice_draw.py            # 语音输入 & 画图功能
├── requirements.txt         # 依赖清单
├── pytest.ini               # 测试配置
├── .gitignore               # Git 忽略规则
│
├── agents/                  # Agent 层
│   ├── planner.py           # 总控 Agent：编排 + 流式输出
│   └── specialist.py        # 领域专家 Agent：POI/天气/酒店
│
├── agent_loop/              # AgentLoop 优化模块
│   ├── metrics.py           # 性能指标采集 & 效率评分
│   ├── optimizer.py         # 循环控制 & 异常恢复
│   └── visualizer.py        # 可视化（终端/HTML/CSV）
│
├── auth/                    # 认证模块
│   ├── token.py             # JWT 生成 & 验证
│   ├── middleware.py         # 认证中间件
│   └── exceptions.py        # 异常定义
│
├── utils/                   # 工具模块
│   └── logger.py            # 日志 & 运行时监控
│
└── tests/                   # 测试套件（65+ cases）
    ├── test_agent_loop.py   # AgentLoop 17 项测试
    ├── test_auth.py         # 认证模块 20+ 测试
    └── test_integration.py  # 集成测试
```

---

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

在项目根目录创建 `.env` 文件：

```env
# 阿里百炼 API Key（必填）
DASHSCOPE_API_KEY=sk-your-dashscope-key
# 高德地图 API Key（可选，MCP 服务已封装）
AMAP_API_KEY=
```

> 阿里百炼 API Key 申请：https://dashscope.console.aliyun.com/

### 3. 运行

```bash
# Web 模式（推荐）
streamlit run app.py

# CLI 模式
python Agent.py
```

### 4. 使用

**Web 模式**：在侧边栏填写目的地、日期、偏好，点击「开始规划」

---

## 核心模块

### config.py — 配置中心 + Monkey-Patch

- `@dataclass` 定义 `Config` 类，模块级 `CONFIG` 实例作为单例
- `tool_domains` 字典实现工具按领域分组（poi/weather/route）
- **Monkey-Patch**：修复 `ChatTongyi.subtract_client_response()` 的流式 tool_calls KeyError bug

### agents/planner.py — 总控编排

TripPlanner 完成四阶段构建：

1. 按领域加载 MCP 工具
2. 创建 3 个 SpecialistAgent
3. 将子 Agent 包装为 `@tool` 函数
4. 创建总控 Agent（含完整工具集 + 系统提示词）

流式输出时过滤子 Agent 内部 `[TOOL_CALL:...]` 标记，保证用户看到纯净内容。

### agents/specialist.py — 领域专家

每个 SpecialistAgent 是独立的 LangGraph Agent，拥有专属 system_prompt 和受限工具集（最小权限原则）。支持流式和非流式两种调用模式。

### mcp_client.py — MCP 连接管理

单例模式管理阿里百炼高德地图 MCP 连接，懒加载 + 工具缓存，按领域分发工具子集。

---

## AgentLoop 性能优化

| 模块 | 核心职责 | 关键实现 |
|------|---------|---------|
| `agent_loop/metrics.py` | 性能指标采集 | TTFT 追踪、迭代耗时、Token 统计、效率评分 (0-100)、智能告警 |
| `agent_loop/optimizer.py` | 循环控制与恢复 | 最大迭代 (50)、超时保护 (120s)、错误上限 (5)、指数退避重试、工具降级 |
| `agent_loop/visualizer.py` | 结果可视化 | ASCII 终端仪表板、HTML 性能报告（表格+进度条）、CSV 原始数据导出 |

**效率评分算法**：基准 100 分，根据迭代次数、错误次数、总耗时进行综合扣分，同时检查是否未完成完整流程。

**优化建议自动生成**：迭代过多 → 建议缓存 / 单轮耗时过长 → 建议并行 / 有错误 → 建议重试。

---

## JWT 认证体系

| 模块 | 职责 |
|------|------|
| `auth/token.py` | JWT 生成/验证，双令牌机制 (Access + Refresh) |
| `auth/middleware.py` | `@require_auth` 装饰器，即插即用 |
| `auth/exceptions.py` | 认证异常定义（过期/无效/权限不足） |

**安全特性**：jti 唯一 ID 防重放、HS256 签名、nbf/exp 时效控制、自定义 claims。

---

## 测试覆盖

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行 AgentLoop 测试
python -m pytest tests/test_agent_loop.py -v

# 运行认证测试
python -m pytest tests/test_auth.py -v

# 运行集成测试
python -m pytest tests/test_integration.py -v -m integration
```

**测试分布：**

| 测试文件 | 覆盖模块 | 用例数 |
|---------|---------|--------|
| `test_agent_loop.py` | MetricsCollector / LoopOptimizer / LoopVisualizer | 17 |
| `test_auth.py` | TokenManager / Middleware / Exceptions | 20+ |
| `test_integration.py` | 端到端流程验证 | 若干 |

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| LLM | 通义千问 qwen3-max (阿里百炼) | 推理与生成 |
| Agent 框架 | LangChain + LangGraph | Agent 创建、工具编排、ReAct 循环 |
| LLM 适配 | langchain_community.ChatTongyi | 通义千问的 LangChain 适配器 |
| MCP 协议 | langchain_mcp_adapters | 连接高德地图 MCP 服务 |
| Web 界面 | Streamlit | 声明式 Web UI |
| 认证 | PyJWT + HS256 | JWT 令牌签发与验证 |
| 配置 | python-dotenv | .env 环境变量 |
| 测试 | pytest | 单元 + 集成测试 |
| 运行环境 | Python 3.12+ | asyncio 异步、类型注解 |

---

## 设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **单例模式** | `McpClientManager` | `__new__` + `_initialized` 双重保护 |
| **工厂方法** | `Config.create_llm()` | 统一 LLM 实例创建 |
| **门面模式** | `TripPlanner` | 隐藏内部多 Agent 复杂性 |
| **装饰器模式** | `@tool` 包装子 Agent / `@require_auth` | 接口适配 / 认证拦截 |
| **策略模式** | `tool_domains` 字典 / `LoopConfig` | 工具分组 / 循环配置可替换 |
| **适配器模式** | `render.py` | JSON → CLI / Streamlit 双视图 |
| **观察者模式** | `MetricsCollector` / `LoopState` | 运行时状态跟踪 |

---

## Bug 修复记录

### ChatTongyi 流式 tool_calls KeyError

- **现象**：`KeyError: 'name'` at `tongyi.py:606`
- **根因**：`subtract_client_response()` 未对 `prev_function` 做 key 存在性检查
- **修复**：`config.py` Monkey-patch，添加 `"name" in prev_function` 守卫

### 子 Agent TOOL_CALL 标记泄漏

- **现象**：用户看到 `[TOOL_CALL:amap_maps_xxx:...]` 内部标记
- **修复**：`planner.py` stream() 中用正则过滤

### 天气卡片暗色主题文字不可见

- **修复**：CSS 显式设置 `color: #1a1a1a`

---

## 许可证

MIT License
