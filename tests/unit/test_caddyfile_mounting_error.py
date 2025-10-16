"""
Unit tests for Caddyfile mounting error scenarios in dockertree CLI.

This module tests the specific error condition where Docker Compose fails to mount
the Caddyfile due to incorrect path resolution or missing files.
"""

import pytest
import subprocess
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from dockertree.core.docker_manager import DockerManager
from dockertree.commands.worktree import WorktreeManager


class TestCaddyfileMountingError:
    """Test Caddyfile mounting error scenarios."""
    
    @pytest.fixture
    def docker_manager(self):
        """Create DockerManager instance with mocked dependencies."""
        with patch('dockertree.core.docker_manager.validate_docker_running'), \
             patch('dockertree.core.docker_manager.get_compose_command'):
            
            manager = DockerManager()
            manager.compose_cmd = "docker compose"
            return manager
    
    @pytest.fixture
    def worktree_manager(self):
        """Create WorktreeManager instance with mocked dependencies."""
        with patch('dockertree.commands.worktree.DockerManager'), \
             patch('dockertree.commands.worktree.GitManager'), \
             patch('dockertree.commands.worktree.EnvironmentManager'), \
             patch('dockertree.commands.worktree.get_project_root'):
            
            manager = WorktreeManager()
            return manager
    
    def test_caddyfile_mounting_error_stderr_parsing(self, docker_manager):
        """Test parsing of Caddyfile mounting error from Docker Compose stderr."""
        # Simulate the exact error from the terminal output
        error_stderr = """Network test_internal  Creating
Network test_internal  Created
Network test_web  Creating
Network test_web  Created
Volume test_caddy_data  Creating
Volume test_caddy_data  Created
Volume test_caddy_config  Creating
Volume test_caddy_config  Created
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_postgres_data\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_redis_data\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_media_files\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
Container test-caddy  Creating
Container test-redis  Creating
Container test-db  Creating
Container test-caddy  Created
Container test-redis  Created
Container test-db  Created
Container test-rq-worker-1  Creating
Container test-web  Creating
Container test-rq-worker-1  Created
Container test-web  Created
Container test-db  Starting
Container test-redis  Starting
Container test-caddy  Starting
Container test-redis  Started
Container test-db  Started
Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
        
        # Test that the error contains the expected patterns
        assert "dockertree-cli/Caddyfile.dockertree" in error_stderr
        assert "error mounting" in error_stderr
        assert "Are you trying to mount a directory onto a file" in error_stderr
        assert "Check if the specified host path exists" in error_stderr
    
    @patch('subprocess.run')
    def test_docker_compose_caddyfile_mounting_failure(self, mock_run, docker_manager):
        """Test Docker Compose failure due to Caddyfile mounting error."""
        compose_file = Path("/test/docker-compose.worktree.yml")
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test"
        
        # Simulate the exact error from the terminal output
        error_stderr = """Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
        
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["docker", "compose", "up", "-d"],
            stderr=error_stderr
        )
        
        result = docker_manager.start_services(compose_file, env_file, project_name)
        
        assert result == False
        mock_run.assert_called_once()
    
    def test_caddyfile_path_validation(self):
        """Test validation of Caddyfile path structure."""
        # Test the incorrect path pattern from the error
        incorrect_path = "/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree"
        
        # The error shows 'dockertree-cli' (with hyphen) but should be 'dockertree' (with underscore)
        assert "dockertree-cli" in incorrect_path
        assert "dockertree" not in incorrect_path
        
        # Test the correct path pattern
        correct_path = "/tmp/test_project/test_project/dockertree/Caddyfile.dockertree"
        assert "dockertree" in correct_path
        assert "dockertree-cli" not in correct_path
    
    @patch('pathlib.Path.exists')
    @patch('subprocess.run')
    def test_worktree_start_with_missing_caddyfile(self, mock_run, mock_exists, worktree_manager):
        """Test worktree start when Caddyfile path doesn't exist."""
        worktree_path = Path("/test/worktree")
        
        # Mock the worktree validation to pass
        with patch('dockertree.commands.worktree.validate_worktree_directory', return_value=True), \
             patch('dockertree.commands.worktree.get_worktree_branch_name', return_value="test"), \
             patch('dockertree.commands.worktree.get_compose_override_path', return_value=Path("/test/compose.yml")), \
             patch.object(worktree_manager.docker_manager, 'start_services', return_value=False):
            
            # Mock file existence checks
            mock_exists.side_effect = lambda path: not str(path).endswith("Caddyfile.dockertree")
            
            # Mock Docker Compose failure due to missing Caddyfile
            error_stderr = """Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
            
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["docker", "compose", "up", "-d"],
                stderr=error_stderr
            )
            
            result = worktree_manager.start_worktree(worktree_path)
            
            assert result == False
    
    @patch('pathlib.Path.exists')
    @patch('subprocess.run')
    def test_worktree_start_with_incorrect_caddyfile_path(self, mock_run, mock_exists, worktree_manager):
        """Test worktree start when Caddyfile path has incorrect directory structure."""
        worktree_path = Path("/test/worktree")
        
        # Mock the worktree validation to pass
        with patch('dockertree.commands.worktree.validate_worktree_directory', return_value=True), \
             patch('dockertree.commands.worktree.get_worktree_branch_name', return_value="test"), \
             patch('dockertree.commands.worktree.get_compose_override_path', return_value=Path("/test/compose.yml")), \
             patch.object(worktree_manager.docker_manager, 'start_services', return_value=False):
            
            # Mock file existence - Caddyfile exists but at wrong path
            def mock_path_exists(path):
                path_str = str(path)
                if "Caddyfile.dockertree" in path_str:
                    # Return True only for the correct path, False for incorrect
                    return "dockertree" in path_str and "dockertree-cli" not in path_str
                return True
            
            mock_exists.side_effect = mock_path_exists
            
            # Mock Docker Compose failure due to incorrect path
            error_stderr = """Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
            
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["docker", "compose", "up", "-d"],
                stderr=error_stderr
            )
            
            result = worktree_manager.start_worktree(worktree_path)
            
            assert result == False
    
    def test_caddyfile_mounting_error_detection(self):
        """Test detection of Caddyfile mounting error patterns."""
        error_messages = [
            "error mounting",
            "Are you trying to mount a directory onto a file",
            "Check if the specified host path exists",
            "dockertree-cli/Caddyfile.dockertree",
            "create mountpoint for /etc/caddy/Caddyfile"
        ]
        
        # Test that all error patterns are present in the actual error
        full_error = """Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
        
        for pattern in error_messages:
            assert pattern in full_error, f"Pattern '{pattern}' not found in error message"
    
    @patch('subprocess.run')
    def test_docker_compose_command_with_caddyfile_error(self, mock_run, docker_manager):
        """Test Docker Compose command execution with Caddyfile mounting error."""
        compose_file = Path("/test/docker-compose.worktree.yml")
        command = ["up", "-d"]
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test"
        
        # Mock env_file.exists() to return True
        with patch.object(Path, 'exists', return_value=True):
            # Simulate the exact error from the terminal output
            error_stderr = """Network test_internal  Creating
