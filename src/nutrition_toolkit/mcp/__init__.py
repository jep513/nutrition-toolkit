"""MCP server exposing the toolkit. Needs the [mcp] extra."""

from __future__ import annotations

from .server import main, mcp

__all__ = ["main", "mcp"]
