# WanderBot -- 旅行规划助手

基于 LangChain + LangGraph 的智能旅行规划 Agent，具备三大核心功能：

- **Memory** -- 对话记忆，跨轮次保持上下文
- **RAG** -- 检索增强生成，查询本地旅行知识数据库
- **MCP** -- 调用自定义 MCP 服务器保存/读取旅行计划

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 API key
```

支持两种 LLM 提供商：
- Anthropic Claude（默认）-- 设置 `ANTHROPIC_API_KEY`
- OpenAI 兼容端点 -- 设置 `OPENAI_API_KEY` 和 `OPENAI_API_BASE`（支持 DeepSeek、智谱 GLM 等）

### 3. 构建向量库

```bash
python rag_setup.py
```

首次运行会下载嵌入模型（约 22MB），然后构建 ChromaDB 向量库。

### 4. 启动 Agent

```bash
python agent.py
```

进入交互界面后：
- 正常输入与 WanderBot 对话
- 输入 `new` 开始新对话（清除记忆）
- 输入 `quit` 或 `exit` 退出

## 文件结构

```
agent/
├── agent.py           # 主入口，集成 LLM + RAG + MCP + Memory
├── rag_setup.py       # 向量库构建脚本（运行一次）
├── mcp_server.py      # MCP 服务器（行程文件操作）
├── mcp_config.json    # MCP 连接配置
├── prompt.md          # Agent 系统提示词
├── requirements.txt   # Python 依赖
├── .env.example       # 环境变量模板
├── travel_data/       # 旅行知识文档（RAG 数据源）
│   ├── tokyo.md
│   ├── paris.md
│   ├── new_york.md
│   ├── bangkok.md
│   ├── travel_tips.md
│   ├── culture_food.md
│   └── weather_seasons.md
├── chroma_db/         # 向量库持久存储（rag_setup.py 生成）
└── travel_plans/      # 保存的旅行计划（MCP 工具生成）
```

## MCP 服务器工具

自定义 MCP 服务器提供三个工具：

| 工具 | 功能 | 参数 |
|------|------|------|
| `save_travel_plan` | 保存行程为 .md 文件 | plan_name, content |
| `read_travel_plan` | 读取已保存行程 | plan_name |
| `list_travel_plans` | 列出所有行程 | 无 |

## 添加更多旅行数据

1. 在 `travel_data/` 中创建新的 .md 文件
2. 重新运行 `python rag_setup.py` 更新向量库

## 配置选项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | anthropic | LLM 提供商：anthropic 或 openai |
| `LLM_MODEL_NAME` | claude-sonnet-4-20250514 | 模型名称 |
| `OPENAI_API_BASE` | https://api.openai.com/v1 | OpenAI 兼容端点 URL |
| `EMBEDDING_MODEL` | all-MiniLM-L6-v2 | 嵌入模型（本地运行） |
| `CHROMA_PERSIST_DIR` | ./chroma_db | 向量库路径 |
| `TRAVEL_PLANS_DIR` | ./travel_plans | 行程文件路径 |