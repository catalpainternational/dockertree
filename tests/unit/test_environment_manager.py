"""
Unit tests for environment manager.
"""

import pytest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path
from dockertree.core.environment_manager import EnvironmentManager


class TestEnvironmentManager:
    """Test environment manager functionality."""
    
    def test_init(self):
        """Test environment manager initialization."""
        env_manager = EnvironmentManager()
        assert env_manager is not None
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_worktree_volume_names(self, mock_project_name):
        """Test worktree volume name generation.
        
        Note: Caddy volumes are not included as they are shared globally,
        not worktree-specific.
        """
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        volume_names = env_manager.get_worktree_volume_names("test-branch")
        
        expected = {
            "postgres": "test-project-test-branch_postgres_data",
            "redis": "test-project-test-branch_redis_data",
            "media": "test-project-test-branch_media_files",
        }
        assert volume_names == expected
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_environment_variables(self, mock_project_name):
        """Test environment variable generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        env_vars = env_manager.get_environment_variables("test-branch")
        
        assert env_vars["COMPOSE_PROJECT_NAME"] == "test-project-test-branch"
        assert env_vars["SITE_DOMAIN"] == "test-project-test-branch.localhost"
        assert "test-project-test-branch.localhost" in env_vars["ALLOWED_HOSTS"]
        assert "localhost" in env_vars["ALLOWED_HOSTS"]
        assert "127.0.0.1" in env_vars["ALLOWED_HOSTS"]
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_domain_name(self, mock_project_name):
        """Test domain name generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        domain = env_manager.get_domain_name("test-branch")
        assert domain == "test-project-test-branch.localhost"
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_allowed_hosts(self, mock_project_name):
        """Test allowed hosts generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        hosts = env_manager.get_allowed_hosts("test-branch")
        expected = "localhost,127.0.0.1,test-project-test-branch.localhost,*.localhost,web,test-project-test-branch-web"
        assert hosts == expected
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_database_url(self, mock_project_name):
        """Test database URL generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        db_url = env_manager.get_database_url("test-branch")
        expected = "postgres://biuser:bipassword@test-project-test-branch-db:5432/database"
        assert db_url == expected
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_database_url_custom_params(self, mock_project_name):
        """Test database URL generation with custom parameters."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        db_url = env_manager.get_database_url(
            "test-branch", 
            postgres_user="custom_user",
            postgres_password="custom_pass",
            postgres_db="custom_db"
        )
        expected = "postgres://custom_user:custom_pass@test-project-test-branch-db:5432/custom_db"
        assert db_url == expected
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_redis_url(self, mock_project_name):
        """Test Redis URL generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        redis_url = env_manager.get_redis_url("test-branch")
        expected = "redis://test-project-test-branch-redis:6379/0"
        assert redis_url == expected
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_redis_url_custom_params(self, mock_project_name):
        """Test Redis URL generation with custom parameters."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        redis_url = env_manager.get_redis_url("test-branch", redis_port=6380, redis_db=1)
        expected = "redis://test-project-test-branch-redis:6380/1"
        assert redis_url == expected
    
    @patch('dockertree.config.settings.get_project_name')
    def test_generate_compose_environment(self, mock_project_name):
        """Test compose environment generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        compose_env = env_manager.generate_compose_environment("test-branch")
        
        assert compose_env["COMPOSE_PROJECT_NAME"] == "test-project-test-branch"
        assert compose_env["DATABASE_URL"] == "postgres://biuser:bipassword@test-project-test-branch-db:5432/database"
        assert compose_env["REDIS_HOST"] == "test-project-test-branch-redis"
        assert compose_env["REDIS_PORT"] == "6379"
        assert compose_env["REDIS_DB"] == "0"
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.write_text')
    def test_validate_environment_file_success(self, mock_write, mock_exists):
        """Test environment file validation success."""
        mock_exists.return_value = True
        
        env_manager = EnvironmentManager()
        env_file_path = Path("/test/.env")
        
        with patch('pathlib.Path.read_text', return_value="TEST_VAR=value"):
            assert env_manager.validate_environment_file(env_file_path) == True
    
    @patch('pathlib.Path.exists')
    def test_validate_environment_file_not_exists(self, mock_exists):
        """Test environment file validation when file doesn't exist."""
        mock_exists.return_value = False
        
        env_manager = EnvironmentManager()
        env_file_path = Path("/test/.env")
        
        assert env_manager.validate_environment_file(env_file_path) == False
    
    @patch('pathlib.Path.exists')
    def test_validate_environment_file_empty(self, mock_exists):
        """Test environment file validation when file is empty."""
        mock_exists.return_value = True
        
        env_manager = EnvironmentManager()
        env_file_path = Path("/test/.env")
        
        with patch('pathlib.Path.read_text', return_value=""):
            assert env_manager.validate_environment_file(env_file_path) == False
    
    @patch('pathlib.Path.exists')
    def test_validate_environment_file_read_error(self, mock_exists):
        """Test environment file validation when read fails."""
        mock_exists.return_value = True
        
        env_manager = EnvironmentManager()
        env_file_path = Path("/test/.env")
        
        with patch('pathlib.Path.read_text', side_effect=Exception("Read error")):
            assert env_manager.validate_environment_file(env_file_path) == False
    
    @patch('dockertree.config.settings.get_project_name')
    def test_get_worktree_config(self, mock_project_name):
        """Test complete worktree configuration generation."""
        mock_project_name.return_value = "test_project"
        env_manager = EnvironmentManager()
        config = env_manager.get_worktree_config("test-branch")
        
        assert config["branch_name"] == "test-branch"
        assert config["domain_name"] == "test-project-test-branch.localhost"
        assert config["allowed_hosts"] == "localhost,127.0.0.1,test-project-test-branch.localhost,*.localhost,web,test-project-test-branch-web"
        assert "postgres://biuser:bipassword@test-project-test-branch-db:5432/database" in config["database_url"]
        assert "redis://test-project-test-branch-redis:6379/0" in config["redis_url"]
        assert "postgres" in config["volume_names"]
        assert "redis" in config["volume_names"]
        assert "media" in config["volume_names"]
        assert "COMPOSE_PROJECT_NAME" in config["environment_variables"]
        assert "DATABASE_URL" in config["compose_environment"]
    
    @patch('dockertree.config.settings.get_project_name')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.write_text')
    def test_create_env_file_from_template_success(self, mock_write, mock_read, mock_exists, mock_project_name):
        """Test environment file creation from template success."""
        mock_project_name.return_value = "test_project"
        mock_exists.return_value = True
        mock_read.return_value = "COMPOSE_PROJECT_NAME={{BRANCH_NAME}}\nSITE_DOMAIN={{DOMAIN_NAME}}"
        
        env_manager = EnvironmentManager()
        template_path = Path("/test/template.env")
        target_path = Path("/test/.env")
        
        result = env_manager.create_env_file_from_template(template_path, target_path, "test-branch")
        
        assert result == True
        mock_write.assert_called_once()
        # Check that placeholders were replaced
        call_args = mock_write.call_args[0][0]
        assert "COMPOSE_PROJECT_NAME=test-branch" in call_args
        assert "SITE_DOMAIN=test-project-test-branch.localhost" in call_args
    
    @patch('pathlib.Path.exists')
    def test_create_env_file_from_template_not_exists(self, mock_exists):
        """Test environment file creation from template when template doesn't exist."""
        mock_exists.return_value = False
        
        env_manager = EnvironmentManager()
        template_path = Path("/test/template.env")
        target_path = Path("/test/.env")
        
        result = env_manager.create_env_file_from_template(template_path, target_path, "test-branch")
        assert result == False
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_create_env_file_from_template_read_error(self, mock_read, mock_exists):
        """Test environment file creation from template when read fails."""
        mock_exists.return_value = True
        mock_read.side_effect = Exception("Read error")
        
        env_manager = EnvironmentManager()
        template_path = Path("/test/template.env")
        target_path = Path("/test/.env")
        
        result = env_manager.create_env_file_from_template(template_path, target_path, "test-branch")
        assert result == False
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.unlink')
    def test_cleanup_environment_files_success(self, mock_unlink, mock_exists):
        """Test environment file cleanup success."""
        mock_exists.return_value = True
        
        env_manager = EnvironmentManager()
        worktree_path = Path("/test/worktree")
        
        result = env_manager.cleanup_environment_files(worktree_path)
        
        assert result == True
        assert mock_unlink.call_count == 2  # .env and env.dockertree
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.unlink')
    def test_cleanup_environment_files_partial_failure(self, mock_unlink, mock_exists):
        """Test environment file cleanup with partial failure."""
        mock_exists.return_value = True
        mock_unlink.side_effect = [None, Exception("Delete error")]
        
        env_manager = EnvironmentManager()
        worktree_path = Path("/test/worktree")
        
        result = env_manager.cleanup_environment_files(worktree_path)
        
        assert result == False
        assert mock_unlink.call_count == 2
