"""
Web Application and Interactive Dashboard package for the Multi-Agent AI Platform.
Provides local HTTP API server and interactive visual graph UI.
"""

from .server import MultiAgentUIServer, run_server

__all__ = ["MultiAgentUIServer", "run_server"]
