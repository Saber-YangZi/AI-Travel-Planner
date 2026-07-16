# 智能旅行助手 — 面试讲解材料

---

## 一、项目概览（30秒电梯演讲）

> 我开发了一个基于Multi-Agent架构的智能旅行规划系统。
> 核心特点有三：一是"业务拆解先行"的设计思路，将旅行规划拆解为查天气、搜景点、找酒店三个独立任务；
> 二是"三层Agent架构"，Planner总控 + Specialist子Agent + MCP工具层，职责清晰；
> 三是生产级质量保障，配套65个单元/集成测试、JWT认证、AgentLoop性能监控、前端错误自动检测。

---

## 二、核心技术难点攻克

### 难点1：LangChain `create_agent` 流式输出的 KeyError bug

**现象**：流式tool_calls中 `prev_function["name"]` 抛出KeyError，导致Agent无法运行。

**根因**：ChatTongyi的 `subtract_client_response` 方法在流式累积tool_call参数时，
        未对 `prev_resp` 做空值检查。

**解决方案**（`config.py` Line 37-59）：
```python
def _patched_subtract(self, resp, prev_resp):
    # 关键：深拷贝 + 防御性检查
    import copy
    resp = copy.deepcopy(resp)
    # ... 遍历 tool_calls
    if "name" in function and "name" in prev_function:  # 防御性检查
        function["name"] = function["name"].replace(prev_function["name"], "")
```
通过Monkey-Patch修复阿里百炼SDK的bug，保证流式输出稳定性。

---

### 难点2：Multi-Agent 通信协议设计

**问题**：Planner与子Agent之间的信息传递既要结构化，又要避免格式泄漏。

**方案**：
1. **JSON Schema约束**：在PLANNER_AGENT_PROMPT中定义完整输出格式（city/days/weather_info/budget）
2. **泄露过滤**：用正则 `r"\[TOOL_CALL:[^\]]*\]"` 过滤子Agent的内部TOOL_CALL标记
3. **容错解析**：`parse_plan()` 用 `text.find("{")` → `text.rfind("}")` 从混合文本提取JSON

---

### 难点3：工具调用效率优化

**现状**：子Agent每次调用都需重新理解上下文 → 延迟高

**优化策略**：
- 领域工具分离：按POI/Weather/Route分领域加载MCP工具
- 幂等初始化：`build()` 中 `if self._agent is not None: return`
- 并行调用设计：3个子Agent独立构建，可扩展为并发执行

---

### 难点4：LoopOptimizer — 循环保护与恢复

**Agent循环的常见问题**：
- 死循环（LLM不断调用同一个工具）
- 单次调用超时卡死
- 错误积累导致崩溃

**我的方案**（`agent_loop/optimizer.py`）：
| 机制 | 保护对象 | 配置 |
|------|---------|------|
| 最大迭代 | 死循环 | max_iterations=50 |
| 超时保护 | 单任务卡死 | timeout_seconds=120 |
| 错误上限 | 错误雪崩 | max_errors=5 |
| 指数退避重试 | 瞬时故障 | backoff=2.0, max=3次 |
| 工具降级 | MCP不可用 | fallback兜底数据 |

---

## 三、逐行代码讲解 — 核心函数

### `TripPlanner.build()` — Agent组装入口（`agents/planner.py` Line 70-117）

```
async def build(self):
    if self._agent is not None: return     # ① 幂等检查

    poi_tools = await self.mcp.get_tools_for("poi")      # ② 按领域加载MCP工具
    weather_tools = await self.mcp.get_tools_for("weather")
    route_tools = await self.mcp.get_tools_for("route")

    # ③ 创建3个领域专家Agent（每个有独立的prompt和工具集）
    self._hotel_agent = SpecialistAgent(llm, "HotelAgent", HOTEL_AGENT_PROMPT, poi_tools)
    self._attraction_agent = SpecialistAgent(llm, "AttractionAgent", ATTRACTION_AGENT_PROMPT, poi_tools)
    self._weather_agent = SpecialistAgent(llm, "WeatherAgent", WEATHER_AGENT_PROMPT, weather_tools)

    await self._hotel_agent.build()          # ④ 构建子Agent（内部调用create_agent）
    await self._attraction_agent.build()
    await self._weather_agent.build()

    # ⑤ 用 @tool 装饰器将子Agent包装为Planner可调用的工具
    @tool
    async def search_hotel(query: str) -> str:
        """搜索酒店。输入城市+偏好，返回酒店列表。"""
        return await self._hotel_agent.invoke(query)

    # ... search_attraction, query_weather 同理

    all_tools = [search_hotel, search_attraction, query_weather, *route_tools]

    # ⑥ 创建顶层Planner Agent，它能看到所有工具
    self._agent = create_agent(model=llm, tools=all_tools, system_prompt=PLANNER_AGENT_PROMPT)
```

---

### `TokenManager.create_token_pair()` — JWT双令牌生成

```
def create_token_pair(self, user_id, extra_claims=None):
    """生成 access_token + refresh_token 对"""
    # 结构：header.payload.signature
    # Payload标准声明：
    #   sub=user_id, iss=签发者, aud=受众,
    #   typ="access"/"refresh",  jti=唯一ID(防重放),
    #   iat=签发时间, exp=过期时间, nbf=生效时间
```

---

## 四、技术方案取舍

| 抉择 | 选项A | 选项B | 实际选择 | 理由 |
|------|-------|-------|---------|------|
| Agent框架 | LangGraph直接 | LangChain封装 | **LangChain** | 快速原型，底层仍是LangGraph |
| 前端 | React/Vue | Streamlit | **Streamlit** | AI应用快速Demo，Python一站 |
| 认证 | JWT HS256 | OAuth2.0 | **JWT HS256** | 适合微服务间认证，轻量易部署 |
| 配置 | YAML文件 | @dataclass | **@dataclass** | 类型安全 + IDE提示 |
| 数据 | 真实API | 假数据 | **假数据+可切换** | 演示稳定性，需`AMAP` Key |

---

## 五、后续拓展方向

1. **FastAPI接口封装**：配合JWT认证提供RESTful API
2. **LangGraph显式状态机**：将隐式Agent循环改为显式DAG
3. **RAG增强**：接入用户历史+旅游攻略库做个性化推荐
4. **多模态输入**：支持语音+图片输入目的地信息
5. **多用户会话管理**：Redis存储对话状态
6. **CI/CD集成**：github actions + pytest + coverage
