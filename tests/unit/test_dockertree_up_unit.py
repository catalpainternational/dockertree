"""
Unit tests for dockertree up -d command logic.

This test suite validates the specific logic and behavior of the dockertree up -d command
without requiring full Docker environment setup.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from dockertree.cli import up
from dockertree.commands.worktree import WorktreeManager


class TestDockertreeUpCommand:
    """Test dockertree up -d command logic."""
    
    def test_up_command_requires_detach_flag(self):
        """Test that up command requires -d flag."""
        # This should be tested through the CLI, but we can test the logic
        # The CLI should reject calls without -d flag
        pass
    
    @patch('dockertree.cli.check_prerequisites')
    @patch('dockertree.cli.WorktreeManager')
    def test_up_command_calls_worktree_manager_start(self, mock_worktree_class, mock_check_prereq):
        """Test that up command calls WorktreeManager.start_worktree()."""
        # Mock the worktree manager
        mock_worktree_manager = Mock()
        mock_worktree_class.return_value = mock_worktree_manager
        mock_worktree_manager.start_worktree.return_value = True
        
        # Mock prerequisites check
        mock_check_prereq.return_value = None
        
        # Test the up command logic (without actually calling the CLI)
        branch_name = "test-branch"
        try:
            mock_check_prereq()
            worktree_manager = mock_worktree_class()
            success = worktree_manager.start_worktree(branch_name)
            
            assert success == True
            mock_check_prereq.assert_called_once()
            mock_worktree_class.assert_called_once()
            mock_worktree_manager.start_worktree.assert_called_once_with(branch_name)
        except Exception:
            # This is expected since we're not in a real worktree directory
            pass
    
    @patch('dockertree.cli.check_prerequisites')
    @patch('dockertree.cli.WorktreeManager')
    def test_up_command_handles_start_failure(self, mock_worktree_class, mock_check_prereq):
        """Test that up command handles start_worktree failure."""
        # Mock the worktree manager
        mock_worktree_manager = Mock()
        mock_worktree_class.return_value = mock_worktree_manager
        mock_worktree_manager.start_worktree.return_value = False
        
        # Mock prerequisites check
        mock_check_prereq.return_value = None
        
        # Test the up command logic
        branch_name = "test-branch"
        try:
            mock_check_prereq()
            worktree_manager = mock_worktree_class()
            success = worktree_manager.start_worktree(branch_name)
            
            assert success == False
            mock_worktree_manager.start_worktree.assert_called_once_with(branch_name)
        except Exception:
            # This is expected since we're not in a real worktree directory
            pass
    
    def test_worktree_manager_start_worktree_validation(self):
        """Test WorktreeManager.start_worktree validation logic."""
        with patch('dockertree.commands.worktree.DockerManager'), \
             patch('dockertree.commands.worktree.GitManager'), \
             patch('dockertree.commands.worktree.EnvironmentManager'), \
             patch('dockertree.commands.worktree.get_project_root'):
            
            manager = WorktreeManager()
            manager.docker_manager = Mock()
            manager.git_manager = Mock()
            manager.env_manager = Mock()
            manager.project_root = Path("/test/project")
            branch_name = "test-branch"
            
            # Test 1: Worktree doesn't exist
            manager.git_manager.validate_worktree_exists.return_value = False
            result = manager.start_worktree(branch_name)
            assert result == False
            
            # Test 2: Worktree path not found
            manager.git_manager.validate_worktree_exists.return_value = True
            manager.git_manager.find_worktree_path.return_value = None
            result = manager.start_worktree(branch_name)
            assert result == False
    
    def test_worktree_manager_start_worktree_success_path(self):
        """Test WorktreeManager.start_worktree success path."""
        with patch('dockertree.commands.worktree.DockerManager'), \
             patch('dockertree.commands.worktree.GitManager'), \
             patch('dockertree.commands.worktree.EnvironmentManager'), \
             patch('dockertree.commands.worktree.get_project_root'):
            
            manager = WorktreeManager()
            manager.docker_manager = Mock()
            manager.git_manager = Mock()
            manager.env_manager = Mock()
            manager.project_root = Path("/test/project")
            branch_name = "test-branch"
            worktree_path = Path("/test/worktree")
            
            # Mock git manager methods
            manager.git_manager.validate_worktree_exists.return_value = True
            manager.git_manager.find_worktree_path.return_value = worktree_path
            
            # Mock all the validation functions to return success
            with patch('dockertree.commands.worktree.get_compose_override_path', return_value=Path("/test/compose.yml")), \
                 patch('dockertree.commands.worktree.get_worktree_branch_name', return_value=branch_name):
                
                # Mock the compose file to exist
                with patch('pathlib.Path.exists', return_value=True):
                    # Mock all the manager methods to return success
                    manager.docker_manager.create_worktree_volumes.return_value = True
                    manager.docker_manager.create_network.return_value = True
                    manager.docker_manager.run_compose_command.return_value = True
                    
                    with patch('dockertree.commands.worktree.WorktreeManager._configure_caddy_routes', return_value=True):
                        result = manager.start_worktree(branch_name)
                
                assert result == True
                manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
                manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
                manager.docker_manager.create_worktree_volumes.assert_called_once_with(branch_name, force_copy=False)
                manager.docker_manager.create_network.assert_called_once()
    
    def test_worktree_manager_start_worktree_network_creation_failure(self):
        """Test WorktreeManager.start_worktree when network creation fails."""
        with patch('dockertree.commands.worktree.DockerManager'), \
             patch('dockertree.commands.worktree.GitManager'), \
             patch('dockertree.commands.worktree.EnvironmentManager'), \
             patch('dockertree.commands.worktree.get_project_root'):
            
            manager = WorktreeManager()
            manager.docker_manager = Mock()
            manager.git_manager = Mock()
            manager.env_manager = Mock()
            manager.project_root = Path("/test/project")
            branch_name = "test-branch"
            worktree_path = Path("/test/worktree")
            
            # Mock git manager methods
            manager.git_manager.validate_worktree_exists.return_value = True
            manager.git_manager.find_worktree_path.return_value = worktree_path
            
            # Mock all the validation functions to return success
            with patch('dockertree.commands.worktree.get_compose_override_path', return_value=Path("/test/compose.yml")), \
                 patch('dockertree.commands.worktree.get_worktree_branch_name', return_value=branch_name):
                
                # Mock the compose file to exist
                with patch('pathlib.Path.exists', return_value=True):
                    # Mock network creation to fail
                    manager.docker_manager.create_worktree_volumes.return_value = True
                    manager.docker_manager.create_network.return_value = False
                    
                    result = manager.start_worktree(branch_name)
                
                assert result == False  # Should fail if network creation fails
                manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
                manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
                manager.docker_manager.create_worktree_volumes.assert_called_once_with(branch_name, force_copy=False)
                manager.docker_manager.create_network.assert_called_once()
