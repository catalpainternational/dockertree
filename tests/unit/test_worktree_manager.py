"""
Unit tests for WorktreeManager high-level functions.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from dockertree.commands.worktree import WorktreeManager


class TestWorktreeManager:
    """Test WorktreeManager high-level functions."""
    
    @pytest.fixture
    def worktree_manager(self, tmp_path):
        """Create WorktreeManager instance with mocked dependencies."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        
        with patch('dockertree.commands.worktree.DockerManager'), \
             patch('dockertree.commands.worktree.GitManager'), \
             patch('dockertree.commands.worktree.EnvironmentManager'), \
             patch('dockertree.commands.worktree.get_project_root', return_value=project_root):
            
            manager = WorktreeManager(project_root=project_root)
            manager.docker_manager = Mock()
            manager.git_manager = Mock()
            manager.env_manager = Mock()
            manager.project_root = project_root
            return manager
    
    def test_create_worktree_empty_branch_name(self, worktree_manager):
        """Test create_worktree with empty branch name."""
        result = worktree_manager.create_worktree("")
        assert result == False
    
    def test_create_worktree_none_branch_name(self, worktree_manager):
        """Test create_worktree with None branch name."""
        result = worktree_manager.create_worktree(None)
        assert result == False
    
    def test_create_worktree_existing_worktree(self, worktree_manager):
        """Test create_worktree when worktree already exists."""
        branch_name = "test-branch"
        worktree_path = worktree_manager.project_root / "worktrees" / "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = worktree_path
        
        result = worktree_manager.create_worktree(branch_name)
        
        assert result == True
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
    
    @patch('dockertree.commands.worktree.confirm_use_existing_worktree')
    def test_create_worktree_existing_worktree_user_confirms(self, mock_confirm, worktree_manager):
        """Test create_worktree when worktree exists and user confirms to use it."""
        branch_name = "test-branch"
        worktree_path = worktree_manager.project_root / "worktrees" / "test-branch"
        
        # Mock orchestrator to return already_exists status
        worktree_manager.orchestrator.create_worktree.return_value = {
            'success': True,
            'data': {
                'branch': branch_name,
                'worktree_path': str(worktree_path),
                'status': 'already_exists'
            }
        }
        mock_confirm.return_value = True  # User confirms
        
        result = worktree_manager.create_worktree(branch_name, interactive=True)
        
        assert result == True
        mock_confirm.assert_called_once_with(branch_name)
    
    @patch('dockertree.commands.worktree.confirm_use_existing_worktree')
    def test_create_worktree_existing_worktree_user_declines(self, mock_confirm, worktree_manager):
        """Test create_worktree when worktree exists and user declines to use it."""
        branch_name = "test-branch"
        worktree_path = worktree_manager.project_root / "worktrees" / "test-branch"
        
        # Mock orchestrator to return already_exists status
        worktree_manager.orchestrator.create_worktree.return_value = {
            'success': True,
            'data': {
                'branch': branch_name,
                'worktree_path': str(worktree_path),
                'status': 'already_exists'
            }
        }
        mock_confirm.return_value = False  # User declines
        
        result = worktree_manager.create_worktree(branch_name, interactive=True)
        
        assert result == False
        mock_confirm.assert_called_once_with(branch_name)
    
    def test_create_worktree_existing_worktree_non_interactive(self, worktree_manager):
        """Test create_worktree when worktree exists in non-interactive mode (JSON)."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktrees/test-branch")
        
        # Mock orchestrator to return already_exists status
        worktree_manager.orchestrator.create_worktree.return_value = {
            'success': True,
            'data': {
                'branch': branch_name,
                'worktree_path': str(worktree_path),
                'status': 'already_exists'
            }
        }
        
        result = worktree_manager.create_worktree(branch_name, interactive=False)
        
        assert result == True  # Should succeed without prompting in non-interactive mode
    
    def test_create_worktree_existing_worktree_not_found(self, worktree_manager):
        """Test create_worktree when worktree exists but path not found."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = None
        
        result = worktree_manager.create_worktree(branch_name)
        
        assert result == False
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
    
    def test_create_worktree_validation_fails(self, worktree_manager):
        """Test create_worktree when validation fails."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = False
        worktree_manager.git_manager.validate_worktree_creation.return_value = (False, "Validation failed")
        
        result = worktree_manager.create_worktree(branch_name)
        
        assert result == False
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.validate_worktree_creation.assert_called_once_with(branch_name)
    
    def test_create_worktree_branch_creation_fails(self, worktree_manager):
        """Test create_worktree when branch creation fails."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = False
        worktree_manager.git_manager.validate_worktree_creation.return_value = (True, "")
        worktree_manager.git_manager.create_branch.return_value = False
        
        result = worktree_manager.create_worktree(branch_name)
        
        assert result == False
        worktree_manager.git_manager.create_branch.assert_called_once_with(branch_name)
    
    @patch('dockertree.commands.worktree.WorktreeOrchestrator')
    def test_create_worktree_success(self, mock_orchestrator_class, worktree_manager):
        """Test successful worktree creation."""
        branch_name = "test-branch"
        new_path = worktree_manager.project_root / "worktrees" / "test-branch"
        
        # Mock orchestrator
        mock_orchestrator = Mock()
        mock_orchestrator.create_worktree.return_value = {
            'success': True,
            'data': {
                'branch': branch_name,
                'worktree_path': str(new_path),
                'status': 'created'
            }
        }
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result, result_data = worktree_manager.create_worktree(branch_name)
        
        assert result == True
        mock_orchestrator.create_worktree.assert_called_once_with(branch_name)
    
    def test_start_worktree_nonexistent_worktree(self, worktree_manager):
        """Test start_worktree with non-existent worktree."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = False
        
        result = worktree_manager.start_worktree(branch_name)
        
        assert result == False
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
    
    def test_start_worktree_path_not_found(self, worktree_manager):
        """Test start_worktree when worktree path cannot be resolved."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = None
        
        result = worktree_manager.start_worktree(branch_name)
        
        assert result == False
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
    
    @patch('pathlib.Path.exists')
    @patch('dockertree.commands.worktree.get_compose_override_path')
    @patch('dockertree.commands.worktree.get_worktree_branch_name')
    def test_start_worktree_compose_file_not_found(self, mock_get_branch, mock_get_compose, mock_exists, worktree_manager):
        """Test start_worktree when compose file doesn't exist."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktree")
        compose_override = Path("/test/compose.yml")
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = worktree_path
        mock_get_compose.return_value = compose_override
        mock_get_branch.return_value = branch_name
        mock_exists.return_value = False
        
        result = worktree_manager.start_worktree(branch_name)
        
        assert result == False
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
    
    @patch('pathlib.Path.exists')
    @patch('dockertree.commands.worktree.get_compose_override_path')
    @patch('dockertree.commands.worktree.get_worktree_branch_name')
    def test_start_worktree_success(self, mock_get_branch, mock_get_compose, mock_exists, worktree_manager):
        """Test successful worktree start."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktree")
        compose_override = Path("/test/compose.yml")
        compose_file = Path("/test/project/dockertree-cli/docker-compose.worktree.yml")
        env_file = worktree_path / ".dockertree" / "env.dockertree"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = worktree_path
        mock_get_compose.return_value = compose_override
        mock_get_branch.return_value = branch_name
        mock_exists.return_value = True
        worktree_manager.docker_manager.create_worktree_volumes.return_value = True
        worktree_manager.docker_manager.create_network.return_value = True
        worktree_manager.docker_manager.start_services.return_value = True
        
        result = worktree_manager.start_worktree(branch_name)
        
        assert result == True
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
        worktree_manager.docker_manager.create_worktree_volumes.assert_called_once_with(branch_name)
        worktree_manager.docker_manager.create_network.assert_called_once()
    
    def test_stop_worktree_nonexistent_worktree(self, worktree_manager):
        """Test stop_worktree with non-existent worktree."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = False
        
        result = worktree_manager.stop_worktree(branch_name)
        
        assert result == True  # Stop operations always return True for cleanup
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
    
    def test_stop_worktree_path_not_found(self, worktree_manager):
        """Test stop_worktree when worktree path cannot be resolved."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = None
        
        result = worktree_manager.stop_worktree(branch_name)
        
        assert result == True  # Stop operations always return True for cleanup
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
    
    @patch('pathlib.Path.exists')
    @patch('dockertree.commands.worktree.get_worktree_branch_name')
    def test_stop_worktree_success(self, mock_get_branch, mock_exists, worktree_manager):
        """Test successful worktree stop."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktree")
        compose_file = Path("/test/project/dockertree-cli/docker-compose.worktree.yml")
        env_file = worktree_path / ".dockertree" / "env.dockertree"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = worktree_path
        mock_get_branch.return_value = branch_name
        mock_exists.return_value = True
        worktree_manager.docker_manager.stop_services.return_value = True
        
        result = worktree_manager.stop_worktree(branch_name)
        
        assert result == True
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
    
    def test_remove_worktree_empty_branch_name(self, worktree_manager):
        """Test remove_worktree with empty branch name."""
        result = worktree_manager.remove_worktree("")
        assert result == False
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    def test_remove_worktree_worktree_not_exists(self, mock_ensure_main, worktree_manager):
        """Test remove_worktree when worktree doesn't exist."""
        branch_name = "test-branch"
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = False
        
        result = worktree_manager.remove_worktree(branch_name)
        
        assert result == False
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    @patch.object(WorktreeManager, 'stop_worktree')
    def test_remove_worktree_success(self, mock_stop_worktree, mock_ensure_main, worktree_manager):
        """Test successful worktree removal."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktrees/test-branch")
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = worktree_path
        mock_stop_worktree.return_value = True
        worktree_manager.docker_manager.remove_volumes.return_value = True
        worktree_manager.git_manager.remove_worktree.return_value = True
        worktree_manager.git_manager.delete_branch_safely.return_value = True
        
        result = worktree_manager.remove_worktree(branch_name)
        
        assert result == True
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
        mock_stop_worktree.assert_called_once_with(branch_name)
        worktree_manager.docker_manager.remove_volumes.assert_called_once_with(branch_name)
        worktree_manager.git_manager.remove_worktree.assert_called_once_with(worktree_path, force=True)
        worktree_manager.git_manager.delete_branch_safely.assert_called_once_with(branch_name, False)
    
    def test_list_worktrees(self, worktree_manager):
        """Test listing worktrees."""
        expected_worktrees = [
            ("/test/worktrees/branch1", "abc123", "branch1"),
            ("/test/worktrees/branch2", "def456", "branch2")
        ]
        
        worktree_manager.git_manager.list_worktrees.return_value = expected_worktrees
        
        result = worktree_manager.list_worktrees()
        
        assert result == expected_worktrees
        worktree_manager.git_manager.list_worktrees.assert_called_once()
    
    def test_prune_worktrees(self, worktree_manager):
        """Test pruning worktrees."""
        pruned_count = 2
        
        worktree_manager.git_manager.prune_worktrees.return_value = pruned_count
        
        result = worktree_manager.prune_worktrees()
        
        assert result == pruned_count
        worktree_manager.git_manager.prune_worktrees.assert_called_once()
    
    def test_get_worktree_info(self, worktree_manager):
        """Test getting worktree information."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktrees/test-branch")
        branch_info = {"status": "active"}
        volumes = {"postgres": "test-branch_postgres_data"}
        config = {"domain": "test-branch.localhost"}
        
        worktree_manager.git_manager.validate_worktree_exists.return_value = True
        worktree_manager.git_manager.find_worktree_path.return_value = worktree_path
        worktree_manager.git_manager.get_branch_info.return_value = branch_info
        worktree_manager.env_manager.get_worktree_volume_names.return_value = volumes
        worktree_manager.env_manager.get_worktree_config.return_value = config
        
        result = worktree_manager.get_worktree_info(branch_name)
        
        expected = {
            "branch_name": branch_name,
            "exists": True,
            "path": worktree_path,
            "branch_info": branch_info,
            "volumes": volumes,
            "config": config
        }
        
        assert result == expected
        worktree_manager.git_manager.validate_worktree_exists.assert_called_once_with(branch_name)
        worktree_manager.git_manager.find_worktree_path.assert_called_once_with(branch_name)
        worktree_manager.git_manager.get_branch_info.assert_called_once_with(branch_name)
        worktree_manager.env_manager.get_worktree_volume_names.assert_called_once_with(branch_name)
        worktree_manager.env_manager.get_worktree_config.assert_called_once_with(branch_name)
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    def test_remove_all_worktrees_no_worktrees(self, mock_ensure_main, worktree_manager):
        """Test remove_all_worktrees when no worktrees exist."""
        worktree_manager.git_manager.list_worktrees.return_value = []
        
        result = worktree_manager.remove_all_worktrees()
        
        assert result == True
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.list_worktrees.assert_called_once()
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    @patch.object(WorktreeManager, 'remove_worktree')
    def test_remove_all_worktrees_single_worktree_success(self, mock_remove_worktree, mock_ensure_main, worktree_manager):
        """Test remove_all_worktrees with single worktree success."""
        worktrees = [("/test/worktrees/branch1", "abc123", "branch1")]
        worktree_manager.git_manager.list_worktrees.return_value = worktrees
        mock_remove_worktree.return_value = True
        
        result = worktree_manager.remove_all_worktrees()
        
        assert result == True
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.list_worktrees.assert_called_once()
        mock_remove_worktree.assert_called_once_with("branch1", False, True)
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    @patch.object(WorktreeManager, 'remove_worktree')
    def test_remove_all_worktrees_multiple_worktrees_success(self, mock_remove_worktree, mock_ensure_main, worktree_manager):
        """Test remove_all_worktrees with multiple worktrees success."""
        worktrees = [
            ("/test/worktrees/branch1", "abc123", "branch1"),
            ("/test/worktrees/branch2", "def456", "branch2"),
            ("/test/worktrees/branch3", "ghi789", "branch3")
        ]
        worktree_manager.git_manager.list_worktrees.return_value = worktrees
        mock_remove_worktree.return_value = True
        
        result = worktree_manager.remove_all_worktrees()
        
        assert result == True
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.list_worktrees.assert_called_once()
        assert mock_remove_worktree.call_count == 3
        mock_remove_worktree.assert_any_call("branch1", False, True)
        mock_remove_worktree.assert_any_call("branch2", False, True)
        mock_remove_worktree.assert_any_call("branch3", False, True)
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    @patch.object(WorktreeManager, 'remove_worktree')
    def test_remove_all_worktrees_with_force_flag(self, mock_remove_worktree, mock_ensure_main, worktree_manager):
        """Test remove_all_worktrees with force flag."""
        worktrees = [("/test/worktrees/branch1", "abc123", "branch1")]
        worktree_manager.git_manager.list_worktrees.return_value = worktrees
        mock_remove_worktree.return_value = True
        
        result = worktree_manager.remove_all_worktrees(force=True)
        
        assert result == True
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.list_worktrees.assert_called_once()
        mock_remove_worktree.assert_called_once_with("branch1", True, True)
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    @patch.object(WorktreeManager, 'remove_worktree')
    def test_remove_all_worktrees_partial_failure(self, mock_remove_worktree, mock_ensure_main, worktree_manager):
        """Test remove_all_worktrees with partial failures."""
        worktrees = [
            ("/test/worktrees/branch1", "abc123", "branch1"),
            ("/test/worktrees/branch2", "def456", "branch2")
        ]
        worktree_manager.git_manager.list_worktrees.return_value = worktrees
        # First removal succeeds, second fails
        mock_remove_worktree.side_effect = [True, False]
        
        result = worktree_manager.remove_all_worktrees()
        
        assert result == False  # Should return False when not all succeed
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.list_worktrees.assert_called_once()
        assert mock_remove_worktree.call_count == 2
    
    @patch('dockertree.commands.worktree.ensure_main_repo')
    @patch.object(WorktreeManager, 'remove_worktree')
    def test_remove_all_worktrees_exception_handling(self, mock_remove_worktree, mock_ensure_main, worktree_manager):
        """Test remove_all_worktrees with exception handling."""
        worktrees = [("/test/worktrees/branch1", "abc123", "branch1")]
        worktree_manager.git_manager.list_worktrees.return_value = worktrees
        mock_remove_worktree.side_effect = Exception("Test exception")
        
        result = worktree_manager.remove_all_worktrees()
        
        assert result == False  # Should return False when exceptions occur
        mock_ensure_main.assert_called_once()
        worktree_manager.git_manager.list_worktrees.assert_called_once()
        mock_remove_worktree.assert_called_once_with("branch1", False, True)