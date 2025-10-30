"""
Environment management for dockertree CLI.

This module provides environment file generation, volume naming, and
configuration management for worktree environments.
"""

from pathlib import Path
from typing import Dict, Optional

from ..config.settings import (
    generate_env_compose_content, 
    get_volume_names,
    DEFAULT_ENV_VARS,
    get_project_root
)
from ..utils.logging import log_info, log_success, log_warning
from ..utils.path_utils import (
    get_env_file_path, 
    get_env_compose_file_path,
    copy_env_file
)


class EnvironmentManager:
    """Manages environment configuration for dockertree CLI."""
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialize environment manager.
        
        Args:
            project_root: Project root directory. If None, uses get_project_root().
        """
        # Use the provided project_root directly, don't fall back to get_project_root()
        # This ensures MCP server uses the correct working directory
        if project_root is None:
            self.project_root = get_project_root()
        else:
            self.project_root = Path(project_root).resolve()
    
    def create_worktree_env(self, branch_name: str, worktree_path: Path, 
                           source_env_path: Optional[Path] = None,
                           domain: Optional[str] = None) -> bool:
        """Create worktree environment files.
        
        Args:
            branch_name: Branch name for the worktree
            worktree_path: Path to the worktree directory
            source_env_path: Optional source .env file path
            domain: Optional domain override (subdomain.domain.tld) for production/staging
            
        Returns:
            True if successful, False otherwise
        """
        log_info("Creating worktree environment files")
        
        # Ensure worktree directory exists
        worktree_path.mkdir(parents=True, exist_ok=True)
        
        # Copy .env file if it exists
        env_copied = False
        if source_env_path:
            env_copied = copy_env_file(source_env_path, worktree_path)
        else:
            # Try to find .env in project root
            env_copied = copy_env_file(self.project_root, worktree_path)
        
        if not env_copied:
            log_warning("No .env file found to copy, creating default .env file")
            # Create a default .env file if none exists
            if not self._create_default_env_file(worktree_path, branch_name, domain):
                log_warning("Failed to create default .env file")
        
        # Create env.dockertree with worktree-specific settings
        # Ensure .dockertree directory exists
        dockertree_dir = worktree_path / ".dockertree"
        dockertree_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate environment content, applying domain overrides if provided
        if domain:
            env_compose_content = self._generate_env_compose_with_domain(branch_name, domain)
        else:
            env_compose_content = generate_env_compose_content(branch_name)
            
        env_compose_path = get_env_compose_file_path(worktree_path)
        
        try:
            env_compose_path.write_text(env_compose_content)
            
            # Apply domain overrides to .env file if domain is provided
            if domain:
                self.apply_domain_overrides(worktree_path, domain)
                
            log_success(f"Environment files created for {branch_name}")
            return True
        except Exception as e:
            log_warning(f"Failed to create environment file: {e}")
            return False
    
    def _create_default_env_file(self, worktree_path: Path, branch_name: str, 
                                 domain: Optional[str] = None) -> bool:
        """Create a default .env file if none exists.
        
        Args:
            worktree_path: Path to worktree directory
            branch_name: Branch name
            domain: Optional domain override (subdomain.domain.tld)
        """
        from ..config.settings import get_project_name, sanitize_project_name, get_allowed_hosts_for_worktree, DEFAULT_ENV_VARS
        
        env_file = worktree_path / ".env"
        
        # Don't overwrite existing .env file
        if env_file.exists():
            return True
        
        # Create default environment content with project prefix
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        
        # Use domain override if provided, otherwise use localhost
        if domain:
            site_domain = f"https://{domain}"
            allowed_hosts = f"localhost,127.0.0.1,{domain},*.{domain.split('.', 1)[1] if '.' in domain else domain},web"
        else:
            site_domain = f"{project_name}-{branch_name}.localhost"
            allowed_hosts = get_allowed_hosts_for_worktree(branch_name)
        
        default_env_content = f"""# Default environment configuration for {branch_name}
# This file was automatically created by dockertree

# Database configuration
POSTGRES_USER=biuser
POSTGRES_PASSWORD=bipassword
POSTGRES_DB=database

# Django configuration
DEBUG=True
DJANGO_SECRET_KEY=django-insecure-secret-key
ALLOWED_HOSTS={allowed_hosts}
SITE_DOMAIN={site_domain}

