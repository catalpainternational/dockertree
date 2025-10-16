"""
Unit tests for GitManager high-level functions.
"""

import pytest
import subprocess
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from dockertree.core.git_manager import GitManager


class TestGitManager:
    """Test GitManager high-level functions."""
    
    @pytest.fixture
    def git_manager(self):
        """Create GitManager instance with mocked dependencies."""
        with patch('dockertree.core.git_manager.subprocess.run'):
            manager = GitManager()
            return manager
    
    @patch('subprocess.run')
    def test_init_validation_success(self, mock_run):
        """Test GitManager initialization with valid git repo."""
        mock_run.return_value = Mock(returncode=0)
        
        # Should not raise an exception
        manager = GitManager()
        assert manager is not None
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            check=True,
            cwd=manager.project_root
        )
    
    @patch('subprocess.run')
    def test_init_validation_failure(self, mock_run):
        """Test GitManager initialization with invalid git repo."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Not a git repository")
        
        with pytest.raises(RuntimeError, match="Not in a git repository"):
            GitManager()
        
        # Get the project root from the manager that was created before the exception
        from dockertree.config.settings import get_project_root
        project_root = get_project_root()
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            check=True,
            cwd=project_root
        )
    
    @patch('dockertree.core.git_manager.validate_current_branch')
    def test_get_current_branch(self, mock_validate, git_manager):
        """Test getting current branch."""
        mock_validate.return_value = "main"
        
        result = git_manager.get_current_branch()
        
        assert result == "main"
        mock_validate.assert_called_once()
    
    @patch('dockertree.core.git_manager.validate_branch_exists')
    @patch('subprocess.run')
    def test_create_branch_already_exists(self, mock_run, mock_validate, git_manager):
        """Test creating branch that already exists."""
        branch_name = "existing-branch"
        mock_validate.return_value = True
        
        result = git_manager.create_branch(branch_name)
        
        assert result == True
        mock_validate.assert_called_once_with(branch_name)
        mock_run.assert_not_called()
    
    @patch('dockertree.core.git_manager.validate_branch_exists')
    @patch('subprocess.run')
    def test_create_branch_success(self, mock_run, mock_validate, git_manager):
        """Test successful branch creation."""
        branch_name = "new-branch"
        mock_validate.return_value = False
        mock_run.return_value = Mock(returncode=0)
        
        result = git_manager.create_branch(branch_name)
        
        assert result == True
        mock_validate.assert_called_once_with(branch_name)
        mock_run.assert_called_once_with(
            ["git", "branch", branch_name],
            capture_output=True,
            check=True,
            cwd=git_manager.project_root
        )
    
    @patch('dockertree.core.git_manager.validate_branch_exists')
    @patch('subprocess.run')
    def test_create_branch_failure(self, mock_run, mock_validate, git_manager):
        """Test branch creation failure."""
        branch_name = "new-branch"
        mock_validate.return_value = False
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Branch creation failed")
        
        result = git_manager.create_branch(branch_name)
        
        assert result == False
        mock_validate.assert_called_once_with(branch_name)
        mock_run.assert_called_once_with(
            ["git", "branch", branch_name],
            capture_output=True,
            check=True,
            cwd=git_manager.project_root
        )
    
    @patch('dockertree.core.git_manager.validate_branch_exists')
    @patch('subprocess.run')
    def test_create_worktree_branch_creation(self, mock_run, mock_validate, git_manager):
        """Test worktree creation with branch creation."""
        branch_name = "new-branch"
        worktree_path = Path("/test/worktrees/new-branch")
        
        mock_validate.return_value = False
        mock_run.return_value = Mock(returncode=0)
        
        # Mock path operations
        with patch.object(Path, 'mkdir', return_value=None):
            result = git_manager.create_worktree(branch_name, worktree_path)
        
        assert result == True
        assert mock_run.call_count == 2  # create branch + create worktree
        mock_validate.assert_called_once_with(branch_name)
    
    @patch('dockertree.core.git_manager.validate_branch_exists')
    @patch('subprocess.run')
    def test_create_worktree_existing_branch(self, mock_run, mock_validate, git_manager):
        """Test worktree creation with existing branch."""
        branch_name = "existing-branch"
        worktree_path = Path("/test/worktrees/existing-branch")
        
        mock_validate.return_value = True
        mock_run.return_value = Mock(returncode=0)
        
        # Mock path operations
        with patch.object(Path, 'mkdir', return_value=None):
            result = git_manager.create_worktree(branch_name, worktree_path)
        
        assert result == True
        assert mock_run.call_count == 1  # only create worktree
        mock_validate.assert_called_once_with(branch_name)
    
    @patch('subprocess.run')
    def test_create_worktree_failure(self, mock_run, git_manager):
        """Test worktree creation failure."""
        branch_name = "test-branch"
        worktree_path = Path("/test/worktrees/test-branch")
        
        # Mock validate_branch_exists call and worktree creation failure
        mock_run.side_effect = [
            Mock(returncode=0),  # validate_branch_exists
            subprocess.CalledProcessError(1, "git", "Worktree creation failed")  # worktree creation
        ]
        
        # Mock path operations
        with patch.object(Path, 'mkdir', return_value=None):
            result = git_manager.create_worktree(branch_name, worktree_path)
        
        assert result == False
        assert mock_run.call_count == 2
    
    @patch('subprocess.run')
    def test_remove_worktree_success(self, mock_run, git_manager):
        """Test successful worktree removal."""
        worktree_path = Path("/test/worktrees/test-branch")
        mock_run.return_value = Mock(returncode=0)
        
        result = git_manager.remove_worktree(worktree_path)
        
        assert result == True
        mock_run.assert_called_once_with(
            ["git", "worktree", "remove", str(worktree_path)],
            capture_output=True,
            check=True,
            cwd=git_manager.project_root
        )
    
    @patch('subprocess.run')
    def test_remove_worktree_with_force(self, mock_run, git_manager):
        """Test worktree removal with force flag."""
        worktree_path = Path("/test/worktrees/test-branch")
        mock_run.return_value = Mock(returncode=0)
        
        result = git_manager.remove_worktree(worktree_path, force=True)
        
        assert result == True
        mock_run.assert_called_once_with(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            capture_output=True,
            check=True,
            cwd=git_manager.project_root
        )
    
    @patch('subprocess.run')
    def test_remove_worktree_failure(self, mock_run, git_manager):
        """Test worktree removal failure."""
        worktree_path = Path("/test/worktrees/test-branch")
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Worktree removal failed")
        
        result = git_manager.remove_worktree(worktree_path)
        
        assert result == False
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_list_worktrees_success(self, mock_run, git_manager):
        """Test successful worktree listing."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="/test/worktrees/branch1 abc123 [branch1]\n/test/worktrees/branch2 def456 [branch2]"
        )
        
        result = git_manager.list_worktrees()
        
        expected = [
            ("/test/worktrees/branch1", "abc123", "branch1"),
            ("/test/worktrees/branch2", "def456", "branch2")
        ]
        assert result == expected
        mock_run.assert_called_once_with(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
            check=True,
            cwd=git_manager.project_root
        )
    
    @patch('subprocess.run')
    def test_list_worktrees_failure(self, mock_run, git_manager):
        """Test worktree listing failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Worktree listing failed")
        
        result = git_manager.list_worktrees()
        
        assert result == []
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_prune_worktrees_success(self, mock_run, git_manager):
        """Test successful worktree pruning."""
        # Mock worktree list with no prunable worktrees
        mock_run.return_value = Mock(returncode=0, stdout="")
        
        result = git_manager.prune_worktrees()
        
        assert result == 0  # No prunable worktrees
        assert mock_run.call_count == 1
    
    @patch('subprocess.run')
    def test_prune_worktrees_failure(self, mock_run, git_manager):
        """Test worktree pruning failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Worktree pruning failed")
        
        result = git_manager.prune_worktrees()
        
        assert result == 0  # Should return 0 on failure
        mock_run.assert_called_once()
    
    @patch('dockertree.core.git_manager.validate_worktree_exists')
    def test_validate_worktree_exists_true(self, mock_validate, git_manager):
        """Test worktree existence validation when worktree exists."""
        branch_name = "test-branch"
        mock_validate.return_value = True
        
        result = git_manager.validate_worktree_exists(branch_name)
        
        assert result == True
        mock_validate.assert_called_once_with(branch_name)
    
    @patch('dockertree.core.git_manager.validate_worktree_exists')
    def test_validate_worktree_exists_false(self, mock_validate, git_manager):
        """Test worktree existence validation when worktree doesn't exist."""
        branch_name = "test-branch"
        mock_validate.return_value = False
        
        result = git_manager.validate_worktree_exists(branch_name)
        
        assert result == False
        mock_validate.assert_called_once_with(branch_name)
    
    @patch('subprocess.run')
    def test_find_worktree_path_success(self, mock_run, git_manager):
        """Test finding worktree path when worktree exists."""
        branch_name = "test-branch"
        mock_run.return_value = Mock(
            returncode=0,
            stdout="/test/worktrees/test-branch abc123 [test-branch]"
        )
        
        result = git_manager.find_worktree_path(branch_name)
        
        assert result == Path("/test/worktrees/test-branch")
        mock_run.assert_called_once_with(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
            check=True,
            cwd=git_manager.project_root
        )
    
    @patch('subprocess.run')
    def test_find_worktree_path_not_found(self, mock_run, git_manager):
        """Test finding worktree path when worktree doesn't exist."""
        branch_name = "nonexistent-branch"
        mock_run.return_value = Mock(
            returncode=0,
            stdout="/test/worktrees/other-branch abc123 [other-branch]"
        )
        
        result = git_manager.find_worktree_path(branch_name)
        
        assert result is None
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_find_worktree_path_failure(self, mock_run, git_manager):
        """Test finding worktree path when git command fails."""
        branch_name = "test-branch"
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Git command failed")
        
        result = git_manager.find_worktree_path(branch_name)
        
        assert result is None
        mock_run.assert_called_once()
    
    @patch('dockertree.core.git_manager.validate_branch_protection')
    @patch('dockertree.core.git_manager.validate_current_branch')
    @patch('dockertree.core.git_manager.validate_branch_exists')
    def test_validate_worktree_creation_success(self, mock_exists, mock_current, mock_protection, git_manager):
        """Test worktree creation validation success."""
        branch_name = "test-branch"
        
        mock_exists.return_value = True
        mock_current.return_value = "main"
        mock_protection.return_value = False
        
        can_create, error_msg = git_manager.validate_worktree_creation(branch_name)
        
        assert can_create == True
        assert error_msg == ""
        mock_exists.assert_called_once_with(branch_name)
        mock_current.assert_called_once()
        mock_protection.assert_called_once_with(branch_name)
    
    @patch('dockertree.core.git_manager.validate_branch_protection')
    @patch('dockertree.core.git_manager.validate_current_branch')
    @patch('dockertree.core.git_manager.validate_branch_exists')
    def test_validate_worktree_creation_protected_branch(self, mock_exists, mock_current, mock_protection, git_manager):
        """Test worktree creation validation with protected branch."""
        branch_name = "main"
        
        mock_exists.return_value = True
        mock_current.return_value = "develop"
        mock_protection.return_value = True
        
        can_create, error_msg = git_manager.validate_worktree_creation(branch_name)
        
        assert can_create == False
        assert "protected branch" in error_msg.lower()
        mock_protection.assert_called_once_with(branch_name)
    
    @patch('dockertree.core.git_manager.validate_branch_protection')
    @patch('dockertree.core.git_manager.validate_current_branch')
    @patch('dockertree.core.git_manager.validate_branch_exists')
    def test_validate_worktree_creation_current_branch(self, mock_exists, mock_current, mock_protection, git_manager):
        """Test worktree creation validation with current branch."""
        branch_name = "test-branch"
        
        mock_exists.return_value = True
        mock_current.return_value = "test-branch"
        mock_protection.return_value = False
        
        can_create, error_msg = git_manager.validate_worktree_creation(branch_name)
        
        assert can_create == False
        assert "current branch" in error_msg.lower()
        mock_current.assert_called_once()
    
    @patch('dockertree.core.git_manager.validate_branch_merged')
    @patch('dockertree.core.git_manager.validate_branch_protection')
    @patch('subprocess.run')
    def test_delete_branch_safely_merged(self, mock_run, mock_protection, mock_merged, git_manager):
        """Test safe branch deletion when branch is merged."""
        branch_name = "merged-branch"
        
        mock_protection.return_value = False
        mock_merged.return_value = True
        # Mock get_current_branch call, validate_branch_merged call, and delete branch call
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main"),  # get_current_branch
            Mock(returncode=0),  # validate_branch_merged (git branch -d)
            Mock(returncode=0)  # delete branch with -d
        ]
        
        result = git_manager.delete_branch_safely(branch_name)
        
        assert result == True
        mock_protection.assert_called_once_with(branch_name)
        mock_merged.assert_called_once_with(branch_name)
        assert mock_run.call_count == 3
    
    @patch('dockertree.core.git_manager.validate_branch_protection')
    @patch('subprocess.run')
    def test_delete_branch_safely_protected(self, mock_run, mock_protection, git_manager):
        """Test safe branch deletion with protected branch."""
        branch_name = "main"
        
        mock_protection.return_value = True
        # Mock validate_branch_exists call and get_current_branch call
        mock_run.side_effect = [
            Mock(returncode=0),  # validate_branch_exists
            Mock(returncode=0, stdout="other-branch")  # get_current_branch
        ]
        
        result = git_manager.delete_branch_safely(branch_name)
        
        assert result == False
        mock_protection.assert_called_once_with(branch_name)
        # validate_branch_exists and get_current_branch are called
        assert mock_run.call_count == 2
    
    @patch('dockertree.core.git_manager.validate_branch_merged')
    @patch('dockertree.core.git_manager.validate_branch_protection')
    @patch('subprocess.run')
    def test_delete_branch_safely_force(self, mock_run, mock_protection, mock_merged, git_manager):
        """Test safe branch deletion with force flag."""
        branch_name = "unmerged-branch"
        
        mock_protection.return_value = False
        mock_merged.return_value = False
        # Mock get_current_branch call, delete with -d (fails), delete with -D (succeeds)
        mock_run.side_effect = [
            Mock(returncode=0, stdout="other-branch"),  # get_current_branch
            subprocess.CalledProcessError(1, "git", "Not merged"),  # delete with -d fails
            Mock(returncode=0)  # delete with -D succeeds
        ]
        
        result = git_manager.delete_branch_safely(branch_name, force=True)
        
        assert result == True
        mock_protection.assert_called_once_with(branch_name)
        # validate_branch_merged is not called when force=True
        mock_merged.assert_not_called()
        # get_current_branch is called, then delete with -d, then delete with -D
        assert mock_run.call_count == 3
    
    @patch('subprocess.run')
    def test_get_branch_info_success(self, mock_run, git_manager):
        """Test getting branch information."""
        branch_name = "test-branch"
        # Mock multiple calls: log, show-ref (protection), show-ref (merged), worktree list
        mock_run.side_effect = [
            Mock(returncode=0, stdout="abc123 Test commit message"),  # log
            Mock(returncode=0),  # protection check
            Mock(returncode=0),  # merged check  
            Mock(returncode=0, stdout="")  # worktree list
        ]
        
        result = git_manager.get_branch_info(branch_name)
        
        assert result["commit"] == "abc123"
        assert result["message"] == "Test commit message"
        assert mock_run.call_count == 4
    
    @patch('subprocess.run')
    def test_get_branch_info_failure(self, mock_run, git_manager):
        """Test getting branch information when branch doesn't exist."""
        branch_name = "nonexistent-branch"
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", "Branch not found")
        
        result = git_manager.get_branch_info(branch_name)
        
        assert result is None
        mock_run.assert_called_once()
