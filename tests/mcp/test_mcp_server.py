"""
Tests for dockertree MCP server.

This module contains tests for the MCP server functionality.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch

from dockertree_mcp.server import DockertreeMCPServer
from dockertree_mcp.config import MCPConfig


class TestDockertreeMCPServer:
    """Test cases for DockertreeMCPServer."""
    
    def test_server_initialization(self):
        """Test MCP server initialization."""
        config = MCPConfig()
        server = DockertreeMCPServer(config)
        
        assert server.config == config
        assert server.worktree_tools is not None
        assert server.volume_tools is not None
        assert server.caddy_tools is not None
        assert server.worktree_resources is not None
    
    @pytest.mark.asyncio
    async def test_list_tools(self):
        """Test listing MCP tools."""
        config = MCPConfig()
        server = DockertreeMCPServer(config)
        
        # Mock the server's list_tools method
        with patch.object(server.server, 'list_tools') as mock_list_tools:
            mock_list_tools.return_value = Mock()
            
            # This would normally be called by the MCP client
            # For now, just verify the server has the method
            assert hasattr(server, '_list_tools')
    
    @pytest.mark.asyncio
    async def test_list_resources(self):
        """Test listing MCP resources."""
        config = MCPConfig()
        server = DockertreeMCPServer(config)
        
        # Mock the server's list_resources method
        with patch.object(server.server, 'list_resources') as mock_list_resources:
            mock_list_resources.return_value = Mock()
            
            # This would normally be called by the MCP client
            # For now, just verify the server has the method
            assert hasattr(server, '_list_resources')


class TestMCPConfig:
    """Test cases for MCPConfig."""
    
    def test_config_initialization(self):
        """Test MCP configuration initialization."""
        config = MCPConfig()
        
        assert config.working_directory is not None
        assert config.timeout == 300
        assert config.verbose is False
    
    def test_config_from_env(self):
        """Test configuration from environment variables."""
        import os
        
        # Set environment variables
        os.environ["DOCKERTREE_WORKING_DIR"] = "/test/dir"
        os.environ["DOCKERTREE_TIMEOUT"] = "600"
        os.environ["DOCKERTREE_VERBOSE"] = "true"
        
        config = MCPConfig.from_env()
        
        assert str(config.working_directory) == "/test/dir"
        assert config.timeout == 600
        assert config.verbose is True
        
        # Clean up
        del os.environ["DOCKERTREE_WORKING_DIR"]
        del os.environ["DOCKERTREE_TIMEOUT"]
        del os.environ["DOCKERTREE_VERBOSE"]
    
    def test_config_to_dict(self):
        """Test configuration to dictionary conversion."""
        config = MCPConfig()
        config_dict = config.to_dict()
        
        assert "working_directory" in config_dict
        assert "timeout" in config_dict
        assert "verbose" in config_dict


