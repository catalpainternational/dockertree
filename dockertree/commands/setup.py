"""
Setup command for dockertree CLI.

This module provides the setup command that initializes dockertree for a project.
"""

import yaml
from pathlib import Path
from typing import Optional, Dict, Any

from ..config.settings import get_project_root, DOCKERTREE_DIR, get_worktree_dir
from ..utils.logging import log_info, log_success, log_warning, log_error
from ..utils.validation import check_prerequisites
from ..utils.file_utils import (
    prompt_yes_no, 
    add_to_gitignore, 
    add_to_cursorignore,
    add_to_cursorindexignore,
    check_gitignore_entry,
    replace_gitignore_entry,
    remove_gitignore_entry
)


class SetupManager:
    """Manages project setup for dockertree CLI."""
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialize setup manager.
        
        Args:
            project_root: Project root directory. If None, uses current working directory.
        """
        self.project_root = project_root or Path.cwd()
        self.dockertree_dir = self.project_root / DOCKERTREE_DIR
    
    def setup_project(self, project_name: Optional[str] = None) -> bool:
        """Initialize dockertree for a project."""
        log_info("Setting up dockertree for this project...")
        
        # 0. Check prerequisites first
        check_prerequisites(project_root=self.project_root)
        
        # 0.5. Validate PROJECT_ROOT environment variable
        if not self._validate_project_root():
            return False
        
        # 1. Create .dockertree directory structure
        if not self._create_dockertree_directory():
            return False
        
        # 2. Detect existing compose file
        compose_file = self.detect_docker_compose()
        if not compose_file:
            log_warning("No Docker Compose file found in project root")
            log_info("Creating minimal docker-compose.yml template...")
            compose_file = self._create_minimal_compose()
            if not compose_file:
                return False
        
        # 3. Generate worktree-specific compose file
        if not self._transform_compose_file(compose_file):
            return False
        
        # 3.5. Validate transformed paths
        if not self._validate_transformed_paths():
            log_warning("Some transformed paths may not work correctly")
            log_info("You may need to adjust paths in the generated compose file")
        
        # 4. Create config.yml
        if not self._create_config_file(project_name, compose_file):
            return False
        
        
        # 7. Ask user about adding .dockertree to .gitignore
        if not self._handle_gitignore_setup():
            log_warning("Gitignore setup was skipped or failed")
        
        # 8. Ask user about installing shell completion
        if not self._handle_completion_setup():
            log_warning("Completion setup was skipped or failed")
        
        log_success("Dockertree setup completed successfully!")
        log_info(f"Configuration: {self.dockertree_dir}/config.yml")
        log_info("Next: dockertree start")
        return True
    
    def _create_dockertree_directory(self) -> bool:
        """Create .dockertree directory structure."""
        try:
            self.dockertree_dir.mkdir(exist_ok=True)
            log_info(f"Created directory: {self.dockertree_dir}")
            
            # Create worktree directory (default: ./worktrees)
            worktree_dir = get_worktree_dir()
            worktree_path = self.project_root / worktree_dir
            worktree_path.mkdir(exist_ok=True)
            log_info(f"Created worktree directory: {worktree_path}")
            
            return True
        except Exception as e:
            log_error(f"Failed to create directories: {e}")
            return False
    
    def detect_docker_compose(self) -> Optional[Path]:
        """Find compose files in project, supporting both legacy and v2 naming conventions."""
        from ..utils.file_utils import find_compose_files, prompt_compose_file_choice
        
        compose_files = find_compose_files(self.project_root)
        
        if not compose_files:
            return None
        
        if len(compose_files) == 1:
            compose_file = compose_files[0]
            log_info(f"Found {compose_file.name}: {compose_file}")
            return compose_file
        
        # Multiple files found, let user choose
        selected_file = prompt_compose_file_choice(compose_files)
        if selected_file:
            log_info(f"Using {selected_file.name}: {selected_file}")
            return selected_file
        
        return None
    
    def _create_minimal_compose(self) -> Optional[Path]:
        """Create a minimal docker-compose.yml template."""
        minimal_compose = """version: '3.8'

