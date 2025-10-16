"""
Unit tests for DockerManager high-level functions.
"""

import pytest
import subprocess
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from dockertree.core.docker_manager import DockerManager


class TestDockerManager:
    """Test DockerManager high-level functions."""
    
    @pytest.fixture
    def docker_manager(self):
        """Create DockerManager instance with mocked dependencies."""
        with patch('dockertree.core.docker_manager.validate_docker_running'), \
             patch('dockertree.core.docker_manager.get_compose_command'):
            
            manager = DockerManager()
            manager.compose_cmd = "docker compose"
            return manager
    
    @patch('subprocess.run')
    @patch('dockertree.core.docker_manager.validate_network_exists')
    def test_create_network_success(self, mock_validate, mock_run, docker_manager):
        """Test successful network creation."""
        network_name = "test-network"
        mock_validate.return_value = False  # Network doesn't exist
        mock_run.return_value = Mock(returncode=0)
        
        result = docker_manager.create_network(network_name)
        
        assert result == True
        mock_validate.assert_called_once_with(network_name)
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    @patch('dockertree.core.docker_manager.validate_network_exists')
    def test_create_network_failure(self, mock_validate, mock_run, docker_manager):
        """Test network creation failure."""
        network_name = "test-network"
        mock_validate.return_value = False  # Network doesn't exist
        mock_run.side_effect = Exception("Network creation failed")
        
        result = docker_manager.create_network(network_name)
        
        assert result == False
        mock_validate.assert_called_once_with(network_name)
        mock_run.assert_called_once()
    
    @patch('dockertree.core.docker_manager.validate_volume_exists')
    @patch('subprocess.run')
    def test_copy_volume_source_not_exists(self, mock_run, mock_validate, docker_manager):
        """Test copy_volume when source volume doesn't exist."""
        source_volume = "source-volume"
        target_volume = "target-volume"
        
        mock_validate.return_value = False
        mock_run.return_value = Mock(returncode=0)
        
        result = docker_manager.copy_volume(source_volume, target_volume)
        
        assert result == True
        mock_validate.assert_called_once_with(source_volume)
        mock_run.assert_called_once_with(
            ["docker", "volume", "create", target_volume],
            check=True,
            capture_output=True
        )
    
    @patch('dockertree.core.docker_manager.validate_volume_exists')
    @patch('subprocess.run')
    def test_copy_volume_success(self, mock_run, mock_validate, docker_manager):
        """Test successful volume copy."""
        source_volume = "source-volume"
        target_volume = "target-volume"
        
        mock_validate.return_value = True
        mock_run.return_value = Mock(returncode=0)
        
        result = docker_manager.copy_volume(source_volume, target_volume)
        
        assert result == True
        mock_validate.assert_called_once_with(source_volume)
        assert mock_run.call_count == 2  # create target volume + copy data
    
    @patch('dockertree.core.docker_manager.validate_volume_exists')
    @patch('subprocess.run')
    def test_copy_volume_copy_failure(self, mock_run, mock_validate, docker_manager):
        """Test volume copy with copy operation failure."""
        source_volume = "source-volume"
        target_volume = "target-volume"
        
        mock_validate.return_value = True
        # First call (create volume) succeeds, second call (copy) fails
        mock_run.side_effect = [Mock(returncode=0), Exception("Copy failed")]
        
        with pytest.raises(Exception, match="Copy failed"):
            docker_manager.copy_volume(source_volume, target_volume)
        
        mock_validate.assert_called_once_with(source_volume)
    
    @patch('dockertree.core.docker_manager.get_volume_names')
    @patch.object(DockerManager, 'copy_volume')
    def test_create_worktree_volumes_success(self, mock_copy_volume, mock_get_volume_names, docker_manager):
        """Test successful worktree volume creation.
        
        Note: Only postgres, redis, and media volumes are created.
        Caddy volumes are shared globally and not per-worktree.
        """
        branch_name = "test-branch"
        project_name = "test-project"
        
        mock_get_volume_names.return_value = {
            "postgres": "test-branch_postgres_data",
            "redis": "test-branch_redis_data",
            "media": "test-branch_media_files",
        }
        mock_copy_volume.return_value = True
        
        result = docker_manager.create_worktree_volumes(branch_name, project_name)
        
        assert result == True
        mock_get_volume_names.assert_called_once_with(branch_name)
        assert mock_copy_volume.call_count == 3  # One for each volume type (postgres, redis, media)
    
    @patch('dockertree.core.docker_manager.get_volume_names')
    @patch.object(DockerManager, 'copy_volume')
    def test_create_worktree_volumes_partial_failure(self, mock_copy_volume, mock_get_volume_names, docker_manager):
        """Test worktree volume creation with partial failure."""
        branch_name = "test-branch"
        project_name = "test-project"
        
        mock_get_volume_names.return_value = {
            "postgres": "test-branch_postgres_data",
            "redis": "test-branch_redis_data",
            "media": "test-branch_media_files",
        }
        # First two succeed, third fails
        mock_copy_volume.side_effect = [True, True, False]
        
        result = docker_manager.create_worktree_volumes(branch_name, project_name)
        
        assert result == False
        mock_get_volume_names.assert_called_once_with(branch_name)
        assert mock_copy_volume.call_count == 3
    
    @patch('dockertree.core.docker_manager.get_volume_names')
    @patch('dockertree.core.docker_manager.validate_volume_exists')
    @patch('subprocess.run')
    def test_remove_volumes_success(self, mock_run, mock_validate, mock_get_volume_names, docker_manager):
        """Test successful volume removal.
        
        Note: Only removes postgres, redis, and media volumes.
        Caddy volumes are shared globally and not removed per-worktree.
        """
        branch_name = "test-branch"
        
        mock_get_volume_names.return_value = {
            "postgres": "test-branch_postgres_data",
            "redis": "test-branch_redis_data",
            "media": "test-branch_media_files",
        }
        mock_validate.return_value = True
        mock_run.return_value = Mock(returncode=0)
        
        result = docker_manager.remove_volumes(branch_name)
        
        assert result == True
        mock_get_volume_names.assert_called_once_with(branch_name)
        assert mock_validate.call_count == 3
        assert mock_run.call_count == 3
    
    @patch('dockertree.core.docker_manager.get_volume_names')
    @patch('dockertree.core.docker_manager.validate_volume_exists')
    @patch('subprocess.run')
    def test_remove_volumes_partial_failure(self, mock_run, mock_validate, mock_get_volume_names, docker_manager):
        """Test volume removal with partial failure."""
        branch_name = "test-branch"
        
        mock_get_volume_names.return_value = {
            "postgres": "test-branch_postgres_data",
            "redis": "test-branch_redis_data",
            "media": "test-branch_media_files",
        }
        mock_validate.return_value = True
        # First two succeed, third fails with CalledProcessError
        mock_run.side_effect = [Mock(returncode=0), Mock(returncode=0), subprocess.CalledProcessError(1, "docker", "Remove failed")]
        
        result = docker_manager.remove_volumes(branch_name)
        
        assert result == False
        mock_get_volume_names.assert_called_once_with(branch_name)
        assert mock_validate.call_count == 3
        assert mock_run.call_count == 3
    
    @patch('dockertree.core.docker_manager.get_volume_names')
    @patch('subprocess.run')
    def test_backup_volumes_success(self, mock_run, mock_get_volume_names, docker_manager):
        """Test successful volume backup."""
        branch_name = "test-branch"
        backup_dir = Path("/test/backups")
        
        mock_get_volume_names.return_value = {
            "postgres": "test-branch_postgres_data",
            "redis": "test-branch_redis_data",
            "media": "test-branch_media_files",
        }
        mock_run.return_value = Mock(returncode=0)
        
        # Mock the backup file creation
        with patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.unlink'), \
             patch('shutil.rmtree'):
            
            result = docker_manager.backup_volumes(branch_name, backup_dir)
        
        assert result is not None
        assert result.name.startswith("backup_test-branch_")
        assert result.suffix == ".tar"
        mock_get_volume_names.assert_called_once_with(branch_name)
    
    @patch('dockertree.core.docker_manager.get_volume_names')
    @patch('subprocess.run')
    def test_restore_volumes_success(self, mock_run, mock_get_volume_names, docker_manager):
        """Test successful volume restore."""
        branch_name = "test-branch"
        backup_file = Path("/test/backup.tar")
        
        mock_get_volume_names.return_value = {
            "postgres": "test-branch_postgres_data",
            "redis": "test-branch_redis_data",
            "media": "test-branch_media_files",
        }
        mock_run.return_value = Mock(returncode=0)
        
        # Mock the restore process
        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.unlink'), \
             patch('pathlib.Path.mkdir'), \
             patch('shutil.rmtree'):
            
            result = docker_manager.restore_volumes(branch_name, backup_file)
        
        assert result == True
        mock_get_volume_names.assert_called_once_with(branch_name)
    
    @patch('subprocess.run')
    def test_start_services_success(self, mock_run, docker_manager):
        """Test successful service start."""
        compose_file = Path("/test/docker-compose.yml")
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test-project"
        
        mock_run.return_value = Mock(returncode=0)
        
        # Mock the env_file.exists() to return True
        with patch.object(Path, 'exists', return_value=True):
            result = docker_manager.start_services(compose_file, env_file, project_name)
        
        assert result == True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "compose" in call_args
        assert "--env-file" in call_args
        assert str(env_file) in call_args
        assert "-f" in call_args
        assert str(compose_file) in call_args
        assert "up" in call_args
        assert "-d" in call_args
    
    @patch('subprocess.run')
    def test_start_services_failure(self, mock_run, docker_manager):
        """Test service start failure."""
        compose_file = Path("/test/docker-compose.yml")
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test-project"
        
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker", "Service start failed")
        
        result = docker_manager.start_services(compose_file, env_file, project_name)
        
        assert result == False
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_stop_services_success(self, mock_run, docker_manager):
        """Test successful service stop."""
        compose_file = Path("/test/docker-compose.yml")
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test-project"
        
        mock_run.return_value = Mock(returncode=0)
        
        # Mock the env_file.exists() to return True
        with patch.object(Path, 'exists', return_value=True):
            result = docker_manager.stop_services(compose_file, env_file, project_name)
        
        assert result == True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "compose" in call_args
        assert "--env-file" in call_args
        assert str(env_file) in call_args
        assert "-f" in call_args
        assert str(compose_file) in call_args
        assert "down" in call_args
    
    @patch('subprocess.run')
    def test_stop_services_failure(self, mock_run, docker_manager):
        """Test service stop failure."""
        compose_file = Path("/test/docker-compose.yml")
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test-project"
        
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker", "Service stop failed")
        
        result = docker_manager.stop_services(compose_file, env_file, project_name)
        
        assert result == False
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_run_compose_command_success(self, mock_run, docker_manager):
        """Test successful compose command execution."""
        compose_file = Path("/test/docker-compose.yml")
        command = ["config"]
        project_name = "test-project"
        
        mock_run.return_value = Mock(returncode=0)
        
        result = docker_manager.run_compose_command(compose_file, command, None, project_name)
        
        assert result == True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "docker" in call_args
        assert "compose" in call_args
        assert "-f" in call_args
        assert str(compose_file) in call_args
        assert "config" in call_args
    
    @patch('subprocess.run')
    def test_run_compose_command_failure(self, mock_run, docker_manager):
        """Test compose command execution failure."""
        compose_file = Path("/test/docker-compose.yml")
        command = ["config"]
        project_name = "test-project"
        
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker", "Compose command failed")
        
        result = docker_manager.run_compose_command(compose_file, command, None, project_name)
        
        assert result == False
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_list_volumes_success(self, mock_run, docker_manager):
        """Test successful volume listing."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="test-branch_postgres_data\ntest-branch_redis_data\n"
        )
        
        result = docker_manager.list_volumes()
        
        assert result == ["test-branch_postgres_data", "test-branch_redis_data"]
        mock_run.assert_called_once_with(
            ["docker", "volume", "ls", "-q"],
            capture_output=True,
            text=True,
            check=True
        )
    
    @patch('subprocess.run')
    def test_list_volumes_failure(self, mock_run, docker_manager):
        """Test volume listing failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker", "Volume listing failed")
        
        result = docker_manager.list_volumes()
        
        assert result == []
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_get_volume_sizes_success(self, mock_run, docker_manager):
        """Test successful volume size retrieval."""
        # First call returns volume list, subsequent calls return size for each volume
        mock_run.side_effect = [
            Mock(returncode=0, stdout="test-volume_postgres_data\ntest-volume_redis_data"),
            Mock(returncode=0, stdout="1.2GB\t/data"),
            Mock(returncode=0, stdout="800MB\t/data")
        ]
        
        result = docker_manager.get_volume_sizes()
        
        assert "test-volume_postgres_data" in result
        assert result["test-volume_postgres_data"] == "1.2GB"
        assert mock_run.call_count == 3
    
    @patch('subprocess.run')
    def test_get_volume_sizes_failure(self, mock_run, docker_manager):
        """Test volume size retrieval failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "docker", "Volume size retrieval failed")
        
        # Mock list_volumes to return test volumes
        with patch.object(docker_manager, 'list_volumes', return_value=["test-volume"]):
            result = docker_manager.get_volume_sizes()
        
        assert result == {}
        mock_run.assert_called_once()