# Redis configuration
REDIS_HOST={compose_project_name}-redis
REDIS_PORT=6379
REDIS_DB=0

# Caddy configuration
CADDY_EMAIL={DEFAULT_ENV_VARS['CADDY_EMAIL']}
"""
        
        try:
            env_file.write_text(default_env_content)
            log_info(f"Created default .env file for {branch_name}")
            return True
        except Exception as e:
            log_warning(f"Failed to create default .env file: {e}")
            return False
    
    def get_worktree_volume_names(self, branch_name: str) -> Dict[str, str]:
        """Get worktree-specific volume names."""
        return get_volume_names(branch_name)
    
    def get_environment_variables(self, branch_name: str) -> Dict[str, str]:
        """Get environment variables for a worktree."""
        from ..config.settings import get_project_name, sanitize_project_name, get_allowed_hosts_for_worktree
        
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        site_domain = f"{project_name}-{branch_name}.localhost"
        
        env_vars = DEFAULT_ENV_VARS.copy()
        env_vars.update({
            "COMPOSE_PROJECT_NAME": compose_project_name,
            "SITE_DOMAIN": site_domain,
            "ALLOWED_HOSTS": get_allowed_hosts_for_worktree(branch_name),
        })
        return env_vars
    
    def validate_environment_file(self, env_file_path: Path) -> bool:
        """Validate that an environment file exists and is readable."""
        if not env_file_path.exists():
            return False
        
        try:
            content = env_file_path.read_text()
            return len(content.strip()) > 0
        except Exception:
            return False
    
    def get_domain_name(self, branch_name: str) -> str:
        """Get the domain name for a worktree."""
        from ..config.settings import get_project_name, sanitize_project_name
        project_name = sanitize_project_name(get_project_name())
        return f"{project_name}-{branch_name}.localhost"

    def get_access_url(self, branch_name: str) -> str:
        """Get the preferred access URL for a worktree.

        If env.dockertree defines SITE_DOMAIN starting with http(s):// use it directly.
        Otherwise, construct http://{domain}/ where domain is either SITE_DOMAIN or
        the default {project}-{branch}.localhost fallback.
        """
        try:
            # Attempt to read SITE_DOMAIN from worktree env.dockertree
            from ..config.settings import get_worktree_paths
            new_path, legacy_path = get_worktree_paths(branch_name)
            env_path = get_env_compose_file_path(new_path)
            if not env_path.exists() and legacy_path.exists():
                env_path = get_env_compose_file_path(legacy_path)
            site_domain_value = None
            if env_path.exists():
                content = env_path.read_text()
                for line in content.splitlines():
                    if line.startswith('SITE_DOMAIN='):
                        site_domain_value = line.split('=', 1)[1].strip()
                        break
            if site_domain_value:
                # If already a full URL, return as-is
                if site_domain_value.startswith('http://') or site_domain_value.startswith('https://'):
                    return site_domain_value.rstrip('/')
                # Else treat as hostname
                return f"http://{site_domain_value}"
        except Exception:
            pass
        # Fallback: build from computed domain
        return f"http://{self.get_domain_name(branch_name)}"
    
    def get_allowed_hosts(self, branch_name: str) -> str:
        """Get the allowed hosts for a worktree."""
        from ..config.settings import get_allowed_hosts_for_worktree
        return get_allowed_hosts_for_worktree(branch_name)
    
    def get_database_url(self, branch_name: str, 
                        postgres_user: str = "biuser",
                        postgres_password: str = "bipassword",
                        postgres_db: str = "database") -> str:
        """Get the database URL for a worktree."""
        from ..config.settings import get_project_name, sanitize_project_name
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        return f"postgres://{postgres_user}:{postgres_password}@{compose_project_name}-db:5432/{postgres_db}"
    
    def get_redis_url(self, branch_name: str, redis_port: int = 6379, redis_db: int = 0) -> str:
        """Get the Redis URL for a worktree."""
        from ..config.settings import get_project_name, sanitize_project_name
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        return f"redis://{compose_project_name}-redis:{redis_port}/{redis_db}"
    
    def generate_compose_environment(self, branch_name: str) -> Dict[str, str]:
        """Generate environment variables for docker compose."""
        from ..config.settings import get_project_name, sanitize_project_name
        
        env_vars = self.get_environment_variables(branch_name)
        
        # Add database and Redis URLs with project prefix
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        
        env_vars["DATABASE_URL"] = self.get_database_url(branch_name)
        env_vars["REDIS_HOST"] = f"{compose_project_name}-redis"
        env_vars["REDIS_PORT"] = "6379"
        env_vars["REDIS_DB"] = "0"
        
        return env_vars
    
    def create_env_file_from_template(self, template_path: Path, 
                                    target_path: Path, 
                                    branch_name: str) -> bool:
        """Create an environment file from a template."""
        if not template_path.exists():
            log_warning(f"Template file {template_path} not found")
            return False
        
        try:
            content = template_path.read_text()
            
            # Replace placeholders
            content = content.replace("{{BRANCH_NAME}}", branch_name)
            content = content.replace("{{DOMAIN_NAME}}", self.get_domain_name(branch_name))
            content = content.replace("{{ALLOWED_HOSTS}}", self.get_allowed_hosts(branch_name))
            content = content.replace("{{DATABASE_URL}}", self.get_database_url(branch_name))
            content = content.replace("{{REDIS_URL}}", self.get_redis_url(branch_name))
            
            target_path.write_text(content)
            log_success(f"Environment file created from template: {target_path}")
            return True
            
        except Exception as e:
            log_warning(f"Failed to create environment file from template: {e}")
            return False
    
    def cleanup_environment_files(self, worktree_path: Path) -> bool:
        """Clean up environment files for a worktree."""
        env_files = [
            get_env_file_path(worktree_path),
            get_env_compose_file_path(worktree_path)
        ]
        
        success = True
        for env_file in env_files:
            if env_file.exists():
                try:
                    env_file.unlink()
                    log_info(f"Removed environment file: {env_file}")
                except Exception as e:
                    log_warning(f"Failed to remove environment file {env_file}: {e}")
                    success = False
        
        return success
    
    def get_worktree_config(self, branch_name: str) -> Dict[str, any]:
        """Get complete worktree configuration."""
        return {
            "branch_name": branch_name,
            "domain_name": self.get_domain_name(branch_name),
            "allowed_hosts": self.get_allowed_hosts(branch_name),
            "database_url": self.get_database_url(branch_name),
            "redis_url": self.get_redis_url(branch_name),
            "volume_names": self.get_worktree_volume_names(branch_name),
            "environment_variables": self.get_environment_variables(branch_name),
            "compose_environment": self.generate_compose_environment(branch_name)
        }
    
    def _generate_env_compose_with_domain(self, branch_name: str, domain: str) -> str:
        """Generate env.dockertree content with domain override.
        
        Args:
            branch_name: Branch name
            domain: Domain override (subdomain.domain.tld)
            
        Returns:
            Environment file content with domain overrides
        """
        from ..config.settings import get_project_name, sanitize_project_name
        project_root = self.project_root
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        
        # Construct URLs from domain
        site_domain = f"https://{domain}"
        allowed_hosts = f"localhost,127.0.0.1,{domain}"
        
        # Extract base domain (everything after first dot)
        if '.' in domain:
            base_domain = domain.split('.', 1)[1]
            allowed_hosts += f",*.{base_domain}"
        allowed_hosts += ",web"
        
        return f"""# Dockertree environment configuration for {branch_name}
