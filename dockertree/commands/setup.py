"""
Setup command for dockertree CLI.

This module provides the setup command that initializes dockertree for a project.
"""

import re
import shutil
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
    
    def _get_examples_dir(self) -> Path:
        """Get path to examples directory in current project.
        
        Returns:
            Path to .dockertree directory where example files are stored
        """
        # Example files are stored directly in .dockertree directory
        return self.dockertree_dir
    
    def _generate_config_dict(self, project_name: str, compose_file: Path) -> Dict[str, Any]:
        """Generate config dictionary from project name and compose file.
        
        Extracts the logic currently in _create_config_file() to make it reusable.
        This method is called by both template-based and from-scratch creation paths.
        
        Args:
            project_name: Project name
            compose_file: Path to docker-compose.yml file
            
        Returns:
            Dictionary with complete config structure
        """
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
        
        return config
    
    def _generate_env_dockertree_content(self, branch_name: str = "master") -> str:
        """Generate env.dockertree content for project root.
        
        Reuses generate_env_compose_content() from settings.py for consistency.
        
        Args:
            branch_name: Branch name (defaults to "master" for project root)
            
        Returns:
            Environment file content string
        """
        from ..config.settings import generate_env_compose_content
        return generate_env_compose_content(branch_name)
    
    def setup_project(self, project_name: Optional[str] = None, domain: Optional[str] = None, ip: Optional[str] = None, non_interactive: bool = False, monkey_patch: bool = False) -> bool:
        """Initialize dockertree for a project.
        
        Args:
            project_name: Optional project name (defaults to directory name)
            domain: Optional domain override (subdomain.domain.tld) for production/staging
        """
        log_info("Setting up dockertree for this project...")
        if domain:
            log_info(f"Using domain override: {domain}")
        
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
        if not self._transform_compose_file(compose_file, domain, ip):
            return False
        
        # 3.5. Validate transformed paths
        if not self._validate_transformed_paths():
            log_warning("Some transformed paths may not work correctly")
            log_info("You may need to adjust paths in the generated compose file")
        
        # 4. Create config.yml
        if not self._create_config_file(project_name, compose_file):
            return False
        
        # 5. Create template env.dockertree for project root
        if not self._create_template_env_dockertree():
            log_warning("Failed to create template env.dockertree")
            # Don't fail setup, this is optional
        
        if non_interactive:
            # Non-interactive: silently ensure worktrees/ in .gitignore, skip completion
            try:
                from ..utils.file_utils import append_line_to_file
                gitignore_path = self.project_root / '.gitignore'
                append_line_to_file(gitignore_path, 'worktrees/')
                log_success("Added worktrees/ to .gitignore")
            except Exception:
                log_warning("Failed to update .gitignore silently in non-interactive mode")
        else:
            # 7. Ask user about adding .dockertree to .gitignore
            if not self._handle_gitignore_setup():
                log_warning("Gitignore setup was skipped or failed")
            
            # 8. Ask user about installing shell completion
            if not self._handle_completion_setup():
                log_warning("Completion setup was skipped or failed")
        
        # 9. Django-specific guidance and optional patching
        try:
            self._django_post_setup_checks(monkey_patch=monkey_patch, non_interactive=non_interactive)
        except Exception as e:
            log_warning(f"Django compatibility checks skipped: {e}")
        
        log_success("Dockertree setup completed successfully!")
        log_info(f"Configuration: {self.dockertree_dir}/config.yml")
        log_info("Next: dockertree start")
        return True

    def _django_post_setup_checks(self, monkey_patch: bool, non_interactive: bool) -> None:
        """If this looks like a Django project, validate env-driven settings and guide user.

        Checks for: ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, USE_X_FORWARDED_HOST, SECURE_PROXY_SSL_HEADER.
        Optionally monkey-patches settings.py to read these from env vars.
        """
        project_root = self.project_root
        manage_py = project_root / "manage.py"
        if not manage_py.exists():
            return
        settings_path = self._locate_django_settings(project_root)
        if not settings_path:
            return

        missing = self._find_missing_env_config(settings_path)
        if not missing:
            log_success("✓ Django settings appear to read required values from environment variables")
            return

        log_warning("Django settings are not fully environment-driven for reverse proxy/Caddy:")
        for item in missing:
            log_warning(f"  - {item}")

        self._print_django_guidance()

        if monkey_patch:
            ok = self._monkey_patch_settings(settings_path)
            if ok:
                log_success(f"Applied monkey patch to: {settings_path}")
            else:
                log_warning("Monkey patch failed; please update settings manually using the guidance above.")

    def _locate_django_settings(self, root: Path) -> Optional[Path]:
        """Heuristically find Django settings.py."""
        # common locations: project_name/settings.py; any */settings.py near manage.py
        candidates = list(root.glob("**/settings.py"))
        # Prefer a settings.py in same tree as manage.py
        for cand in candidates:
            if (cand.parent / "__init__.py").exists():
                return cand
        return candidates[0] if candidates else None

    def _find_missing_env_config(self, settings_py: Path) -> list[str]:
        """Naively scan settings.py for env-driven configuration of required keys."""
        text = settings_py.read_text()
        missing: list[str] = []
        def lacks(patterns: list[str]) -> bool:
            return not any(p in text for p in patterns)

        # ALLOWED_HOSTS from env (comma-split or similar)
        if lacks(["ALLOWED_HOSTS = os.getenv", "ALLOWED_HOSTS=os.getenv", "env('ALLOWED_HOSTS'", "split(", "] for parsing"]):
            missing.append("ALLOWED_HOSTS from env (comma-separated)")
        # CSRF_TRUSTED_ORIGINS from env (space-separated)
        if lacks(["CSRF_TRUSTED_ORIGINS = os.getenv", "env('CSRF_TRUSTED_ORIGINS'", "split("]):
            missing.append("CSRF_TRUSTED_ORIGINS from env (space-separated)")
        # USE_X_FORWARDED_HOST from env
        if lacks(["USE_X_FORWARDED_HOST = os.getenv", "env('USE_X_FORWARDED_HOST'"]):
            missing.append("USE_X_FORWARDED_HOST from env (True/False)")
        # SECURE_PROXY_SSL_HEADER from env (tuple encoded as 'HTTP_X_FORWARDED_PROTO,https')
        if lacks(["SECURE_PROXY_SSL_HEADER =", "SECURE_PROXY_SSL_HEADER = tuple("]):
            missing.append("SECURE_PROXY_SSL_HEADER from env ('HTTP_X_FORWARDED_PROTO,https')")
        return missing

    def _print_django_guidance(self) -> None:
        log_info("")
        log_info("Guidance for Django behind Caddy (copy into settings.py):")
        log_info("""
import os

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "").split()

USE_X_FORWARDED_HOST = os.getenv("USE_X_FORWARDED_HOST", "False") == "True"
_hdr = os.getenv("SECURE_PROXY_SSL_HEADER")
if _hdr:
    SECURE_PROXY_SSL_HEADER = tuple(_hdr.split(",", 1))
        """)

    def _monkey_patch_settings(self, settings_py: Path) -> bool:
        try:
            text = settings_py.read_text()
            block = (
                "\n\n# Dockertree auto-added settings for reverse proxy and env-driven config\n"
                "import os\n"
                "ALLOWED_HOSTS = os.getenv(\"ALLOWED_HOSTS\", \"localhost,127.0.0.1\").split(\",\")\n"
                "CSRF_TRUSTED_ORIGINS = os.getenv(\"CSRF_TRUSTED_ORIGINS\", \"\").split()\n"
                "USE_X_FORWARDED_HOST = os.getenv(\"USE_X_FORWARDED_HOST\", \"False\") == \"True\"\n"
                "_hdr = os.getenv(\"SECURE_PROXY_SSL_HEADER\")\n"
                "if _hdr:\n    SECURE_PROXY_SSL_HEADER = tuple(_hdr.split(\",\", 1))\n"
            )
            if "Dockertree auto-added settings" in text:
                return True
            settings_py.write_text(text + block)
            return True
        except Exception as e:
            log_warning(f"Failed to patch settings.py: {e}")
            return False
    
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
    
    def _transform_compose_file(self, source_compose: Path, domain: Optional[str] = None, ip: Optional[str] = None) -> bool:
        """Transform compose file for worktree use.
        
        Args:
            source_compose: Path to source docker-compose.yml
            domain: Optional domain override (subdomain.domain.tld) for production/staging
        """
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
                    
                    # Use domain override if provided, otherwise use localhost pattern
                    if domain:
                        # For production/staging, use the provided domain
                        proxy_domain = domain
                        log_info(f"Using production domain for {service_name}: {domain}")
                    elif ip:
                        # IP deployments - HTTP only, no automatic HTTPS
                        proxy_domain = ip
                        log_warning("IP deployments are HTTP-only. Let's Encrypt requires a domain name.")
                    else:
                        # For development, use localhost pattern
                        proxy_domain = "${COMPOSE_PROJECT_NAME}.localhost"
                    
                    new_labels = [
                        f"caddy.proxy={proxy_domain}",
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

                    # Ensure a named volume mount exists for SQLite persistence
                    # Mount a named volume at /data so Django can point SQLite NAME to /data/db.sqlite3
                    volumes_list = service_config.setdefault('volumes', [])
                    # Normalize to list
                    if isinstance(volumes_list, dict):
                        # Convert uncommon dict format to list mount (source:target)
                        normalized = []
                        for vname, vcfg in volumes_list.items():
                            target = vcfg.get('target') if isinstance(vcfg, dict) else None
                            if target:
                                normalized.append(f"{vname}:{target}")
                        service_config['volumes'] = volumes_list = normalized
                    if all(not (isinstance(v, str) and v.split(':',1)[0] == 'sqlite_data') for v in volumes_list):
                        volumes_list.append('sqlite_data:/data')
                
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
                
                # Add env_file directive to load both .env and dockertree env files
                if 'env_file' not in service_config:
                    service_config['env_file'] = []
                elif isinstance(service_config['env_file'], str):
                    # Convert string to list for consistency
                    service_config['env_file'] = [service_config['env_file']]
                
                # Ensure we have a list to work with
                if not isinstance(service_config['env_file'], list):
                    service_config['env_file'] = []
                
                # Ensure we load both .env (project variables) and env.dockertree (worktree variables)
                # Order matters: env.dockertree is listed second so it can override values from .env
                env_files_to_add = [
                    '${PROJECT_ROOT}/.env',
                    '${PROJECT_ROOT}/.dockertree/env.dockertree'
                ]
                
                for env_file in env_files_to_add:
                    if env_file not in service_config['env_file']:
                        service_config['env_file'].append(env_file)
                
                log_info(f"Added env_file directives to service '{service_name}'")
                
                # Transform volume mounts for worktree compatibility
                self._transform_volume_mounts(service_config)
                
                # Transform build configurations for worktree compatibility
                self._transform_build_configuration(service_config)
                
                # Resolve relative paths in volumes and other configurations
                self._resolve_relative_paths(service_config)
            
            # Ensure volumes section exists so we can add sqlite_data named volume
            compose_data.setdefault('volumes', {})

            # Add sqlite_data volume definition if not present (worktree transform will name it per branch)
            if 'sqlite_data' not in compose_data['volumes']:
                compose_data['volumes']['sqlite_data'] = None

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
        """Create config.yml file.
        
        If .dockertree/config.yml does not exist, checks for example template first.
        If example exists, copies and edits it. Otherwise creates from scratch.
        """
        try:
            config_file = self.dockertree_dir / "config.yml"
            
            # Don't overwrite if it already exists
            if config_file.exists():
                log_info("config.yml already exists, skipping creation")
                return True
            
            # Auto-detect project name if not provided
            if not project_name:
                project_name = self.project_root.name
            
            # Generate config dict (single source of truth)
            config = self._generate_config_dict(project_name, compose_file)
            
            # Check if example template exists
            examples_dir = self._get_examples_dir()
            example_config = examples_dir / "example.config.yml"
            
            if example_config.exists():
                # Copy example template and edit it
                # Copy example to target location
                shutil.copy2(example_config, config_file)
                log_info(f"Copied example template from {example_config}")
                
                # Read the copied file
                content = config_file.read_text()
                
                # Uncomment and set project_name
                content = re.sub(
                    r'^# project_name:.*',
                    f'project_name: {project_name}',
                    content,
                    flags=re.MULTILINE
                )
                
                # Uncomment and set caddy_network
                content = re.sub(
                    r'^# caddy_network:.*',
                    f"caddy_network: {config['caddy_network']}",
                    content,
                    flags=re.MULTILINE
                )
                
                # Uncomment and set worktree_dir
                content = re.sub(
                    r'^# worktree_dir:.*',
                    f"worktree_dir: {config['worktree_dir']}",
                    content,
                    flags=re.MULTILINE
                )
                
                # Uncomment services section and add detected services
                # Replace the entire services section with actual services
                services_yaml = yaml.dump({'services': config['services']}, default_flow_style=False, sort_keys=False)
                # Find services section (from "services:" to next "# ==" or end of section)
                services_match = re.search(r'^services:.*?(?=^# =|^volumes:|$)', content, re.MULTILINE | re.DOTALL)
                if services_match:
                    # Replace the matched section
                    content = content[:services_match.start()] + services_yaml + content[services_match.end():]
                else:
                    # If not found, just replace "services:" line
                    content = re.sub(r'^services:', services_yaml, content, flags=re.MULTILINE)
                
                # Uncomment and set volumes
                volumes_yaml = yaml.dump({'volumes': config['volumes']}, default_flow_style=False, sort_keys=False)
                volumes_match = re.search(r'^volumes:.*?(?=^# =|^environment:|$)', content, re.MULTILINE | re.DOTALL)
                if volumes_match:
                    content = content[:volumes_match.start()] + volumes_yaml + content[volumes_match.end():]
                else:
                    content = re.sub(r'^volumes:', volumes_yaml, content, flags=re.MULTILINE)
                
                # Uncomment and set environment variables
                env_yaml = yaml.dump({'environment': config['environment']}, default_flow_style=False, sort_keys=False)
                env_match = re.search(r'^environment:.*?(?=^# =|$)', content, re.MULTILINE | re.DOTALL)
                if env_match:
                    content = content[:env_match.start()] + env_yaml + content[env_match.end():]
                else:
                    content = re.sub(r'^environment:', env_yaml, content, flags=re.MULTILINE)
                
                # Write edited content
                config_file.write_text(content)
                log_success(f"Created config file from template: {config_file}")
            else:
                # No example template, create from scratch (existing behavior)
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
    
    def _create_template_env_dockertree(self) -> bool:
        """Create template env.dockertree for project root (enables master branch usage).
        
        If .dockertree/env.dockertree does not exist, checks for example template first.
        If example exists, copies and edits it. Otherwise creates from scratch.
        """
        try:
            env_dockertree_path = self.dockertree_dir / "env.dockertree"
            
            # Don't overwrite if it already exists
            if env_dockertree_path.exists():
                log_info("env.dockertree already exists, skipping creation")
                return True
            
            # Generate env content (reuses settings.py logic)
            env_content = self._generate_env_dockertree_content("master")
            
            # Check if example template exists
            examples_dir = self._get_examples_dir()
            example_env = examples_dir / "example.env.dockertree"
            
            if example_env.exists():
                # Copy example template and edit it
                # Copy example to target location
                shutil.copy2(example_env, env_dockertree_path)
                log_info(f"Copied example template from {example_env}")
                
                # Read the copied file
                content = env_dockertree_path.read_text()
                
                # Parse generated content to extract values
                # Format: KEY=value
                env_vars = {}
                for line in env_content.split('\n'):
                    if '=' in line and not line.strip().startswith('#'):
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
                
                # Uncomment and set each variable
                for key, value in env_vars.items():
                    # Pattern: # KEY=value or #KEY=value
                    pattern = rf'^#\s*{re.escape(key)}=.*'
                    replacement = f'{key}={value}'
                    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
                
                # Write edited content
                env_dockertree_path.write_text(content)
                log_success(f"Created template env.dockertree from template: {env_dockertree_path}")
            else:
                # No example template, create from scratch (existing behavior)
                env_dockertree_path.write_text(env_content)
                log_success(f"Created template env.dockertree: {env_dockertree_path}")
            
            log_info("This enables using dockertree commands with the master branch")
            return True
            
        except Exception as e:
            log_error(f"Failed to create template env.dockertree: {e}")
            return False
    
    def _regenerate_example_files(self) -> bool:
        """Regenerate example.config.yml and example.env.dockertree in examples/ directory.
        
        Uses same structure as active config generation but with all settings commented.
        Ensures example files stay in sync with actual config structure.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            examples_dir = self._get_examples_dir()
            examples_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate example.config.yml
            example_config_path = examples_dir / "example.config.yml"
            
            # Read the existing example file if it exists to preserve structure
            # Otherwise generate from scratch
            if example_config_path.exists():
                log_info("Regenerating example.config.yml (preserving existing structure)")
            else:
                log_info("Creating example.config.yml")
            
            # For now, we'll write a comprehensive template
            # In the future, this could parse existing configs to generate examples
            config_template = """# Dockertree Project Configuration Template
# This file serves as a comprehensive template with all possible settings
# Uncomment and modify settings as needed for your project
# 
# When running `dockertree setup`, if .dockertree/config.yml does not exist,
# this template will be copied and automatically configured based on your
# docker-compose.yml file.

# ============================================================================
# Project Identification
# ============================================================================

# Project name (used in container names, volumes, and domains)
# Default: directory name
# Automatically set during setup based on project directory name
# project_name: myproject

# ============================================================================
# Network Configuration
# ============================================================================

# Docker network name for Caddy proxy
# Default: dockertree_caddy_proxy
# This network is shared across all worktrees for routing
# caddy_network: dockertree_caddy_proxy

# ============================================================================
# Directory Configuration
# ============================================================================

# Directory where worktrees are stored
# Default: worktrees
# Worktrees will be created in {project_root}/{worktree_dir}/{branch_name}/
# worktree_dir: worktrees

# ============================================================================
# Service Configuration
# ============================================================================

# Service configuration
# Automatically detected from docker-compose.yml during setup
# Each service can have a container_name_template
# The ${COMPOSE_PROJECT_NAME} variable is automatically set per worktree
# Format: {project_name}-{branch_name}
services:
  # Example web service
  # web:
  #   container_name_template: ${COMPOSE_PROJECT_NAME}-web
  
  # Example database service
  # db:
  #   container_name_template: ${COMPOSE_PROJECT_NAME}-db
  
  # Example Redis service
  # redis:
  #   container_name_template: ${COMPOSE_PROJECT_NAME}-redis
  
  # Add more services as needed:
  # api:
  #   container_name_template: ${COMPOSE_PROJECT_NAME}-api
  # worker:
  #   container_name_template: ${COMPOSE_PROJECT_NAME}-worker

# ============================================================================
# Volume Configuration
# ============================================================================

# Volume names (automatically detected from docker-compose.yml)
# These will be prefixed with {project_name}-{branch_name}_ for each worktree
# Example: myproject-feature-auth_postgres_data
volumes:
  # Example PostgreSQL volume
  # - postgres_data
  
  # Example Redis volume
  # - redis_data
  
  # Example media files volume
  # - media_files
  
  # Add more volumes as needed:
  # - sqlite_data
  # - static_files
  # - uploads

# ============================================================================
# Default Environment Variables
# ============================================================================

# Default environment variables for all worktrees
# These can be overridden in worktree-specific env.dockertree files
# These values are used as defaults when creating new worktrees
environment:
  # Debug mode (True for development, False for production)
  # DEBUG: "True"
  
  # Allowed hosts for Django/Flask applications
  # Automatically includes localhost, 127.0.0.1, worktree domain, *.localhost, and web
  # ALLOWED_HOSTS: "localhost,127.0.0.1,*.localhost,web"
  
  # Add more default environment variables:
  # POSTGRES_USER: "user"
  # POSTGRES_PASSWORD: "password"
  # POSTGRES_DB: "database"
  # DJANGO_SECRET_KEY: "django-insecure-secret-key"
  # SITE_DOMAIN: "localhost:8000"
  # CADDY_EMAIL: "admin@example.com"

# ============================================================================
# Deployment Configuration (Optional)
# ============================================================================

# Deployment configuration
# Used by 'dockertree push' command
# These settings provide defaults for deployment operations
# deployment:
  # Default server for push operations
  # Format: username@hostname:/path/to/packages
  # Example: user@server.example.com:/var/dockertree/packages
  # default_server: user@server.example.com:/var/dockertree/packages
  
  # Default domain for HTTPS deployments
  # Used when --domain flag is not provided to push command
  # Example: myapp.example.com
  # default_domain: myapp.example.com
  
  # Default IP for HTTP-only deployments
  # Used when --ip flag is not provided to push command
  # Note: IP-only deployments are HTTP-only (no TLS)
  # Example: 203.0.113.10
  # default_ip: 203.0.113.10
  
  # SSH key path for deployment
  # Used for SCP operations during push
  # Example: ~/.ssh/deploy_key
  # ssh_key: ~/.ssh/deploy_key

# ============================================================================
# DNS Configuration (Optional)
# ============================================================================

# DNS configuration
# Used for automatic DNS management during deployment
# Currently supports Digital Ocean DNS API
# dns:
  # DNS provider (currently only 'digitalocean' is supported)
  # provider: digitalocean
  
  # API token for DNS provider
  # Can use environment variable: ${DIGITALOCEAN_API_TOKEN} or ${DNS_API_TOKEN}
  # Priority: CLI flag > shell environment > .env file > this config file
  # api_token: ${DIGITALOCEAN_API_TOKEN}
  
  # Default domain for DNS operations
  # Used when creating subdomains during deployment
  # Example: example.com
  # default_domain: example.com
"""
            
            example_config_path.write_text(config_template)
            log_success(f"Regenerated example.config.yml: {example_config_path}")
            
            # Generate example.env.dockertree
            example_env_path = examples_dir / "example.env.dockertree"
            
            if example_env_path.exists():
                log_info("Regenerating example.env.dockertree (preserving existing structure)")
            else:
                log_info("Creating example.env.dockertree")
            
            # Read the existing example file content (we already created it, so use that)
            # But for regeneration, we'll write the comprehensive template
            env_template = """# Dockertree Environment Configuration Template
# This file serves as a comprehensive template with all possible environment variables
# Uncomment and modify variables as needed for your project
#
# This file is automatically sourced by Docker Compose
# Variables here override those in .env files
#
# When running `dockertree setup`, if .dockertree/env.dockertree does not exist,
# this template will be copied and automatically configured for the project root.

# ============================================================================
# Project Identification
# ============================================================================

# Docker Compose project name (automatically set per worktree)
# Format: {project_name}-{branch_name}
# For project root, uses: {project_name}-master
# COMPOSE_PROJECT_NAME=myproject-master

# Project root directory (automatically set)
# Points to the worktree directory
# PROJECT_ROOT=${PWD}

# ============================================================================
# Domain and Host Configuration
# ============================================================================

# Site domain for the worktree
# Local development: {project_name}-{branch_name}.localhost
# Production: https://subdomain.example.com
# IP-only: http://203.0.113.10
# SITE_DOMAIN=myproject-master.localhost

# Allowed hosts for Django/Flask applications
# Automatically includes localhost, 127.0.0.1, worktree domain, *.localhost, and web
# Format: comma-separated list
# ALLOWED_HOSTS=localhost,127.0.0.1,myproject-master.localhost,*.localhost,web

# ============================================================================
# Django Configuration
# ============================================================================

# Debug mode (True for development, False for production)
# DEBUG=True

# Django secret key (use a secure random key in production)
# Generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# DJANGO_SECRET_KEY=django-insecure-secret-key

# Enable X-Forwarded-Host header support (required for reverse proxy)
# Set to True when using Caddy or other reverse proxies
# USE_X_FORWARDED_HOST=True

# CSRF trusted origins (space-separated URLs)
# For localhost: http://{project_name}-{branch_name}.localhost
# For domains: https://subdomain.example.com http://subdomain.example.com
# CSRF_TRUSTED_ORIGINS=http://myproject-master.localhost

# Secure proxy SSL header (tuple format for Django)
# Format: HTTP_X_FORWARDED_PROTO,https
# Used to detect HTTPS when behind a reverse proxy
# SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https

# ============================================================================
# Database Configuration (PostgreSQL)
# ============================================================================

# PostgreSQL user
# POSTGRES_USER=user

# PostgreSQL password
# POSTGRES_PASSWORD=password

# PostgreSQL database name
# POSTGRES_DB=database

# PostgreSQL host (automatically set to worktree-specific container)
# Format: ${COMPOSE_PROJECT_NAME}-db
# POSTGRES_HOST=${COMPOSE_PROJECT_NAME}-db

# PostgreSQL port
# POSTGRES_PORT=5432

# Database URL (automatically constructed)
# Format: postgres://user:password@host:port/database
# DATABASE_URL=postgres://user:password@${COMPOSE_PROJECT_NAME}-db:5432/database

# ============================================================================
# Redis Configuration
# ============================================================================

# Redis host (automatically set to worktree-specific container)
# Format: ${COMPOSE_PROJECT_NAME}-redis
# REDIS_HOST=${COMPOSE_PROJECT_NAME}-redis

# Redis port
# REDIS_PORT=6379

# Redis database number
# REDIS_DB=0

# Redis URL (automatically constructed)
# Format: redis://host:port/db
# REDIS_URL=redis://${COMPOSE_PROJECT_NAME}-redis:6379/0

# ============================================================================
# Caddy Proxy Configuration
# ============================================================================

# Email for Let's Encrypt certificate notifications
# Used when deploying with HTTPS via Caddy
# CADDY_EMAIL=admin@example.com

# ============================================================================
# DNS Provider Configuration (for deployment)
# ============================================================================

# Digital Ocean API token (for automatic DNS management)
# Can also be set via environment variable: DIGITALOCEAN_API_TOKEN or DNS_API_TOKEN
# Priority: CLI flag > shell env > .env file > this file
# DIGITALOCEAN_API_TOKEN=your_token_here

# Generic DNS API token (alternative to DIGITALOCEAN_API_TOKEN)
# DNS_API_TOKEN=your_token_here

# ============================================================================
# Droplet/Server Configuration (for deployment)
# ============================================================================

# Default region for droplet creation
# Used with dockertree droplets create command
# Example: nyc1, sfo3, lon1
# DROPLET_DEFAULT_REGION=nyc1

# Default size for droplet creation
# Used with dockertree droplets create command
# Example: s-1vcpu-1gb, s-2vcpu-4gb
# DROPLET_DEFAULT_SIZE=s-1vcpu-1gb

# Default image for droplet creation
# Used with dockertree droplets create command
# Example: ubuntu-22-04-x64, ubuntu-20-04-x64
# DROPLET_DEFAULT_IMAGE=ubuntu-22-04-x64

# Default SSH keys for droplet creation (comma-separated)
# Used with dockertree droplets create and push commands
# SSH key names (comma-separated, e.g., anders,peter)
# Only key names are supported, not numeric IDs or fingerprints
# DROPLET_DEFAULT_SSH_KEYS=anders,peter

# ============================================================================
# Application-Specific Configuration
# ============================================================================

# Add your application-specific environment variables below:
# CUSTOM_SETTING=value
# API_KEY=your_api_key
# EXTERNAL_SERVICE_URL=https://api.example.com
# LOG_LEVEL=INFO
# SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
"""
            
            example_env_path.write_text(env_template)
            log_success(f"Regenerated example.env.dockertree: {example_env_path}")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to regenerate example files: {e}")
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
            old_entry = f"{worktree_dir}/"  # For migration from old path references
            
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
