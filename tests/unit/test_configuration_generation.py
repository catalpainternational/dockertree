"""
Configuration generation tests for dockertree setup command.

Tests cover:
- Config.yml generation with detected services
- Volume detection and configuration
- Environment variable handling
- Docker Compose transformation
- Caddyfile template handling
"""

import pytest
import yaml
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from typing import Dict, Any, List

from dockertree.commands.setup import SetupManager


class TestConfigurationGeneration:
    """Test cases for configuration generation functionality."""
    
    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory for testing."""
        temp_dir = Path(tempfile.mkdtemp(prefix="dockertree_config_test_"))
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def setup_manager(self, temp_project_dir):
        """Create a SetupManager instance for testing."""
        with patch('dockertree.commands.setup.get_project_root') as mock_get_root:
            mock_get_root.return_value = temp_project_dir
            return SetupManager()
    
    @pytest.fixture
    def complex_compose_data(self):
        """Complex docker-compose.yml data for testing."""
        return {
            'version': '3.8',
            'services': {
                'web': {
                    'build': '.',
                    'ports': ['8000:8000'],
                    'container_name': 'myproject-web',
                    'volumes': ['./:/app'],
                    'environment': {
                        'DEBUG': 'True',
                        'ALLOWED_HOSTS': 'localhost,127.0.0.1',
                        'DATABASE_URL': 'postgres://user:pass@db:5432/myproject'
                    },
                    'depends_on': ['db', 'redis', 'elasticsearch']
                },
                'db': {
                    'image': 'postgres:13',
                    'container_name': 'myproject-db',
                    'volumes': ['postgres_data:/var/lib/postgresql/data'],
                    'environment': {
                        'POSTGRES_DB': 'myproject',
                        'POSTGRES_USER': 'user',
                        'POSTGRES_PASSWORD': 'pass'
                    }
                },
                'redis': {
                    'image': 'redis:alpine',
                    'container_name': 'myproject-redis'
                },
                'elasticsearch': {
                    'image': 'elasticsearch:7.14.0',
                    'container_name': 'myproject-elasticsearch',
                    'volumes': ['elasticsearch_data:/usr/share/elasticsearch/data'],
                    'environment': {
                        'discovery.type': 'single-node'
                    }
                },
                'nginx': {
                    'image': 'nginx:alpine',
                    'container_name': 'myproject-nginx',
                    'ports': ['80:80'],
                    'volumes': ['./nginx.conf:/etc/nginx/nginx.conf'],
                    'depends_on': ['web']
                }
            },
            'volumes': {
                'postgres_data': {},
                'elasticsearch_data': {}
            },
            'networks': {
                'app_network': {
                    'driver': 'bridge'
                }
            }
        }
    
    def test_config_001_config_yml_generation(self, setup_manager, complex_compose_data):
        """Test ID: CONFIG-001 - Config.yml generation with detected services."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project(project_name="test-project")
        assert result is True
        
        # Verify config.yml content
        config_file = setup_manager.dockertree_dir / "config.yml"
        assert config_file.exists()
        
        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        
        # Check basic configuration
        assert config_data['project_name'] == "test-project"
        assert config_data['caddy_network'] == 'dockertree_caddy_proxy'
        assert config_data['worktree_dir'] == 'worktrees'
        
        # Check services configuration
        assert 'services' in config_data
        services = config_data['services']
        
        # Verify all services are detected
        expected_services = ['web', 'db', 'redis', 'elasticsearch', 'nginx']
        for service in expected_services:
            assert service in services
            assert 'container_name_template' in services[service]
            assert services[service]['container_name_template'] == f'${{COMPOSE_PROJECT_NAME}}-{service}'
        
        # Check volumes configuration
        assert 'volumes' in config_data
        volumes = config_data['volumes']
        assert 'postgres_data' in volumes
        assert 'elasticsearch_data' in volumes
        
        # Check environment configuration
        assert 'environment' in config_data
        env = config_data['environment']
        assert env['DEBUG'] == 'True'
        assert 'ALLOWED_HOSTS' in env
    
    def test_config_002_volume_detection(self, setup_manager, complex_compose_data):
        """Test ID: CONFIG-002 - Volume detection in config.yml."""
        # Create docker-compose.yml with volumes
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify volumes in config
        config_file = setup_manager.dockertree_dir / "config.yml"
        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        
        assert 'volumes' in config_data
        volumes = config_data['volumes']
        
        # Check all volumes are detected
        expected_volumes = ['postgres_data', 'elasticsearch_data']
        for volume in expected_volumes:
            assert volume in volumes
    
    def test_config_003_environment_variables(self, setup_manager, complex_compose_data):
        """Test ID: CONFIG-003 - Environment variable detection."""
        # Create docker-compose.yml with environment variables
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify environment variables in config
        config_file = setup_manager.dockertree_dir / "config.yml"
        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        
        assert 'environment' in config_data
        env = config_data['environment']
        
        # Check default environment variables
        assert env['DEBUG'] == 'True'
        assert 'ALLOWED_HOSTS' in env
        assert 'localhost,127.0.0.1,*.localhost,web' in env['ALLOWED_HOSTS']
    
    def test_transform_001_container_name_transformation(self, setup_manager, complex_compose_data):
        """Test ID: TRANSFORM-001 - Container name transformation."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        assert worktree_compose.exists()
        
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        # Check container names use variables
        services = transformed_data['services']
        
        # Check specific container name transformations
        assert services['web']['container_name'] == '${COMPOSE_PROJECT_NAME}-myproject-web'
        assert services['db']['container_name'] == '${COMPOSE_PROJECT_NAME}-myproject-db'
        assert services['redis']['container_name'] == '${COMPOSE_PROJECT_NAME}-myproject-redis'
        assert services['elasticsearch']['container_name'] == '${COMPOSE_PROJECT_NAME}-myproject-elasticsearch'
        assert services['nginx']['container_name'] == '${COMPOSE_PROJECT_NAME}-myproject-nginx'
    
    def test_transform_002_port_to_expose_conversion(self, setup_manager, complex_compose_data):
        """Test ID: TRANSFORM-002 - Port to expose conversion."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        services = transformed_data['services']
        
        # Check ports converted to expose (should extract container port only)
        assert 'expose' in services['web']
        assert 'ports' not in services['web']
        assert services['web']['expose'] == ['8000']
        
        assert 'expose' in services['nginx']
        assert 'ports' not in services['nginx']
        assert services['nginx']['expose'] == ['80']
    
    def test_transform_003_caddy_labels_addition(self, setup_manager, complex_compose_data):
        """Test ID: TRANSFORM-003 - Caddy labels addition to web services."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        services = transformed_data['services']
        
        # Check Caddy labels added to web service
        web_service = services['web']
        assert 'labels' in web_service
        labels = web_service['labels']
        
        # Check for Caddy proxy labels
        caddy_labels = [label for label in labels if 'caddy.proxy' in label]
        assert len(caddy_labels) > 0
        
        # Check specific Caddy labels
        assert any('caddy.proxy=${COMPOSE_PROJECT_NAME}.localhost' in label for label in labels)
        assert any('caddy.proxy.reverse_proxy' in label for label in labels)
        # Health check is optional and disabled by default
        # assert any('caddy.proxy.health_check' in label for label in labels)
        
        # Check web service is connected to dockertree_caddy_proxy network
        assert 'networks' in web_service
        assert 'dockertree_caddy_proxy' in web_service['networks']
    
    def test_transform_004_volume_name_transformation(self, setup_manager, complex_compose_data):
        """Test ID: TRANSFORM-004 - Volume name transformation."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        # Check volumes use branch-specific naming
        if 'volumes' in transformed_data:
            for volume_name, volume_config in transformed_data['volumes'].items():
                if isinstance(volume_config, dict) and 'name' in volume_config:
                    assert volume_config['name'].startswith('${COMPOSE_PROJECT_NAME}_')
    
    def test_network_configuration(self, setup_manager, complex_compose_data):
        """Test network configuration in transformed compose file."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify network configuration
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        # Check networks section
        assert 'networks' in transformed_data
        networks = transformed_data['networks']
        
        # Check dockertree_caddy_proxy network is added
        assert 'dockertree_caddy_proxy' in networks
        assert networks['dockertree_caddy_proxy']['external'] is True
        
        # Check original networks are preserved
        if 'app_network' in complex_compose_data.get('networks', {}):
            assert 'app_network' in networks
    
    def test_environment_variable_addition(self, setup_manager, complex_compose_data):
        """Test environment variable addition to services."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        services = transformed_data['services']
        
        # Check environment variables are added to all services
        for service_name, service_config in services.items():
            if 'environment' in service_config:
                env = service_config['environment']
                
                # Check for added environment variables
                assert 'COMPOSE_PROJECT_NAME' in env
                assert 'PROJECT_ROOT' in env
                
                # Check original environment variables are preserved
                if service_name == 'web':
                    assert 'DEBUG' in env
                    assert 'ALLOWED_HOSTS' in env
                    assert 'DATABASE_URL' in env
    
    def test_caddyfile_template_handling(self, setup_manager, complex_compose_data):
        """Test Caddyfile template handling."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Mock the source Caddyfile template
        with patch('dockertree.config.settings.get_script_dir') as mock_get_script_dir:
            mock_script_dir = Path("/mock/script/dir")
            mock_get_script_dir.return_value = mock_script_dir
            
            # Mock the source Caddyfile
            mock_source_caddyfile = mock_script_dir / "config" / "Caddyfile.dockertree"
            with patch.object(Path, 'exists') as mock_exists:
                mock_exists.return_value = True
                with patch.object(Path, 'read_text') as mock_read_text:
                    mock_read_text.return_value = "# Mock Caddyfile content"
                    with patch.object(Path, 'write_text') as mock_write_text:
                        result = setup_manager.setup_project()
                        assert result is True
                        
                        # Verify Caddyfile was created
                        caddyfile = setup_manager.dockertree_dir / "Caddyfile.dockertree"
                        assert caddyfile.exists()
                        
                        # Verify content was written
                        mock_write_text.assert_called_once_with("# Mock Caddyfile content")
    
    def test_minimal_caddyfile_creation(self, setup_manager):
        """Test minimal Caddyfile creation when template is not found."""
        # Create minimal compose file
        minimal_compose = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:alpine',
                    'ports': ['8000:80']
                }
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(minimal_compose, f)
        
        # Mock missing template
        with patch('dockertree.config.settings.get_script_dir') as mock_get_script_dir:
            mock_script_dir = Path("/mock/script/dir")
            mock_get_script_dir.return_value = mock_script_dir
            
            mock_source_caddyfile = mock_script_dir / "config" / "Caddyfile.dockertree"
            with patch.object(Path, 'exists') as mock_exists:
                mock_exists.return_value = False
                
                result = setup_manager.setup_project()
                assert result is True
                
                # Verify minimal Caddyfile was created
                caddyfile = setup_manager.dockertree_dir / "Caddyfile.dockertree"
                assert caddyfile.exists()
                
                # Verify minimal content
                with open(caddyfile) as f:
                    content = f.read()
                
                assert "Global Caddyfile for Dockertree" in content
                assert "auto_https off" in content
                assert "admin 0.0.0.0:2019" in content
    
    def test_config_file_structure(self, setup_manager, complex_compose_data):
        """Test config file structure and validation."""
        # Create docker-compose.yml
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(complex_compose_data, f)
        
        # Run setup
        result = setup_manager.setup_project(project_name="structure-test")
        assert result is True
        
        # Verify config file structure
        config_file = setup_manager.dockertree_dir / "config.yml"
        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        
        # Check required fields
        required_fields = ['project_name', 'caddy_network', 'worktree_dir', 'services', 'volumes', 'environment']
        for field in required_fields:
            assert field in config_data
        
        # Check data types
        assert isinstance(config_data['project_name'], str)
        assert isinstance(config_data['caddy_network'], str)
        assert isinstance(config_data['worktree_dir'], str)
        assert isinstance(config_data['services'], dict)
        assert isinstance(config_data['volumes'], list)
        assert isinstance(config_data['environment'], dict)
        
        # Check specific values
        assert config_data['project_name'] == "structure-test"
        assert config_data['caddy_network'] == "dockertree_caddy_proxy"
        assert config_data['worktree_dir'] == "worktrees"
    
    def test_duplicate_network_detection(self, setup_manager):
        """Test that duplicate networks are detected and prevented."""
        # Create compose file with existing caddy_proxy network
        compose_data = {
            'services': {
                'web': {
                    'image': 'nginx',
                    'networks': ['internal', 'caddy_proxy', 'caddy_proxy'],  # Duplicate
                    'labels': ['caddy.proxy=test.localhost', 'caddy.proxy=test.localhost']  # Duplicate
                }
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(compose_data, f)
        
        # Run setup - should handle duplicates gracefully
        result = setup_manager.setup_project()
        assert result is True
        
        # Check that worktree compose file was created without duplicates
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        web_service = transformed_data['services']['web']
        networks = web_service['networks']
        labels = web_service['labels']
        
        # Should not have duplicates
        assert len(networks) == len(set(networks))
        assert len(labels) == len(set(labels))
        
        # Should have dockertree_caddy_proxy network
        assert 'dockertree_caddy_proxy' in networks
    
    def test_legacy_cleanup_functionality(self, setup_manager):
        """Test legacy dockertree element cleanup."""
        # Create compose file with legacy elements
        compose_data = {
            'services': {
                'web': {
                    'image': 'nginx',
                    'container_name': '${COMPOSE_PROJECT_NAME}-web',
                    'networks': ['internal', 'caddy_proxy'],
                    'labels': ['caddy.proxy=test.localhost', 'caddy.proxy.reverse_proxy=web:8000']
                }
            },
            'networks': {
                'caddy_proxy': {'external': True}
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(compose_data, f)
        
        # Test legacy cleanup
        cleaned_data = setup_manager._clean_legacy_dockertree_elements(compose_data)
        
        # Check that legacy elements are removed
        web_service = cleaned_data['services']['web']
        assert web_service['container_name'] == 'web'  # ${COMPOSE_PROJECT_NAME} prefix removed
        assert 'caddy_proxy' not in web_service['networks']
        assert 'caddy.proxy' not in str(web_service.get('labels', []))
        assert 'caddy_proxy' not in cleaned_data.get('networks', {})
    
    def test_service_detection_edge_cases(self, setup_manager):
        """Test service detection edge cases."""
        # Test compose file with no services
        empty_compose = {
            'version': '3.8',
            'services': {}
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(empty_compose, f)
        
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify config with no services
        config_file = setup_manager.dockertree_dir / "config.yml"
        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        
        assert config_data['services'] == {}
    
    def test_volume_detection_edge_cases(self, setup_manager):
        """Test volume detection edge cases."""
        # Test compose file with no volumes
        no_volumes_compose = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:alpine'
                }
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(no_volumes_compose, f)
        
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify config with no volumes
        config_file = setup_manager.dockertree_dir / "config.yml"
        with open(config_file) as f:
            config_data = yaml.safe_load(f)
        
        assert config_data['volumes'] == []
    
    def test_environment_variable_preservation(self, setup_manager):
        """Test that original environment variables are preserved."""
        # Create compose file with specific environment variables
        env_compose = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:alpine',
                    'environment': {
                        'CUSTOM_VAR': 'custom_value',
                        'DEBUG': 'False',
                        'PORT': '8080'
                    }
                }
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(env_compose, f)
        
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file preserves environment variables
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        web_service = transformed_data['services']['web']
        assert 'environment' in web_service
        
        env = web_service['environment']
        assert 'CUSTOM_VAR' in env
        assert env['CUSTOM_VAR'] == 'custom_value'
        assert 'DEBUG' in env
        assert env['DEBUG'] == 'False'
        assert 'PORT' in env
        assert env['PORT'] == '8080'
        
        # Check added environment variables
        assert 'COMPOSE_PROJECT_NAME' in env
        assert 'PROJECT_ROOT' in env
    
    def test_env_file_directive_addition(self, setup_manager):
        """Test that env_file directives are added to all services."""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:alpine',
                    'environment': {
                        'DEBUG': 'True'
                    }
                },
                'db': {
                    'image': 'postgres:15'
                }
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(compose_data, f)
        
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify transformed compose file has env_file directives
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        # Check both services have env_file directives
        for service_name in ['web', 'db']:
            service = transformed_data['services'][service_name]
            assert 'env_file' in service
            assert '${PROJECT_ROOT}/.env' in service['env_file']
            assert '${PROJECT_ROOT}/.dockertree/env.dockertree' in service['env_file']

    def test_env_file_preserves_existing(self, setup_manager):
        """Test that existing env_file directives are preserved."""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {
                    'image': 'nginx:alpine',
                    'env_file': '.env.custom'
                }
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(compose_data, f)
        
        result = setup_manager.setup_project()
        assert result is True
        
        worktree_compose = setup_manager.dockertree_dir / "docker-compose.worktree.yml"
        with open(worktree_compose) as f:
            transformed_data = yaml.safe_load(f)
        
        web_service = transformed_data['services']['web']
        assert '.env.custom' in web_service['env_file']
        assert '${PROJECT_ROOT}/.env' in web_service['env_file']
        assert '${PROJECT_ROOT}/.dockertree/env.dockertree' in web_service['env_file']

    def test_template_env_dockertree_creation(self, setup_manager):
        """Test that template env.dockertree is created during setup."""
        compose_data = {
            'version': '3.8',
            'services': {
                'web': {'image': 'nginx:alpine'}
            }
        }
        
        compose_file = setup_manager.project_root / "docker-compose.yml"
        with open(compose_file, 'w') as f:
            yaml.dump(compose_data, f)
        
        result = setup_manager.setup_project()
        assert result is True
        
        # Verify template env.dockertree was created
        env_dockertree = setup_manager.dockertree_dir / "env.dockertree"
        assert env_dockertree.exists()
        
        # Verify content
        content = env_dockertree.read_text()
        assert 'COMPOSE_PROJECT_NAME' in content
        assert 'PROJECT_ROOT' in content
        assert 'SITE_DOMAIN' in content