# Domain override: {domain}
COMPOSE_PROJECT_NAME={compose_project_name}
PROJECT_ROOT={project_root}
SITE_DOMAIN={site_domain}
ALLOWED_HOSTS={allowed_hosts}
DEBUG=False
"""
    
    def apply_domain_overrides(self, worktree_path: Path, domain: str) -> bool:
        """Apply domain overrides to existing environment files.
        
        This method modifies .env files to replace localhost references
        with production/staging domain values.
        
        Args:
            worktree_path: Path to worktree directory
            domain: Domain override (subdomain.domain.tld)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from ..config.settings import sanitize_project_name, get_project_name
            import re
            
            # Construct URLs from domain
            http_url = f"http://{domain}"
            https_url = f"https://{domain}"
            
            # Update .env file if it exists
            env_file = worktree_path / ".env"
            if env_file.exists():
                content = env_file.read_text()
                
                # Replace SITE_DOMAIN
                content = re.sub(
                    r'SITE_DOMAIN=.*',
                    f'SITE_DOMAIN={https_url}',
                    content,
                    flags=re.MULTILINE
                )
                
                # Update ALLOWED_HOSTS to include domain
                # Extract base domain
                base_domain = domain.split('.', 1)[1] if '.' in domain else domain
                
                # Build new ALLOWED_HOSTS
                if 'ALLOWED_HOSTS=' in content:
                    # Replace existing ALLOWED_HOSTS
                    content = re.sub(
                        r'ALLOWED_HOSTS=.*',
                        f'ALLOWED_HOSTS=localhost,127.0.0.1,{domain},*.{base_domain},web',
                        content,
                        flags=re.MULTILINE
                    )
                else:
                    # Add ALLOWED_HOSTS if missing
                    content += f"\nALLOWED_HOSTS=localhost,127.0.0.1,{domain},*.{base_domain},web\n"
                
                # Set DEBUG=False for production
                content = re.sub(
                    r'DEBUG=.*',
                    'DEBUG=False',
                    content,
                    flags=re.MULTILINE | re.IGNORECASE
                )
                
                # Replace any localhost references in URLs
                project_name = sanitize_project_name(get_project_name())
                localhost_domain = f"{project_name}-.*\\.localhost"
                content = re.sub(
                    localhost_domain,
                    domain,
                    content
                )
                
                env_file.write_text(content)
                log_info(f"Applied domain overrides to .env file: {domain}")
            
            # Update env.dockertree file
            env_dockertree = get_env_compose_file_path(worktree_path)
            if env_dockertree.exists():
                content = env_dockertree.read_text()
                
                # Replace SITE_DOMAIN
                content = re.sub(
                    r'SITE_DOMAIN=.*',
                    f'SITE_DOMAIN={https_url}',
                    content,
                    flags=re.MULTILINE
                )
                
                # Update ALLOWED_HOSTS
                base_domain = domain.split('.', 1)[1] if '.' in domain else domain
                content = re.sub(
                    r'ALLOWED_HOSTS=.*',
                    f'ALLOWED_HOSTS=localhost,127.0.0.1,{domain},*.{base_domain},web',
                    content,
                    flags=re.MULTILINE
                )
                
                # Set DEBUG=False
                content = re.sub(
                    r'DEBUG=.*',
                    'DEBUG=False',
                    content,
                    flags=re.MULTILINE | re.IGNORECASE
                )
                
                env_dockertree.write_text(content)
                log_info(f"Applied domain overrides to env.dockertree: {domain}")
            
            return True
            
        except Exception as e:
            log_warning(f"Failed to apply domain overrides: {e}")
            return False

    def apply_ip_overrides(self, worktree_path: Path, ip: str) -> bool:
        """Apply IP overrides to existing environment files (HTTP-only).

        Sets SITE_DOMAIN to http://{ip}, updates ALLOWED_HOSTS to include
        the IP, and forces DEBUG=False.
        """
        try:
            import re

            http_url = f"http://{ip}"

            # Update .env file
            env_file = worktree_path / ".env"
            if env_file.exists():
                content = env_file.read_text()

                content = re.sub(r'SITE_DOMAIN=.*', f'SITE_DOMAIN={http_url}', content, flags=re.MULTILINE)

                if 'ALLOWED_HOSTS=' in content:
                    content = re.sub(r'ALLOWED_HOSTS=.*', f'ALLOWED_HOSTS=localhost,127.0.0.1,{ip},web', content, flags=re.MULTILINE)
                else:
                    content += f"\nALLOWED_HOSTS=localhost,127.0.0.1,{ip},web\n"

                content = re.sub(r'DEBUG=.*', 'DEBUG=False', content, flags=re.MULTILINE | re.IGNORECASE)

                env_file.write_text(content)
                log_info(f"Applied IP overrides to .env file: {ip}")

            # Update env.dockertree
            env_dockertree = get_env_compose_file_path(worktree_path)
            if env_dockertree.exists():
                content = env_dockertree.read_text()
                content = re.sub(r'SITE_DOMAIN=.*', f'SITE_DOMAIN={http_url}', content, flags=re.MULTILINE)
                content = re.sub(r'ALLOWED_HOSTS=.*', f'ALLOWED_HOSTS=localhost,127.0.0.1,{ip},web', content, flags=re.MULTILINE)
                content = re.sub(r'DEBUG=.*', 'DEBUG=False', content, flags=re.MULTILINE | re.IGNORECASE)
                env_dockertree.write_text(content)
                log_info(f"Applied IP overrides to env.dockertree: {ip}")

            return True
        except Exception as e:
            log_warning(f"Failed to apply IP overrides: {e}")
            return False
