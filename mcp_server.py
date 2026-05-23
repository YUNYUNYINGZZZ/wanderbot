"""Custom MCP server for travel plan file operations.

Provides three tools for managing travel plan files:
- save_travel_plan: Save a travel itinerary as a .md file
- read_travel_plan: Load a previously saved travel plan
- list_travel_plans: Show all saved travel plans with timestamps

Run via stdio transport (langchain-mcp-adapters connects to this subprocess).
"""

import os
import re
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TravelPlanServer")

TRAVEL_PLANS_DIR = Path(os.getenv("TRAVEL_PLANS_DIR", "./travel_plans"))
TRAVEL_PLANS_DIR.mkdir(exist_ok=True)


def sanitize_name(name: str) -> str:
    """Sanitize a plan name to prevent path traversal and ensure safe filenames."""
    safe = re.sub(r"[^\w\-]", "_", name.replace(" ", "_"))
    return safe[:100]  # Limit length


@mcp.tool()
def save_travel_plan(plan_name: str, content: str) -> str:
    """Save a travel plan to a markdown file.

    Args:
        plan_name: Name for the travel plan (e.g., "tokyo_7day_itinerary")
        content: The full travel plan content in markdown format

    Returns:
        Confirmation message with the saved file path
    """
    safe_name = sanitize_name(plan_name)
    filepath = TRAVEL_PLANS_DIR / f"{safe_name}.md"
    filepath.write_text(content, encoding="utf-8")
    return f"Travel plan '{safe_name}' saved to: {filepath}"


@mcp.tool()
def read_travel_plan(plan_name: str) -> str:
    """Read a previously saved travel plan from a file.

    Args:
        plan_name: Name of the travel plan to read (e.g., "tokyo_7day_itinerary")

    Returns:
        The content of the travel plan file, or an error message if not found
    """
    safe_name = sanitize_name(plan_name)
    filepath = TRAVEL_PLANS_DIR / f"{safe_name}.md"
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    available = [f.stem for f in TRAVEL_PLANS_DIR.glob("*.md")]
    available_str = ", ".join(available) if available else "none"
    return f"Plan '{plan_name}' not found. Available plans: {available_str}"


@mcp.tool()
def list_travel_plans() -> str:
    """List all saved travel plans with their update timestamps.

    Returns:
        A formatted list of all available travel plan names and timestamps
    """
    plans = list(TRAVEL_PLANS_DIR.glob("*.md"))
    if not plans:
        return "No travel plans saved yet. Start planning your first trip!"
    lines = []
    for filepath in sorted(plans):
        mtime = filepath.stat().st_mtime
        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"- {filepath.stem} (updated: {timestamp})")
    return "Available travel plans:\n" + "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")