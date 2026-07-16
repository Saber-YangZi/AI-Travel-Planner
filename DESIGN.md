# 智能旅行助手 — 技术设计文档

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    入口层                                    │
│   Agent.py (CLI)          app.py (Streamlit Web)             │
└─────────────────┬────────────────────────────────────────────┘
                  │
┌─────────────────┴────────────────────────────────────────────┐
│                    核心层                                    │
│   config.py     →  ChatTongyi (qwen3-max, 带Monkey-Patch)    │
│   prompts.py    →  4组System Prompt                          │
│                                                              │
│   agents/planner.py    → TripPlanner (总控Agent)             │
│   agents/specialist.py → SpecialistAgent (领域Agent)         │
│                                                              │
│   mcp_client.py → McpClientManager (单例, MCP工具连接)       │
│   render.py     → parse_plan / format_plan_cli               │
└─────────────────┬────────────────────────────────────────────┘
                  │
┌─────────────────┴────────────────────────────────────────────┐
│                    增强模块                                  │
│   auth/                  → JWT认证                           │
│   agent_loop/            → 循环优化+性能监控                 │
│   utils/                 → 日志+运行时监控                   │
│   browser_monitor.py     → 前端错误检测                      │
└──────────────────────────────────────────────────────────────┘
                  │
┌─────────────────┴────────────────────────────────────────────┐
│                 测试 & CI                                     │
│   tests/test_auth.py          → 38 单元测试                  │
│   tests/test_agent_loop.py    → 17 单元测试                  │
│   tests/test_integration.py   → 10 集成测试                  │
│   pytest.ini                  → 测试配置                     │
└──────────────────────────────────────────────────────────────┘
```

---

## 模块详解

### 1. config.py — 配置中心
- **模式**: @dataclass + 模块级单例 `CONFIG`
- **LLM**: ChatTongyi(qwen3-max), streaming=True
- **MCP端点**: 阿里百炼高德地图MCP Server
- **Monkey-Patch**: `_patched_subtract` 修复流式tool_calls KeyError

### 2. agents/planner.py — TripPlanner
- **职责**: 任务拆解 → 工具调度 → 结果整合
- **核心方法**:
  - `build()`: 加载MCP工具 → 创建3个SpecialistAgent → @tool包装 → create_agent
  - `stream()`: 流式输出 + 工具调用状态监听
  - `invoke()`: 非流式调用
- **设计模式**: 组合模式（Planner包含多个子Agent）

### 3. agents/specialist.py — SpecialistAgent
- **职责**: 封装特定领域的LLM推理能力
- **特点**: 延迟初始化（build()幂等），统一的invoke/stream接口

### 4. mcp_client.py — McpClientManager
- **模式**: 单例模式
- **当前状态**: 返回假数据（5个LangChain Tool对象）
- **领域划分**: poi/weather/route 三个domain

### 5. render.py — 渲染工具
- `parse_plan()`: 从混合文本提取JSON（find/rfind + json.loads）
- `_weather_icon()`: 8种天气→emoji映射
- `format_plan_cli()`: JSON→CLI格式化输出

---

## auth/ — JWT 认证模块

### 组件
| 文件 | 职责 |
|------|------|
| `token.py` | TokenManager: 生成/校验/刷新/撤销 |
| `exceptions.py` | 5种认证异常（过期/无效/撤销/缺失/类型错误） |
| `middleware.py` | Bearer提取 + validate_token装饰器 + FastAPI中间件 |

### 安全设计
- **双令牌**: access_token(30min) + refresh_token(7day)
- **防重放**: jti唯一ID + 撤销列表
- **类型隔离**: access与refresh不可混用
- **刷新即撤销**: 刷新时旧refresh_token自动失效
- **完整测试**: 38个用例覆盖生成/校验/过期/签名伪造/类型混用/刷新/撤销

---

## agent_loop/ — Agent循环优化模块

### 组件
| 文件 | 职责 |
|------|------|
| `optimizer.py` | LoopOptimizer: 循环保护 + 重试 + 降级 |
| `metrics.py` | MetricsCollector: 性能指标采集 |
| `visualizer.py` | LoopVisualizer: 仪表板/HTML/CSV/JSON输出 |

### 循环保护机制
```
┌─────────────────┐
│   LoopOptimizer  │
├─────────────────┤
│ max_iterations   │ ← 防止死循环
│ timeout_seconds  │ ← 防止单任务卡死
│ max_errors       │ ← 防止错误雪崩
│ retry_max=3      │ ← 指数退避重试
│ graceful_timeout │ ← 优雅终止
└─────────────────┘
```

---

## 测试策略

### 覆盖率
| 套件 | 用例数 | 类型 | 覆盖模块 |
|------|--------|------|---------|
| test_auth | 38 | 单元 | auth/ |
| test_agent_loop | 17 | 单元 | agent_loop/ |
| test_integration | 10 | 集成 | 全项目 |
| **总计** | **65** | — | — |

### 运行
```bash
pytest tests/ -v                          # 全量测试
pytest tests/ -m unit -v                  # 仅单元测试
pytest tests/ --cov=. --cov-report=html   # 覆盖率报告
```

---

## 依赖清单

```
langchain>=0.3         # Agent框架
langchain-community    # ChatTongyi集成
streamlit              # Web UI
python-dotenv          # 环境变量
pyjwt[crypto]          # JWT认证
pytest, pytest-asyncio # 测试
playwright             # 前端错误监控
```

## 运行方式

```bash
# CLI
python Agent.py

# Web
streamlit run app.py

# 测试
python -m pytest tests/ -v

# 前端监控
python browser_monitor.py http://localhost:8503 --headless
```
