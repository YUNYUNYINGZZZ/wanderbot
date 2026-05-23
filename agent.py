"""WanderBot -- Travel Planning Assistant Agent

An interactive LangChain agent with three core capabilities:
1. Memory -- Conversation context persists across turns via LangGraph checkpointer
2. RAG -- Searches a local ChromaDB vector store for travel knowledge
3. MCP -- Calls a custom MCP server for saving/loading travel plan files

Usage:
    python rag_setup.py   # Build vector store first (run once)
    python agent.py       # Start interactive chat

Commands during chat:
    - Type normally to chat with WanderBot
    - Type 'new' to start a fresh conversation (clears memory)
    - Type 'quit' or 'exit' to end the session
"""

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "claude-sonnet-4-20250514")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
MCP_CONFIG_PATH = os.getenv("MCP_CONFIG_PATH", "mcp_config.json")

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


# ---- System Prompt ----

def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompt.md"
    return prompt_path.read_text(encoding="utf-8")


# ---- LLM Initialization ----

def get_llm():
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        api_url = os.getenv("ANTHROPIC_API_URL", None)
        kwargs = {"model_name": LLM_MODEL_NAME}
        if api_url:
            kwargs["anthropic_api_url"] = api_url
        return ChatAnthropic(**kwargs)
    elif LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        return ChatOpenAI(
            model=LLM_MODEL_NAME,
            openai_api_base=api_base,
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


# ---- RAG Tool ----

def create_rag_tool():
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
        weather patterns, food recommendations, and travel advice.

        Use this tool whenever you need factual information about a destination,
        local customs, best travel seasons, or practical travel tips.

        Args:
            query: The travel-related question to search for
        """
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


# ---- Weather & Time Tools ----

import json as _json
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


def create_weather_tool():
    @tool("get_weather")
    def get_weather(location: str) -> str:
        """Get current weather for a travel destination. Returns temperature, humidity,
        wind, weather description, sunrise/sunset times.

        Use this tool when the user asks about current or upcoming weather at a destination.

        Args:
            location: City name (e.g., "Tokyo", "Paris", "New York")
        """
        encoded = urllib.parse.quote(location)
        url = f"https://wttr.in/{encoded}?format=j1"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WanderBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))

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
    @tool("get_current_time")
    def get_current_time(city: str = "") -> str:
        """Get the current date and time for a travel destination. Returns local time,
        UTC time, and timezone offset.

        Use this tool when the user asks about the current time, date, or timezone at a destination.

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


# ---- MCP Tools ----

async def load_mcp_tools():
    from langchain_mcp_adapters.client import MultiServerMCPClient
    config_path = Path(__file__).parent / MCP_CONFIG_PATH
    mcp_config = json.loads(config_path.read_text(encoding="utf-8"))
    client = MultiServerMCPClient(mcp_config)
    mcp_tools = await client.get_tools()
    return list(mcp_tools)


# ---- Agent Construction ----

async def create_travel_agent():
    from langgraph.prebuilt import create_react_agent

    llm = get_llm()
    rag_tool = create_rag_tool()
    weather_tool = create_weather_tool()
    time_tool = create_time_tool()
    mcp_tools = await load_mcp_tools()
    all_tools = [rag_tool, weather_tool, time_tool] + mcp_tools
    system_prompt = load_system_prompt()
    checkpointer = MemorySaver()

    agent = create_react_agent(
        model=llm,
        tools=all_tools,
        prompt=system_prompt,
        checkpointer=checkpointer,
    )
    return agent


# ---- Interactive Chat Loop ----

async def chat_loop():
    agent = await create_travel_agent()

    thread_id = f"travel_session_{int(time.time())}"
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 60)
    print("  WanderBot -- Your Travel Planning Assistant")
    print("  Type 'quit' or 'exit' to end the session")
    print("  Type 'new' to start a fresh conversation")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nWanderBot: Happy travels! Goodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("WanderBot: Happy travels! Goodbye!")
            break
        if user_input.lower() == "new":
            thread_id = f"travel_session_{int(time.time())}"
            config = {"configurable": {"thread_id": thread_id}}
            print("WanderBot: Starting a new conversation! Where would you like to go?")
            continue

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
        )

        ai_messages = [m for m in result["messages"] if m.type == "ai"]
        if ai_messages:
            last_ai = ai_messages[-1]
            print(f"\nWanderBot: {last_ai.content}")


if __name__ == "__main__":
    asyncio.run(chat_loop())