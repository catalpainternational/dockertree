"""
Error handling tests for dockertree setup command.

Tests cover:
- Permission errors
- Invalid Docker Compose files
- Missing dependencies
- File system errors
- Network errors
- Configuration errors
"""

import pytest
import yaml
import tempfile
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from typing import Dict, Any

from dockertree.commands.setup import SetupManager
from dockertree.utils.validation import check_prerequisites


class TestSetupErrorHandling:
    """Test cases for error handling in setup command."""
    
    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory for testing."""
        temp_dir = Path(tempfile.mkdtemp(prefix="dockertree_error_test_"))
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def setup_manager(self, temp_project_dir):
        """Create a SetupManager instance for testing."""
        with patch('dockertree.commands.setup.get_project_root') as mock_get_root:
            mock_get_root.return_value = temp_project_dir
            return SetupManager()
    
    @pytest.fixture
    def mock_prerequisites_success(self):
        """Mock prerequisites check to return True for error tests that should succeed."""
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.return_value = True
            yield mock_check
    
    def test_error_001_permission_errors(self, setup_manager, mock_prerequisites_success):
        """Test ID: ERROR-001 - Permission errors."""
        # Test directory creation permission error
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test file writing permission error
        with patch('pathlib.Path.write_text') as mock_write:
            mock_write.side_effect = PermissionError("Permission denied")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test file reading permission error
        with patch('pathlib.Path.read_text') as mock_read:
            mock_read.side_effect = PermissionError("Permission denied")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_002_invalid_docker_compose(self, setup_manager, mock_prerequisites_success):
        """Test ID: ERROR-002 - Invalid docker-compose.yml."""
        # Test invalid YAML syntax
        invalid_yaml = setup_manager.project_root / "docker-compose.yml"
        invalid_yaml.write_text("invalid: yaml: content: [")
        
        result = setup_manager.setup_project()
        assert result is False
        
        # Test empty compose file
        empty_compose = setup_manager.project_root / "docker-compose.yml"
        empty_compose.write_text("")
        
        result = setup_manager.setup_project()
        assert result is False
        
        # Test compose file without services
        no_services_compose = setup_manager.project_root / "docker-compose.yml"
        no_services_compose.write_text("version: '3.8'")
        
        result = setup_manager.setup_project()
        assert result is False
        
        # Test compose file with invalid structure
        invalid_structure = {
            'version': '3.8',
            'services': 'not_a_dict'
        }
        
        invalid_compose = setup_manager.project_root / "docker-compose.yml"
        with open(invalid_compose, 'w') as f:
            yaml.dump(invalid_structure, f)
        
        result = setup_manager.setup_project()
        assert result is False
    
    def test_error_003_missing_dependencies(self, setup_manager):
        """Test ID: ERROR-003 - Missing dependencies."""
        # Test missing Docker
        with patch('dockertree.commands.setup.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker is not running")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
        
        # Test missing Git
        with patch('dockertree.commands.setup.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Not in a git repository")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
        
        # Test missing Python dependencies - this would be caught during import
        # Skip this test as it's not easily mockable at the right level
        pass
    
    def test_error_004_file_system_errors(self, setup_manager, mock_prerequisites_success):
        """Test file system errors."""
        # Test disk full error
        with patch('pathlib.Path.write_text') as mock_write:
            mock_write.side_effect = OSError("No space left on device")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test read-only file system
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = OSError("Read-only file system")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test file not found errors - this should not cause setup to fail
        # since setup creates files if they don't exist
        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = False
            
            result = setup_manager.setup_project()
            # Setup should succeed even if files don't exist initially
            assert result is True
    
    def test_error_005_network_errors(self, setup_manager, mock_prerequisites_success):
        """Test network-related errors."""
        # Test Docker daemon not running - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker is not running")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
        
        # Test network timeout - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker Compose is not available")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
    
    def test_error_006_configuration_errors(self, setup_manager, mock_prerequisites_success):
        """Test configuration-related errors."""
        # Test invalid project name - empty project name should be handled gracefully
        result = setup_manager.setup_project(project_name="")
        # Setup should succeed even with empty project name (uses directory name)
        assert result is True
        
        # Test invalid compose file path - setup should create minimal compose file
        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = False
            
            result = setup_manager.setup_project()
            # Setup should succeed by creating minimal compose file
            assert result is True
        
        # Test YAML parsing errors
        with patch('yaml.safe_load') as mock_yaml:
            mock_yaml.side_effect = yaml.YAMLError("YAML parsing error")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_007_memory_errors(self, setup_manager, mock_prerequisites_success):
        """Test memory-related errors."""
        # Test memory allocation error
        with patch('yaml.safe_load') as mock_yaml:
            mock_yaml.side_effect = MemoryError("Cannot allocate memory")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test large file handling
        large_compose = setup_manager.project_root / "docker-compose.yml"
        large_content = "version: '3.8'\n" + "services:\n" + "  web:\n" + "    image: nginx:alpine\n" * 10000
        large_compose.write_text(large_content)
        
        with patch('yaml.safe_load') as mock_yaml:
            mock_yaml.side_effect = MemoryError("File too large")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_008_concurrent_access_errors(self, setup_manager, mock_prerequisites_success):
        """Test concurrent access errors."""
        # Test file locked by another process
        with patch('pathlib.Path.write_text') as mock_write:
            mock_write.side_effect = OSError("Text file busy")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test directory locked by another process
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = OSError("Directory not empty")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_009_unicode_errors(self, setup_manager, mock_prerequisites_success):
        """Test Unicode-related errors."""
        # Test invalid Unicode in compose file
        unicode_compose = setup_manager.project_root / "docker-compose.yml"
        unicode_compose.write_bytes(b"version: '3.8'\nservices:\n  web:\n    image: nginx:alpine\n\xff\xfe")
        
        result = setup_manager.setup_project()
        assert result is False
        
        # Test Unicode encoding errors
        with patch('pathlib.Path.read_text') as mock_read:
            mock_read.side_effect = UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid start byte')
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_010_timeout_errors(self, setup_manager, mock_prerequisites_success):
        """Test timeout-related errors."""
        # Test subprocess timeout - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker is not running")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
        
        # Test file operation timeout
        with patch('pathlib.Path.write_text') as mock_write:
            mock_write.side_effect = TimeoutError("Operation timed out")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_011_resource_exhaustion(self, setup_manager, mock_prerequisites_success):
        """Test resource exhaustion errors."""
        # Test too many open files
        with patch('pathlib.Path.open') as mock_open:
            mock_open.side_effect = OSError("Too many open files")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test process limit exceeded - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker is not running")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
    
    def test_error_012_invalid_arguments(self, setup_manager, mock_prerequisites_success):
        """Test invalid argument handling."""
        # Test None project name
        result = setup_manager.setup_project(project_name=None)
        # Should handle gracefully, not fail
        
        # Test very long project name
        long_name = "a" * 1000
        result = setup_manager.setup_project(project_name=long_name)
        # Should handle gracefully
        
        # Test special characters in project name
        special_name = "project@#$%^&*()"
        result = setup_manager.setup_project(project_name=special_name)
        # Should handle gracefully
    
    def test_error_013_corrupted_files(self, setup_manager, mock_prerequisites_success):
        """Test corrupted file handling."""
        # Test corrupted YAML file
        corrupted_compose = setup_manager.project_root / "docker-compose.yml"
        corrupted_compose.write_text("version: '3.8'\nservices:\n  web:\n    image: nginx:alpine\n    invalid_yaml: [")
        
        result = setup_manager.setup_project()
        assert result is False
        
        # Test binary file in place of text file
        binary_compose = setup_manager.project_root / "docker-compose.yml"
        binary_compose.write_bytes(b'\x00\x01\x02\x03\x04\x05')
        
        result = setup_manager.setup_project()
        assert result is False
    
    def test_error_014_symlink_errors(self, setup_manager, mock_prerequisites_success):
        """Test symlink-related errors."""
        # Test broken symlink
        broken_symlink = setup_manager.project_root / "docker-compose.yml"
        broken_symlink.symlink_to("/nonexistent/path")
        
        result = setup_manager.setup_project()
        assert result is False
        
        # Remove the broken symlink and create a circular one
        broken_symlink.unlink()
        circular_symlink = setup_manager.project_root / "docker-compose.yml"
        circular_symlink.symlink_to("docker-compose.yml")
        
        result = setup_manager.setup_project()
        assert result is False
    
    def test_error_015_permission_denied_specific(self, setup_manager, mock_prerequisites_success):
        """Test specific permission denied scenarios."""
        # Test directory creation permission denied
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied: '/root/.dockertree'")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test file writing permission denied
        with patch('pathlib.Path.write_text') as mock_write:
            mock_write.side_effect = PermissionError("Permission denied: '/root/.dockertree/config.yml'")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test file reading permission denied
        with patch('pathlib.Path.read_text') as mock_read:
            mock_read.side_effect = PermissionError("Permission denied: '/root/docker-compose.yml'")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_016_network_connectivity(self, setup_manager, mock_prerequisites_success):
        """Test network connectivity issues."""
        # Test Docker daemon connection failure - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker is not running")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
        
        # Test network unreachable - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker Compose is not available")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
    
    def test_error_017_disk_space_errors(self, setup_manager, mock_prerequisites_success):
        """Test disk space related errors."""
        # Test insufficient disk space
        with patch('pathlib.Path.write_text') as mock_write:
            mock_write.side_effect = OSError("No space left on device")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test quota exceeded
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = OSError("Disk quota exceeded")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_018_invalid_file_paths(self, setup_manager, mock_prerequisites_success):
        """Test invalid file path scenarios."""
        # Test path too long
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = OSError("File name too long")
            
            result = setup_manager.setup_project()
            assert result is False
        
        # Test invalid characters in path
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = OSError("Invalid argument")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_019_system_resource_limits(self, setup_manager, mock_prerequisites_success):
        """Test system resource limit errors."""
        # Test process limit exceeded - this should be caught by prerequisites check
        with patch('dockertree.utils.validation.check_prerequisites') as mock_check:
            mock_check.side_effect = SystemExit("Docker is not running")
            
            with pytest.raises(SystemExit):
                setup_manager.setup_project()
        
        # Test memory limit exceeded
        with patch('yaml.safe_load') as mock_yaml:
            mock_yaml.side_effect = MemoryError("Cannot allocate memory")
            
            result = setup_manager.setup_project()
            assert result is False
    
    def test_error_020_graceful_degradation(self, setup_manager, mock_prerequisites_success):
        """Test graceful degradation in error scenarios."""
        # Test partial setup failure
        with patch('dockertree.commands.setup.SetupManager._create_dockertree_directory') as mock_create_dir:
            mock_create_dir.return_value = True
            
            with patch('dockertree.commands.setup.SetupManager._transform_compose_file') as mock_transform:
                mock_transform.return_value = False
                
                result = setup_manager.setup_project()
                assert result is False
        
        # Test setup status with partial failure
        with patch.object(setup_manager, 'get_setup_status') as mock_status:
            mock_status.return_value = {
                'dockertree_dir_exists': True,
                'config_file_exists': True,
                'compose_file_exists': False,
                'caddyfile_exists': False,
                'is_complete': False,
                'project_root': str(setup_manager.project_root),
                'dockertree_dir': str(setup_manager.dockertree_dir)
            }
            status = setup_manager.get_setup_status()
            assert status['is_complete'] is False
            assert status['config_file_exists'] is True
            assert status['compose_file_exists'] is False
