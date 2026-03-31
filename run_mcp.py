#!/usr/bin/env python3
"""Standalone MCP server launcher.
Adds its own directory to sys.path so mcp_server and egtsr_runtime are importable.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_server.server import main

main()
