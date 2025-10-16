"""
Unit tests for CaddyManager high-level functions.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from dockertree.commands.caddy import CaddyManager


class TestCaddyManager:
    """Test CaddyManager high-level functions."""
    
    @pytest.fixture
    def caddy_manager(self):
        """Create CaddyManager instance with mocked dependencies."""
        with patch('dockertree.commands.caddy.DockerManager'), \
             patch('dockertree.commands.caddy.get_project_root'):
            
            manager = CaddyManager()
            manager.docker_manager = Mock()
            manager.project_root = Path("/test/project")
            manager.compose_file = Mock()
            return manager
    
    def test_start_global_caddy_network_creation_fails(self, caddy_manager):
        """Test start_global_caddy when network creation fails."""
        caddy_manager.docker_manager.create_network.return_value = False
        
        result = caddy_manager.start_global_caddy()
        
        assert result == False
        caddy_manager.docker_manager.create_network.assert_called_once()
    
    def test_start_global_caddy_compose_file_not_found(self, caddy_manager):
        """Test start_global_caddy when compose file doesn't exist."""
        caddy_manager.docker_manager.create_network.return_value = True
        caddy_manager.compose_file.exists.return_value = False
        
        result = caddy_manager.start_global_caddy()
        
        assert result == False
        caddy_manager.docker_manager.create_network.assert_called_once()
    
    def test_start_global_caddy_success(self, caddy_manager):
        """Test successful global Caddy start."""
        caddy_manager.docker_manager.create_network.return_value = True
        caddy_manager.compose_file.exists.return_value = True
        caddy_manager.docker_manager.start_services.return_value = True
        
        result = caddy_manager.start_global_caddy()
        
        assert result == True
        caddy_manager.docker_manager.create_network.assert_called_once()
        caddy_manager.docker_manager.start_services.assert_called_once_with(caddy_manager.compose_file)
    
    def test_start_global_caddy_services_fail(self, caddy_manager):
        """Test start_global_caddy when services fail to start."""
        caddy_manager.docker_manager.create_network.return_value = True
        caddy_manager.compose_file.exists.return_value = True
        caddy_manager.docker_manager.start_services.return_value = False
        
        result = caddy_manager.start_global_caddy()
        
        assert result == False
        caddy_manager.docker_manager.create_network.assert_called_once()
        caddy_manager.docker_manager.start_services.assert_called_once_with(caddy_manager.compose_file)
    
    def test_stop_global_caddy_compose_file_not_found(self, caddy_manager):
        """Test stop_global_caddy when compose file doesn't exist."""
        caddy_manager.compose_file.exists.return_value = False
        
        result = caddy_manager.stop_global_caddy()
        
        assert result == True  # Stop operations should succeed even if file not found
        caddy_manager.docker_manager.stop_services.assert_not_called()
    
    def test_stop_global_caddy_success(self, caddy_manager):
        """Test successful global Caddy stop."""
        caddy_manager.compose_file.exists.return_value = True
        caddy_manager.docker_manager.stop_services.return_value = True
        
        result = caddy_manager.stop_global_caddy()
        
        assert result == True
        caddy_manager.docker_manager.stop_services.assert_called_once_with(caddy_manager.compose_file)
    
    def test_stop_global_caddy_services_fail(self, caddy_manager):
        """Test stop_global_caddy when services fail to stop."""
        caddy_manager.compose_file.exists.return_value = True
        caddy_manager.docker_manager.stop_services.return_value = False
        
        result = caddy_manager.stop_global_caddy()
        
        assert result == False
        caddy_manager.docker_manager.stop_services.assert_called_once_with(caddy_manager.compose_file)
    
    @patch('dockertree.commands.caddy.validate_container_running')
    def test_is_caddy_running_true(self, mock_validate, caddy_manager):
        """Test is_caddy_running when Caddy is running."""
        mock_validate.return_value = True
        
        result = caddy_manager.is_caddy_running()
        
        assert result == True
        mock_validate.assert_called_once_with("dockertree_caddy_proxy")
    
    @patch('dockertree.commands.caddy.validate_container_running')
    def test_is_caddy_running_false(self, mock_validate, caddy_manager):
        """Test is_caddy_running when Caddy is not running."""
        mock_validate.return_value = False
        
        result = caddy_manager.is_caddy_running()
        
        assert result == False
        mock_validate.assert_called_once_with("dockertree_caddy_proxy")
    
    @patch('dockertree.commands.caddy.validate_container_running')
    def test_get_caddy_status(self, mock_validate, caddy_manager):
        """Test getting Caddy status information."""
        mock_validate.return_value = True
        caddy_manager.compose_file.exists.return_value = True
        caddy_manager.docker_manager.create_network.return_value = True
        
        result = caddy_manager.get_caddy_status()
        
        expected = {
            "running": True,
            "compose_file_exists": True,
            "network_exists": True
        }
        
        assert result == expected
        mock_validate.assert_called_once_with("dockertree_caddy_proxy")
        caddy_manager.compose_file.exists.assert_called_once()
        caddy_manager.docker_manager.create_network.assert_called_once()
    
    @patch('dockertree.commands.caddy.validate_container_running')
    def test_get_caddy_status_not_running(self, mock_validate, caddy_manager):
        """Test getting Caddy status when not running."""
        mock_validate.return_value = False
        caddy_manager.compose_file.exists.return_value = False
        caddy_manager.docker_manager.create_network.return_value = False
        
        result = caddy_manager.get_caddy_status()
        
        expected = {
            "running": False,
            "compose_file_exists": False,
            "network_exists": False
        }
        
        assert result == expected
        mock_validate.assert_called_once_with("dockertree_caddy_proxy")
        caddy_manager.compose_file.exists.assert_called_once()
        caddy_manager.docker_manager.create_network.assert_called_once()