services:
  web:
    image: nginx:alpine
    ports:
      - "8000:80"
    volumes:
      - ./:/app
    environment:
      - DEBUG=True
"""
        compose_file = self.project_root / "docker-compose.yml"
        try:
            compose_file.write_text(minimal_compose)
            log_info("Created minimal docker-compose.yml template")
            return compose_file
        except Exception as e:
            log_error(f"Failed to create minimal docker-compose.yml: {e}")
            return None
    
    def _transform_compose_file(self, source_compose: Path) -> bool:
        """Transform compose file for worktree use."""
        try:
            target_compose = self.dockertree_dir / "docker-compose.worktree.yml"
            
            # Read source compose file
            with open(source_compose) as f:
                compose_data = yaml.safe_load(f)
            
            if not compose_data or 'services' not in compose_data:
                log_error("Invalid compose file")
                return False
            
            # Filter out services that should not be included per-worktree
            # Caddy should only run as a global service, not per-worktree
            services_to_exclude = ['caddy', 'caddy-monitor', 'dockertree_caddy_proxy']
            excluded_services = [name for name in compose_data['services'].keys() if name in services_to_exclude]
            if excluded_services:
                log_info(f"Excluding global services from worktree compose: {', '.join(excluded_services)}")
            
            filtered_services = {
                name: config for name, config in compose_data['services'].items()
                if name not in services_to_exclude
            }
            compose_data['services'] = filtered_services
            
            # Transform services
            for service_name, service_config in compose_data['services'].items():
                # Add COMPOSE_PROJECT_NAME to container names
                if 'container_name' in service_config:
                    service_config['container_name'] = f"${{COMPOSE_PROJECT_NAME}}-{service_config['container_name']}"
                else:
                    service_config['container_name'] = f"${{COMPOSE_PROJECT_NAME}}-{service_name}"
                
                # Convert ports to expose for isolation
                if 'ports' in service_config:
                    ports = service_config.pop('ports')
                    expose_ports = []
                    for port in ports:
                        if isinstance(port, str):
                            # Handle "8000:8000" or "8000" format - extract container port
                            container_port = port.split(':')[-1]
                            expose_ports.append(container_port)
                        elif isinstance(port, int):
                            expose_ports.append(str(port))
                    service_config['expose'] = expose_ports
                
                # Add Caddy labels for web services
                if service_name in ['web', 'app', 'frontend', 'api']:
                    existing_labels = service_config.setdefault('labels', [])
                    new_labels = [
                        f"caddy.proxy=${{COMPOSE_PROJECT_NAME}}.localhost",
                        f"caddy.proxy.reverse_proxy=${{COMPOSE_PROJECT_NAME}}-{service_name}:8000"
                        # Note: Health check disabled by default. Add manually if needed:
                        # "caddy.proxy.health_check=/health-check/"
                    ]
                    # Only add labels that don't already exist
                    for label in new_labels:
                        if label not in existing_labels:
                            existing_labels.append(label)
                    
                    # Connect web services to dockertree_caddy_proxy network
                    networks = service_config.setdefault('networks', [])
                    if 'dockertree_caddy_proxy' not in networks:
                        networks.append('dockertree_caddy_proxy')
                
                # Add environment variables
                if 'environment' in service_config:
                    if isinstance(service_config['environment'], dict):
                        service_config['environment'].update({
                            'COMPOSE_PROJECT_NAME': '${COMPOSE_PROJECT_NAME}',
                            'PROJECT_ROOT': '${PROJECT_ROOT}',
                        })
                    elif isinstance(service_config['environment'], list):
                        service_config['environment'].extend([
                            'COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}',
                            'PROJECT_ROOT=${PROJECT_ROOT}',
                        ])
                else:
                    service_config['environment'] = {
                        'COMPOSE_PROJECT_NAME': '${COMPOSE_PROJECT_NAME}',
                        'PROJECT_ROOT': '${PROJECT_ROOT}',
                    }
                
                # Transform volume mounts for worktree compatibility
                self._transform_volume_mounts(service_config)
                
                # Transform build configurations for worktree compatibility
                self._transform_build_configuration(service_config)
                
                # Resolve relative paths in volumes and other configurations
                self._resolve_relative_paths(service_config)
            
            # Transform volumes to use branch-specific names
            # Exclude caddy volumes as they are shared globally
            volumes_to_exclude = ['caddy_data', 'caddy_config']
            if 'volumes' in compose_data:
                # Filter out caddy volumes
                excluded_volumes = [name for name in compose_data['volumes'].keys() if name in volumes_to_exclude]
                if excluded_volumes:
                    log_info(f"Excluding global volumes from worktree compose: {', '.join(excluded_volumes)}")
                
                filtered_volumes = {
                    name: config for name, config in compose_data['volumes'].items()
                    if name not in volumes_to_exclude
                }
                compose_data['volumes'] = filtered_volumes
                
                for volume_name, volume_config in compose_data['volumes'].items():
                    if isinstance(volume_config, dict):
                        # Transform volume names to use COMPOSE_PROJECT_NAME prefix
                        if 'name' in volume_config:
                            # Replace existing name with templated version
                            original_name = volume_config['name']
                            # Extract the base name after the project prefix if present
                            volume_config['name'] = f"${{COMPOSE_PROJECT_NAME}}_{volume_name}"
                        elif 'external' in volume_config:
                            # External volumes also need project prefix
                            volume_config['name'] = f"${{COMPOSE_PROJECT_NAME}}_{volume_name}"
                        else:
                            # No explicit name, add one with project prefix
                            volume_config['name'] = f"${{COMPOSE_PROJECT_NAME}}_{volume_name}"
                    elif volume_config is None:
                        # Simple volume definition, add explicit name
                        compose_data['volumes'][volume_name] = {
                            'name': f"${{COMPOSE_PROJECT_NAME}}_{volume_name}"
                        }
            
            # Add networks
            compose_data.setdefault('networks', {})
            compose_data['networks']['dockertree_caddy_proxy'] = {'external': True}
            
            # Validate transformed compose file
            if not self._validate_transformed_compose(compose_data):
                return False
            
            # Write transformed compose file
            with open(target_compose, 'w') as f:
                yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)
            
            log_success(f"Created worktree compose file: {target_compose}")
            return True
            
        except Exception as e:
            log_error(f"Failed to transform compose file: {e}")
            return False
    
    def _validate_transformed_compose(self, compose_data: Dict[str, Any]) -> bool:
        """Validate transformed compose file for common issues."""
        for service_name, service_config in compose_data.get('services', {}).items():
            # Check for duplicate networks
            if 'networks' in service_config:
                networks = service_config['networks']
                if len(networks) != len(set(networks)):
                    duplicates = [n for n in networks if networks.count(n) > 1]
                    log_error(f"Service '{service_name}' has duplicate networks: {duplicates}")
                    return False
            
            # Check for duplicate labels
            if 'labels' in service_config:
                labels = service_config['labels']
                if len(labels) != len(set(labels)):
                    duplicates = [l for l in labels if labels.count(l) > 1]
                    log_warning(f"Service '{service_name}' has duplicate labels: {duplicates}")
        
        # Check for hardcoded volume names that should be templated
        if 'volumes' in compose_data:
            hardcoded_volumes = []
            for volume_name, volume_config in compose_data['volumes'].items():
                if isinstance(volume_config, dict) and 'name' in volume_config:
                    volume_name_value = volume_config['name']
                    # Check if the volume name is hardcoded (doesn't contain ${COMPOSE_PROJECT_NAME})
                    if not isinstance(volume_name_value, str) or '${COMPOSE_PROJECT_NAME}' not in volume_name_value:
                        hardcoded_volumes.append(f"{volume_name}: {volume_name_value}")
            
            if hardcoded_volumes:
                log_warning("Found hardcoded volume names that may cause conflicts between worktrees:")
                for hardcoded in hardcoded_volumes:
                    log_warning(f"  - {hardcoded}")
                log_warning("These volumes should use ${COMPOSE_PROJECT_NAME} prefix for proper isolation.")
        
        return True
    
    def _clean_legacy_dockertree_elements(self, compose_data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove legacy dockertree elements from compose data."""
        
        legacy_network_names = ['caddy_proxy', 'dockertree_caddy_proxy']
        legacy_label_patterns = ['caddy.proxy']
        
        for service_name, service_config in compose_data.get('services', {}).items():
            # Remove legacy dockertree networks
            if 'networks' in service_config:
                original_networks = service_config['networks']
                cleaned_networks = [n for n in original_networks if n not in legacy_network_names]
                if cleaned_networks:
                    service_config['networks'] = cleaned_networks
                else:
                    # Keep at least one default network if all were removed
                    service_config['networks'] = ['default']
            
            # Remove legacy dockertree labels
            if 'labels' in service_config:
                original_labels = service_config['labels']
                cleaned_labels = [
                    label for label in original_labels 
                    if not any(pattern in label for pattern in legacy_label_patterns)
                ]
                if cleaned_labels:
                    service_config['labels'] = cleaned_labels
                else:
                    del service_config['labels']
            
            # Remove ${COMPOSE_PROJECT_NAME} prefixes from container names
            if 'container_name' in service_config:
                container_name = service_config['container_name']
                if '${COMPOSE_PROJECT_NAME}' in container_name:
                    # Extract base name and remove the prefix
                    service_config['container_name'] = service_name
        
        # Remove legacy network definitions
        if 'networks' in compose_data:
            cleaned_networks = {
                name: config for name, config in compose_data['networks'].items()
                if name not in legacy_network_names
            }
            if cleaned_networks:
                compose_data['networks'] = cleaned_networks
            else:
                del compose_data['networks']
        
        return compose_data
    
    def clean_legacy_elements(self) -> bool:
        """Clean legacy dockertree elements from docker-compose.yml."""
        try:
            compose_file = self.project_root / "docker-compose.yml"
            if not compose_file.exists():
                log_error("docker-compose.yml not found in project root")
                return False
            
            # Read current compose file
            with open(compose_file) as f:
                compose_data = yaml.safe_load(f)
            
            if not compose_data or 'services' not in compose_data:
                log_error("Invalid docker-compose.yml file")
                return False
            
            # Clean legacy elements
            cleaned_data = self._clean_legacy_dockertree_elements(compose_data)
            
            # Write cleaned compose file
            with open(compose_file, 'w') as f:
                yaml.dump(cleaned_data, f, default_flow_style=False, sort_keys=False)
            
            log_success("Cleaned legacy dockertree elements from docker-compose.yml")
            return True
            
        except Exception as e:
            log_error(f"Failed to clean legacy elements: {e}")
            return False
    
    def _transform_volume_mounts(self, service_config: Dict[str, Any]) -> None:
        """Transform volume mounts for worktree compatibility."""
        if 'volumes' not in service_config:
            return
        
        volumes = service_config['volumes']
        
        # Handle list format volumes
        if isinstance(volumes, list):
            for i, volume in enumerate(volumes):
                if isinstance(volume, str):
                    # Transform main app mount: .:/app -> ${PROJECT_ROOT}:/app
                    if volume == '.:/app':
                        volumes[i] = '${PROJECT_ROOT}:/app'
                        log_info(f"Transformed main app volume mount: .:/app -> ${{PROJECT_ROOT}}:/app")
                    # Handle relative paths: ./path -> ${PROJECT_ROOT}/path
                    elif volume.startswith('./'):
                        relative_path = volume[2:]
                        volumes[i] = f"${{PROJECT_ROOT}}/{relative_path}"
                        log_info(f"Transformed relative volume mount: {volume} -> ${{PROJECT_ROOT}}/{relative_path}")
        
        # Handle dict format volumes (less common but possible)
        elif isinstance(volumes, dict):
            for volume_name, volume_config in volumes.items():
                if isinstance(volume_config, dict) and 'source' in volume_config:
                    source = volume_config['source']
                    if source == '.':
                        volume_config['source'] = '${PROJECT_ROOT}'
                        log_info(f"Transformed dict volume mount: {volume_name} source: . -> ${{PROJECT_ROOT}}")
                    elif isinstance(source, str) and source.startswith('./'):
                        relative_path = source[2:]
                        volume_config['source'] = f"${{PROJECT_ROOT}}/{relative_path}"
                        log_info(f"Transformed dict volume mount: {volume_name} source: {source} -> ${{PROJECT_ROOT}}/{relative_path}")
    
    def _transform_build_configuration(self, service_config: Dict[str, Any]) -> None:
        """Transform build configurations to use PROJECT_ROOT paths."""
        if 'build' not in service_config:
            return
        
        build = service_config['build']
        
        # Handle short format: build: "." or build: "./path"
        if isinstance(build, str):
            if build == '.':
                service_config['build'] = '${PROJECT_ROOT}'
                log_info(f"Transformed build context: . -> ${{PROJECT_ROOT}}")
            elif build.startswith('./'):
                relative_path = build[2:]
                service_config['build'] = f"${{PROJECT_ROOT}}/{relative_path}"
                log_info(f"Transformed build context: {build} -> ${{PROJECT_ROOT}}/{relative_path}")
        
        # Handle long format: build: { context: ..., dockerfile: ... }
        elif isinstance(build, dict):
            # Transform context path
            if 'context' in build:
                context = build['context']
                if context == '.':
                    build['context'] = '${PROJECT_ROOT}'
                    log_info(f"Transformed build context: . -> ${{PROJECT_ROOT}}")
                elif isinstance(context, str) and context.startswith('./'):
                    relative_path = context[2:]
                    build['context'] = f"${{PROJECT_ROOT}}/{relative_path}"
                    log_info(f"Transformed build context: {context} -> ${{PROJECT_ROOT}}/{relative_path}")
            
            # Transform dockerfile path if it's relative
            if 'dockerfile' in build:
                dockerfile = build['dockerfile']
                if isinstance(dockerfile, str) and dockerfile.startswith('./'):
                    relative_path = dockerfile[2:]
                    build['dockerfile'] = f"${{PROJECT_ROOT}}/{relative_path}"
                    log_info(f"Transformed dockerfile path: {dockerfile} -> ${{PROJECT_ROOT}}/{relative_path}")
    
    def _resolve_relative_paths(self, service_config: Dict[str, Any]) -> None:
        """Resolve relative paths in service configuration with intelligent path detection."""
        # Define patterns that should use project root (configuration files)
        project_root_patterns = [
            'config/', 'postgres-config/', 'nginx-config/', 'caddy-config/',
            'docker/', 'scripts/', 'templates/', 'docs/', 'migrations/',
            'fixtures/', 'static/', 'media/', 'logs/', 'env', '.env'
        ]
        
        # Define patterns that should use worktree paths (application files)
        worktree_patterns = [
            'src/', 'app/', 'code/', 'static/', 'media/', 'uploads/',
            'logs/', 'tmp/', 'cache/', 'data/', 'node_modules/'
        ]
        
        # Get worktree directory from config (defaults to 'worktrees')
        worktree_dir = get_worktree_dir()
        
        def _should_use_worktree_path(relative_path: str) -> bool:
            """Determine if path should use worktree or project root."""
            # Check for worktree-specific patterns first
            for pattern in worktree_patterns:
                if relative_path.startswith(pattern):
                    return True
            
            # Check for project root patterns
            for pattern in project_root_patterns:
                if relative_path.startswith(pattern):
                    return False
            
            # Default to worktree for application files
            return True
        
        def _transform_path(relative_path: str) -> str:
            """Transform relative path to environment variable-based path."""
            if _should_use_worktree_path(relative_path):
                return f"${{PROJECT_ROOT}}/{worktree_dir}/${{COMPOSE_PROJECT_NAME}}/{relative_path}"
            else:
                return f"${{PROJECT_ROOT}}/{relative_path}"
        
        # Handle volumes with relative paths
        if 'volumes' in service_config:
            volumes = service_config['volumes']
            if isinstance(volumes, list):
                for i, volume in enumerate(volumes):
                    if isinstance(volume, str) and volume.startswith('./'):
                        # Convert relative path to environment variable-based path
                        relative_path = volume[2:]  # Remove './' prefix
                        volumes[i] = _transform_path(relative_path)
            elif isinstance(volumes, dict):
                for volume_name, volume_config in volumes.items():
                    if isinstance(volume_config, dict) and 'source' in volume_config:
                        source = volume_config['source']
                        if isinstance(source, str) and source.startswith('./'):
                            relative_path = source[2:]  # Remove './' prefix
                            volume_config['source'] = _transform_path(relative_path)
        
        # Handle other configurations that might have relative paths
        for key, value in service_config.items():
            if isinstance(value, str) and value.startswith('./'):
                # Convert relative path to environment variable-based path
                relative_path = value[2:]  # Remove './' prefix
                service_config[key] = _transform_path(relative_path)
            elif isinstance(value, dict):
                # Recursively handle nested dictionaries
                self._resolve_relative_paths(value)
            elif isinstance(value, list):
                # Handle lists that might contain relative paths
                for i, item in enumerate(value):
                    if isinstance(item, str) and item.startswith('./'):
                        relative_path = item[2:]  # Remove './' prefix
                        value[i] = _transform_path(relative_path)
    
    def _validate_transformed_paths(self) -> bool:
        """Validate that transformed paths will work correctly."""
        try:
            worktree_compose = self.dockertree_dir / "docker-compose.worktree.yml"
            if not worktree_compose.exists():
                return True  # Nothing to validate yet
            
            # Read the transformed compose file
            with open(worktree_compose) as f:
                compose_data = yaml.safe_load(f)
            
            if not compose_data or 'services' not in compose_data:
                return True
            
            # Get worktree directory from config
            worktree_dir = get_worktree_dir()
            worktree_pattern = f'/{worktree_dir}/${{COMPOSE_PROJECT_NAME}}/'
            
            validation_issues = []
            
            # Check each service for path issues
            for service_name, service_config in compose_data['services'].items():
                if 'volumes' in service_config:
                    for volume in service_config['volumes']:
                        if isinstance(volume, str) and ':' in volume:
                            # Check if it's a bind mount with a path
                            source_path = volume.split(':')[0]
                            if source_path.startswith('${PROJECT_ROOT}/'):
                                # This is a transformed path, check if it makes sense
                                if worktree_pattern in source_path:
                                    # This is a worktree path - check if it's appropriate
                                    relative_part = source_path.split(worktree_pattern)[-1]
                                    if relative_part.startswith(('config/', 'postgres-config/', 'nginx-config/')):
                                        validation_issues.append(
                                            f"Service {service_name}: Configuration file '{relative_part}' "
                                            f"should use project root, not worktree path"
                                        )
                                elif source_path.endswith(('postgres-config/', 'nginx-config/', 'caddy-config/')):
                                    # This looks like a configuration directory
                                    log_info(f"✓ Service {service_name}: Configuration path looks correct")
            
            if validation_issues:
                log_warning("Path validation issues found:")
                for issue in validation_issues:
                    log_warning(f"  - {issue}")
                return False
            else:
                log_success("✓ All transformed paths look correct")
                return True
                
        except Exception as e:
            log_warning(f"Path validation failed: {e}")
            return True  # Don't fail setup due to validation issues
    
    
    def _create_config_file(self, project_name: Optional[str], compose_file: Path) -> bool:
        """Create config.yml file."""
        try:
            # Auto-detect project name if not provided
            if not project_name:
                project_name = self.project_root.name
            
            # Detect services from compose file
            with open(compose_file) as f:
                compose_data = yaml.safe_load(f)
            
            services = {}
            volumes = []
            
            if 'services' in compose_data:
                for service_name in compose_data['services'].keys():
                    services[service_name] = {
                        "container_name_template": f"${{COMPOSE_PROJECT_NAME}}-{service_name}"
                    }
            
            if 'volumes' in compose_data:
                volumes = list(compose_data['volumes'].keys())
            
            config = {
                'project_name': project_name,
                'caddy_network': 'dockertree_caddy_proxy',
                'worktree_dir': 'worktrees',
                'services': services,
                'volumes': volumes,
                'environment': {
                    'DEBUG': 'True',
                    'ALLOWED_HOSTS': 'localhost,127.0.0.1,*.localhost,web',
                }
            }
            
            config_file = self.dockertree_dir / "config.yml"
            with open(config_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
            log_success(f"Created config file: {config_file}")
            
            # Copy README.md to .dockertree directory
            if not self._copy_readme_file():
                log_warning("Failed to copy README.md to .dockertree directory")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to create config file: {e}")
            return False
    
    def _copy_readme_file(self) -> bool:
        """Copy README.md from package to .dockertree directory."""
        try:
            from ..config.settings import get_script_dir
            
            # Get source README.md from package
            script_dir = get_script_dir()
            source_readme = script_dir / "config" / "README.md"
            
            if not source_readme.exists():
                log_warning(f"Source README.md not found: {source_readme}")
                return False
            
            # Copy to .dockertree directory
            target_readme = self.dockertree_dir / "README.md"
            import shutil
            shutil.copy2(source_readme, target_readme)
            
            log_success(f"Copied README.md to: {target_readme}")
            return True
            
        except Exception as e:
            log_error(f"Failed to copy README.md: {e}")
            return False
    
    def _validate_project_root(self) -> bool:
        """Validate that PROJECT_ROOT environment variable is set correctly."""
        import os
        
        project_root = os.environ.get('PROJECT_ROOT')
        if not project_root:
            log_warning("PROJECT_ROOT environment variable not set")
            log_info("Setting PROJECT_ROOT to current project root...")
            os.environ['PROJECT_ROOT'] = str(self.project_root)
            project_root = str(self.project_root)
        
        # Validate that PROJECT_ROOT points to a valid directory
        project_root_path = Path(project_root)
        if not project_root_path.exists():
            log_error(f"PROJECT_ROOT path does not exist: {project_root}")
            return False
        
        if not project_root_path.is_dir():
            log_error(f"PROJECT_ROOT path is not a directory: {project_root}")
            return False
        
        # Check if it contains typical project files
        project_files = ['manage.py', 'requirements.txt', 'pyproject.toml', 'package.json', 'Dockerfile']
        has_project_files = any((project_root_path / file).exists() for file in project_files)
        
        if not has_project_files:
            log_warning(f"PROJECT_ROOT directory may not be a valid project root: {project_root}")
            log_info("Continuing anyway - this may be intentional for custom setups")
        
        log_success(f"PROJECT_ROOT validated: {project_root}")
        return True
    
    def _handle_gitignore_setup(self) -> bool:
        """Handle ignore file setup for dockertree directories."""
        try:
            # Get worktree directory from config (defaults to 'worktrees')
            worktree_dir = get_worktree_dir()
            worktrees_entry = f"{worktree_dir}/"
            old_entry = ".dockertree/worktrees/"
            
            success = True
            
            # Handle .gitignore
            log_info("The .dockertree directory contains configuration files that should be committed to version control.")
            log_info(f"However, {worktrees_entry} contains worktree directories that should NOT be committed.")
            
            # Check if old entry exists (migration case)
            if check_gitignore_entry(self.project_root, old_entry):
                log_info(f"Found old entry '{old_entry}' in .gitignore")
                log_info(f"Migrating to new worktree directory: {worktrees_entry}")
                
                if prompt_yes_no(f"Would you like to update .gitignore to use {worktrees_entry}?", default=True):
                    if replace_gitignore_entry(self.project_root, old_entry, worktrees_entry):
                        log_success(f"Updated .gitignore: now ignoring {worktrees_entry}")
                    else:
                        log_warning("Failed to update .gitignore")
                        success = False
                else:
                    log_info("Skipped updating .gitignore")
            # Check if correct entry already exists
            elif check_gitignore_entry(self.project_root, worktrees_entry):
                log_info(f"{worktrees_entry} is already in .gitignore")
            # New setup case
            else:
                if prompt_yes_no(f"Would you like to add {worktrees_entry} to your .gitignore file?", default=True):
                    if add_to_gitignore(self.project_root, worktrees_entry):
                        log_success(f"Added {worktrees_entry} to .gitignore")
                        log_info("✓ .dockertree/ directory will be committed")
                        log_info(f"✓ {worktrees_entry} will be ignored")
                    else:
                        log_warning(f"Failed to add {worktrees_entry} to .gitignore")
                        success = False
                else:
                    log_info("Skipped adding to .gitignore")
                    log_warning(f"Note: You may want to manually add {worktrees_entry} to .gitignore")
            
            # Handle .cursorignore (only if file exists)
            cursorignore_path = self.project_root / ".cursorignore"
            if cursorignore_path.exists():
                if prompt_yes_no(f"Would you like to add {worktrees_entry} to your .cursorignore file?", default=True):
                    if add_to_cursorignore(self.project_root, worktrees_entry):
                        log_success(f"Added {worktrees_entry} to .cursorignore")
                    else:
                        log_warning(f"Failed to add {worktrees_entry} to .cursorignore")
                        success = False
                else:
                    log_info("Skipped adding to .cursorignore")
            
            # Handle .cursorindexignore (only if file exists)
            cursorindexignore_path = self.project_root / ".cursorindexignore"
            if cursorindexignore_path.exists():
                if prompt_yes_no(f"Would you like to add {worktrees_entry} to your .cursorindexignore file?", default=True):
                    if add_to_cursorindexignore(self.project_root, worktrees_entry):
                        log_success(f"Added {worktrees_entry} to .cursorindexignore")
                    else:
                        log_warning(f"Failed to add {worktrees_entry} to .cursorindexignore")
                        success = False
                else:
                    log_info("Skipped adding to .cursorindexignore")
            
            return success
                
        except Exception as e:
            log_error(f"Failed to handle ignore file setup: {e}")
            return False
    
    def _handle_completion_setup(self) -> bool:
        """Handle shell completion setup for dockertree."""
        try:
            from .completion import CompletionManager
            
            completion_manager = CompletionManager()
            return completion_manager.prompt_install_completion()
            
        except Exception as e:
            log_error(f"Failed to handle completion setup: {e}")
            return False
    
    def is_setup_complete(self) -> bool:
        """Check if dockertree is already set up for this project."""
        config_file = self.dockertree_dir / "config.yml"
        compose_file = self.dockertree_dir / "docker-compose.worktree.yml"
        
        return all(f.exists() for f in [config_file, compose_file])
    
    def get_setup_status(self) -> Dict[str, Any]:
        """Get status of dockertree setup."""
        return {
            "dockertree_dir_exists": self.dockertree_dir.exists(),
            "config_file_exists": (self.dockertree_dir / "config.yml").exists(),
            "compose_file_exists": (self.dockertree_dir / "docker-compose.worktree.yml").exists(),
            "is_complete": self.is_setup_complete(),
            "project_root": str(self.project_root),
            "dockertree_dir": str(self.dockertree_dir)
        }
