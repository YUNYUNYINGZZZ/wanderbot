"""WanderBot Web Interface -- Streamlit chat UI for the travel planning agent.

Usage:
    streamlit run app.py
"""

import asyncio
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def get_config(key, default=""):
    """Read config from env vars, falling back to Streamlit secrets.
    Also syncs secrets into os.environ so SDKs like langchain-anthropic can find them."""
    val = os.getenv(key, "")
    if not val:
        try:
            val = st.secrets[key]
            # Write back to os.environ so external SDKs can read it
            os.environ[key] = str(val)
        except (KeyError, FileNotFoundError):
            pass
    return val or default


# Load all config, syncing Streamlit secrets into os.environ for SDK compatibility
LLM_PROVIDER = get_config("LLM_PROVIDER", "anthropic")
LLM_MODEL_NAME = get_config("LLM_MODEL_NAME", "claude-sonnet-4-20250514")
CHROMA_PERSIST_DIR = get_config("CHROMA_PERSIST_DIR", "./chroma_db")
EMBEDDING_MODEL = get_config("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
MCP_CONFIG_PATH = get_config("MCP_CONFIG_PATH", "mcp_config.json")

# Ensure API keys are in os.environ for langchain-anthropic SDK
get_config("ANTHROPIC_API_KEY", "")
get_config("ANTHROPIC_API_URL", "")
get_config("OPENAI_API_KEY", "")
get_config("OPENAI_API_BASE", "https://api.openai.com/v1")

CONVERSATIONS_DIR = Path(__file__).parent / "conversations"
CONVERSATIONS_DIR.mkdir(exist_ok=True)

CITY_TIMEZONES = {
    "tokyo": "Asia/Tokyo", "osaka": "Asia/Tokyo", "kyoto": "Asia/Tokyo",
    "paris": "Europe/Paris", "lyon": "Europe/Paris",
    "new york": "America/New_York", "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "chicago": "America/Chicago",
    "bangkok": "Asia/Bangkok", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai",
    "hangzhou": "Asia/Shanghai", "guangzhou": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong", "taipei": "Asia/Taipei",
    "seoul": "Asia/Seoul", "singapore": "Asia/Singapore",
    "london": "Europe/London", "berlin": "Europe/Berlin",
    "amsterdam": "Europe/Amsterdam", "rome": "Europe/Rome",
    "istanbul": "Europe/Istanbul", "moscow": "Europe/Moscow",
    "dubai": "Asia/Dubai", "mumbai": "Asia/Kolkata",
    "cairo": "Africa/Cairo", "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland",
    "mexico city": "America/Mexico_City",
    "rio de janeiro": "America/Sao_Paulo",
}

TOOL_LABELS = {
    "travel_knowledge_search": ("🔍 RAG", "检索本地旅行知识数据库"),
    "get_weather": ("🌤️ 天气", "获取目的地实时天气"),
    "get_current_time": ("🕐 时间", "获取目的地当前时间"),
    "save_travel_plan": ("💾 MCP", "保存旅行计划到文件"),
    "read_travel_plan": ("📂 MCP", "读取已保存的旅行计划"),
    "list_travel_plans": ("📋 MCP", "列出所有旅行计划"),
}

# ---- Page Config ----

st.set_page_config(page_title="WanderBot", page_icon="🌍", layout="wide")


# ---- Conversation Persistence ----

def get_conv_path(thread_id):
    return CONVERSATIONS_DIR / f"{thread_id}.json"


def save_conversation(thread_id, messages, title=""):
    """Save current conversation to a JSON file."""
    data = {
        "thread_id": thread_id,
        "title": title,
        "updated_at": datetime.now().isoformat(),
        "messages": messages,
    }
    get_conv_path(thread_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_conversation(thread_id):
    """Load a conversation from a JSON file."""
    path = get_conv_path(thread_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def list_conversations():
    """List all saved conversations, sorted by update time (newest first)."""
    convs = []
    for path in CONVERSATIONS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        convs.append({
            "thread_id": data["thread_id"],
            "title": data.get("title", "新对话"),
            "updated_at": data.get("updated_at", ""),
            "msg_count": len(data.get("messages", [])),
        })
    convs.sort(key=lambda c: c["updated_at"], reverse=True)
    return convs


def derive_title(messages):
    """Derive a conversation title from the first user message."""
    for msg in messages:
        if msg["role"] == "user":
            text = msg["content"][:30].strip()
            return text if text else "新对话"
    return "新对话"


# ---- LLM & Agent Helpers ----

def get_llm():
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        api_key = get_config("ANTHROPIC_API_KEY", "")
        api_url = get_config("ANTHROPIC_API_URL", None)
        kwargs = {"model_name": LLM_MODEL_NAME}
        if api_key:
            kwargs["anthropic_api_key"] = api_key
        if api_url:
            kwargs["anthropic_api_url"] = api_url
        return ChatAnthropic(**kwargs)
    elif LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        api_key = get_config("OPENAI_API_KEY", "")
        api_base = get_config("OPENAI_API_BASE", "https://api.openai.com/v1")
        return ChatOpenAI(
            model=LLM_MODEL_NAME,
            openai_api_key=api_key,
            openai_api_base=api_base,
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def ensure_vectorstore():
    """Build ChromaDB if it doesn't exist (for Streamlit Cloud deployment)."""
    chroma_path = Path(CHROMA_PERSIST_DIR)
    if chroma_path.exists() and any(chroma_path.iterdir()):
        return

    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_huggingface import HuggingFaceEmbeddings

    data_dir = Path(__file__).parent / "travel_data"
    category_map = {
        "tokyo": "destination", "paris": "destination",
        "new_york": "destination", "bangkok": "destination",
        "travel_tips": "tips", "culture_food": "culture_food",
        "weather_seasons": "weather",
    }

    docs = []
    for filepath in data_dir.glob("*.md"):
        category = category_map.get(filepath.stem, "general")
        docs.append(Document(
            page_content=filepath.read_text(encoding="utf-8"),
            metadata={"source": filepath.stem, "category": category},
        ))

    if docs:
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        Chroma.from_documents(
            documents=docs, embedding=embeddings,
            collection_name="travel_knowledge",
            persist_directory=CHROMA_PERSIST_DIR,
        )


def create_rag_tool():
    from langchain_chroma import Chroma
    from langchain_core.tools import tool
    from langchain_huggingface import HuggingFaceEmbeddings

    ensure_vectorstore()

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vectorstore = Chroma(
        collection_name="travel_knowledge",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    @tool("travel_knowledge_search")
    def travel_knowledge_search(query: str) -> str:
        """Search the travel knowledge database for destination info, cultural tips,
        weather patterns, food recommendations, and travel advice."""
        docs = retriever.invoke(query)
        if not docs:
            return "No relevant travel knowledge found in the database."
        result_parts = []
        for doc in docs:
            source = doc.metadata.get("source", "unknown")
            category = doc.metadata.get("category", "general")
            result_parts.append(f"[{source} ({category})]\n{doc.page_content[:500]}")
        return "\n\n---\n\n".join(result_parts)

    return travel_knowledge_search


async def load_mcp_tools():
    """Load MCP tools. Returns empty list if MCP server cannot start (e.g. on Streamlit Cloud)."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        config_path = Path(__file__).parent / MCP_CONFIG_PATH
        mcp_config = json.loads(config_path.read_text(encoding="utf-8"))
        client = MultiServerMCPClient(mcp_config)
        mcp_tools = await client.get_tools()
        return list(mcp_tools)
    except Exception as e:
        st.warning(f"MCP 服务器无法启动（云端部署不支持子进程），旅行计划文件功能暂不可用。")
        return []


def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompt.md"
    return prompt_path.read_text(encoding="utf-8")


def create_weather_tool():
    from langchain_core.tools import tool

    @tool("get_weather")
    def get_weather(location: str) -> str:
        """Get current weather for a travel destination. Returns temperature, humidity,
        wind, weather description, sunrise/sunset times.

        Args:
            location: City name (e.g., "Tokyo", "Paris", "New York")
        """
        encoded = urllib.parse.quote(location)
        url = f"https://wttr.in/{encoded}?format=j1"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WanderBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            current = data.get("current_condition", [{}])[0]
            area = data.get("nearest_area", [{}])[0]
            weather = data.get("weather", [{}])[0]
            astro = weather.get("astronomy", [{}])[0]

            city_name = area.get("areaName", [{}])[0].get("value", location)
            country = area.get("country", [{}])[0].get("value", "N/A")
            desc = current.get("weatherDesc", [{}])[0].get("value", "N/A")

            lines = [
                f"{city_name}, {country}",
                f"Temperature: {current.get('temp_C', 'N/A')}C / {current.get('temp_F', 'N/A')}F",
                f"Feels like: {current.get('FeelsLikeC', 'N/A')}C",
                f"Humidity: {current.get('humidity', 'N/A')}%",
                f"Wind: {current.get('windspeedKmph', 'N/A')} km/h {current.get('winddir16Point', 'N/A')}",
                f"Condition: {desc}",
                f"Sunrise/Sunset: {astro.get('sunrise', 'N/A')} / {astro.get('sunset', 'N/A')}",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Unable to fetch weather for {location}: {e}"

    return get_weather


def create_time_tool():
    from langchain_core.tools import tool

    @tool("get_current_time")
    def get_current_time(city: str = "") -> str:
        """Get the current date and time for a travel destination. Returns local time,
        UTC time, and timezone offset.

        Args:
            city: City name (e.g., "Tokyo", "Paris"). If empty, returns UTC time.
        """
        if not city:
            now = datetime.now(ZoneInfo("UTC"))
            return f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S')}"

        tz = CITY_TIMEZONES.get(city.lower().strip())
        if not tz:
            available = ", ".join(sorted(CITY_TIMEZONES.keys()))
            return f"City '{city}' not in timezone database. Supported: {available}"

        now = datetime.now(ZoneInfo(tz))
        utc_now = datetime.now(ZoneInfo("UTC"))
        offset_h = now.utcoffset().total_seconds() / 3600

        return (
            f"{city} ({tz})\n"
            f"Local time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTC time: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTC offset: +{offset_h:.0f}h"
        )

    return get_current_time


async def build_agent():
    from langgraph.prebuilt import create_react_agent
    from langgraph.checkpoint.memory import MemorySaver

    llm = get_llm()
    rag_tool = create_rag_tool()
    weather_tool = create_weather_tool()
    time_tool = create_time_tool()
    mcp_tools = await load_mcp_tools()
    all_tools = [rag_tool, weather_tool, time_tool] + mcp_tools
    system_prompt = load_system_prompt()

    agent = create_react_agent(
        model=llm,
        tools=all_tools,
        prompt=system_prompt,
        checkpointer=MemorySaver(),
    )
    return agent


def extract_tool_calls(result_messages):
    calls = []
    for msg in result_messages:
        if msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                info = TOOL_LABELS.get(tc["name"], ("🔧 Tool", tc["name"]))
                args_str = str(tc.get("args", "")) if tc.get("args") else ""
                calls.append((info[0], info[1], tc["name"], args_str))
    return calls


def extract_response(result_messages):
    ai_messages = [m for m in result_messages if m.type == "ai"]
    if not ai_messages:
        return ""
    raw_content = ai_messages[-1].content
    if isinstance(raw_content, list):
        text_parts = [
            block.get("text", "") for block in raw_content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(text_parts)
    return str(raw_content)


def render_message(msg):
    with st.chat_message(msg["role"]):
        if msg.get("tool_calls"):
            with st.expander("🛠️ 工具调用详情", expanded=False):
                for icon, desc, name, args in msg["tool_calls"]:
                    st.markdown(f"**{icon} {desc}** — `{name}`")
                    if args:
                        st.code(args, language="json")
        st.markdown(msg["content"], unsafe_allow_html=True)


# ---- Streamlit UI ----

# Sidebar
with st.sidebar:
    st.title("🌍 WanderBot")
    st.caption("旅行规划助手 — Memory + RAG + MCP")

    st.markdown("---")
    st.subheader("历史对话")
    saved_convs = list_conversations()
    if saved_convs:
        for conv in saved_convs:
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(
                    f"{conv['title']} ({conv['msg_count']}条)",
                    key=f"load_{conv['thread_id']}",
                    use_container_width=True,
                ):
                    loaded = load_conversation(conv["thread_id"])
                    if loaded:
                        st.session_state.thread_id = conv["thread_id"]
                        st.session_state.messages = loaded["messages"]
                        st.session_state.conv_title = conv["title"]
                        st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{conv['thread_id']}"):
                    get_conv_path(conv["thread_id"]).unlink(missing_ok=True)
                    st.rerun()
    else:
        st.info("暂无历史对话")

    st.markdown("---")
    if st.button("➕ 开始新对话", use_container_width=True, type="primary"):
        st.session_state.thread_id = f"travel_session_{int(time.time())}"
        st.session_state.messages = []
        st.session_state.conv_title = "新对话"
        st.rerun()

    st.markdown("---")
    st.subheader("当前配置")
    st.text(f"LLM: {LLM_PROVIDER} / {LLM_MODEL_NAME}")
    st.text(f"Embedding: {EMBEDDING_MODEL}")

# ---- Session State ----

if "agent" not in st.session_state:
    with st.spinner("正在初始化 Agent（加载 RAG + MCP + Memory）..."):
        agent = asyncio.run(build_agent())
        st.session_state.agent = agent
        st.session_state.thread_id = f"travel_session_{int(time.time())}"
        st.session_state.messages = []
        st.session_state.conv_title = "新对话"

if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"travel_session_{int(time.time())}"
if "conv_title" not in st.session_state:
    st.session_state.conv_title = "新对话"

# ---- Display Chat History ----

st.subheader(st.session_state.conv_title)
for msg in st.session_state.messages:
    render_message(msg)

# ---- Chat Input ----

if prompt := st.chat_input("输入你的旅行问题..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Auto-derive title from first user message
    if len(st.session_state.messages) == 1:
        st.session_state.conv_title = derive_title(st.session_state.messages)

    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    with st.chat_message("assistant"):
        with st.spinner("WanderBot 正在思考..."):
            result = asyncio.run(
                st.session_state.agent.ainvoke(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config=config,
                )
            )

        tool_calls = extract_tool_calls(result["messages"])
        if tool_calls:
            with st.expander("🛠️ 工具调用详情", expanded=True):
                for icon, desc, name, args in tool_calls:
                    st.markdown(f"**{icon} {desc}** — `{name}`")
                    if args:
                        st.code(args, language="json")

        response = extract_response(result["messages"])
        st.markdown(response, unsafe_allow_html=True)

        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "tool_calls": tool_calls,
        })

    # Auto-save conversation after each exchange
    save_conversation(
        st.session_state.thread_id,
        st.session_state.messages,
        st.session_state.conv_title,
    )