"""
Direct Python API for dockertree MCP server.

This module provides direct Python API access to dockertree functionality,
bypassing the CLI wrapper for richer responses and better integration.
"""

from .dockertree_api import DockertreeAPI

__all__ = ["DockertreeAPI"]