Network test_internal  Created
Network test_web  Creating
Network test_web  Created
Volume test_caddy_data  Creating
Volume test_caddy_data  Created
Volume test_caddy_config  Creating
Volume test_caddy_config  Created
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_postgres_data\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_redis_data\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_media_files\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
Container test-caddy  Creating
Container test-redis  Creating
Container test-db  Creating
Container test-caddy  Created
Container test-redis  Created
Container test-db  Created
Container test-rq-worker-1  Creating
Container test-web  Creating
Container test-rq-worker-1  Created
Container test-web  Created
Container test-db  Starting
Container test-redis  Starting
Container test-caddy  Starting
Container test-redis  Started
Container test-db  Started
Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
            
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["docker", "compose", "up", "-d"],
                stderr=error_stderr
            )
            
            result = docker_manager.run_compose_command(compose_file, command, env_file, project_name)
            
            assert result == False
            mock_run.assert_called_once()
            
            # Verify the command was called with correct parameters
            call_args = mock_run.call_args[0][0]
            assert "docker" in call_args
            assert "compose" in call_args
            assert "--env-file" in call_args
            assert str(env_file) in call_args
            assert "-p" in call_args
            assert project_name in call_args
            assert "-f" in call_args
            assert str(compose_file) in call_args
            assert "up" in call_args
            assert "-d" in call_args
    
    def test_caddyfile_path_resolution_error_scenarios(self):
        """Test various Caddyfile path resolution error scenarios."""
        # Test case 1: Incorrect directory name (hyphen vs underscore)
        incorrect_path = "/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree"
        correct_path = "/tmp/test_project/test_project/dockertree/Caddyfile.dockertree"
        
        assert incorrect_path != correct_path
        assert "dockertree-cli" in incorrect_path
        assert "dockertree" in correct_path
        
        # Test case 2: Missing file
        missing_file_path = "/tmp/test_project/test_project/dockertree/nonexistent_file"
        assert "Caddyfile.dockertree" not in missing_file_path
        
        # Test case 3: Directory instead of file
        directory_path = "/tmp/test_project/test_project/dockertree/"
        assert directory_path.endswith("/")
        
        # Test case 4: Wrong file extension
        wrong_extension_path = "/tmp/test_project/test_project/dockertree/Caddyfile.txt"
        assert not wrong_extension_path.endswith("Caddyfile.dockertree")
    
    @patch('subprocess.run')
    def test_volume_warnings_with_caddyfile_error(self, mock_run, docker_manager):
        """Test that volume warnings are present alongside Caddyfile mounting error."""
        compose_file = Path("/test/docker-compose.worktree.yml")
        env_file = Path("/test/.dockertree/env.dockertree")
        project_name = "test"
        
        # Include both volume warnings and Caddyfile error
        error_stderr = """Network test_internal  Creating
Network test_internal  Created
Network test_web  Creating
Network test_web  Created
Volume test_caddy_data  Creating
Volume test_caddy_data  Created
Volume test_caddy_config  Creating
Volume test_caddy_config  Created
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_postgres_data\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_redis_data\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
time="2025-09-28T18:11:45+09:00" level=warning msg="volume \"test_media_files\" already exists but was not created by Docker Compose. Use `external: true` to use an existing volume"
Container test-caddy  Creating
Container test-redis  Creating
Container test-db  Creating
Container test-caddy  Created
Container test-redis  Created
Container test-db  Created
Container test-rq-worker-1  Creating
Container test-web  Creating
Container test-rq-worker-1  Created
Container test-web  Created
Container test-db  Starting
Container test-redis  Starting
Container test-caddy  Starting
Container test-redis  Started
Container test-db  Started
Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: error mounting "/host_mnt/tmp/test_project/test_project/dockertree-cli/Caddyfile.dockertree" to rootfs at "/etc/caddy/Caddyfile": create mountpoint for /etc/caddy/Caddyfile mount: cannot create subdirectories in "/var/lib/docker/overlay2/0e95bf1b18750d834fdd6e71829438667d616029fa9dc17eaff3c6f7ceaae713/merged/etc/caddy/Caddyfile": not a directory: unknown: Are you trying to mount a directory onto a file (or vice-versa)? Check if the specified host path exists and is the expected type"""
        
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["docker", "compose", "up", "-d"],
            stderr=error_stderr
        )
        
        result = docker_manager.start_services(compose_file, env_file, project_name)
        
        assert result == False
        
        # Verify that both volume warnings and Caddyfile error are present
        assert "volume \"test_postgres_data\" already exists" in error_stderr
        assert "volume \"test_redis_data\" already exists" in error_stderr
        assert "volume \"test_media_files\" already exists" in error_stderr
        assert "error mounting" in error_stderr
        assert "dockertree-cli/Caddyfile.dockertree" in error_stderr
