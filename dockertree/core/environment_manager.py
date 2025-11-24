"""
Environment management for dockertree CLI.

This module provides environment file generation, volume naming, and
configuration management for worktree environments.
"""

import os
from pathlib import Path
from typing import Dict, Optional

from ..config.settings import (
    generate_env_compose_content, 
    get_volume_names,
    DEFAULT_ENV_VARS,
    get_project_root,
    get_worktree_paths
)
from ..utils.logging import log_info, log_success, log_warning
from ..utils.path_utils import (
    get_env_file_path, 
    get_env_compose_file_path,
    copy_env_file
)
from ..core.dns_manager import is_domain


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
            env_compose_content = self._generate_env_compose_content(branch_name)
            
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
        from ..config.settings import DOCKERTREE_DIR, sanitize_project_name, get_allowed_hosts_for_worktree, DEFAULT_ENV_VARS
        import yaml
        
        env_file = worktree_path / ".env"
        
        # Don't overwrite existing .env file
        if env_file.exists():
            return True
        
        # Get project name from config in self.project_root (not current directory)
        project_name = None
        config_path = self.project_root / DOCKERTREE_DIR / "config.yml"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f) or {}
                    project_name = config.get("project_name")
            except Exception:
                pass
        
        # Fallback to project root directory name if config doesn't have project_name
        if not project_name:
            project_name = self.project_root.name
        
        # Create default environment content with project prefix
        project_name = sanitize_project_name(project_name)
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
# IMPORTANT: Set these values to match your PostgreSQL container configuration
# These values must match POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB
# in your docker-compose.yml file
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=

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
    
    def _generate_env_compose_content(self, branch_name: str) -> str:
        """Generate env.dockertree content for a worktree using self.project_root."""
        from ..config.settings import DOCKERTREE_DIR, sanitize_project_name, get_allowed_hosts_for_worktree
        import yaml
        
        # Get project name from config in self.project_root
        project_name = None
        config_path = self.project_root / DOCKERTREE_DIR / "config.yml"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f) or {}
                    project_name = config.get("project_name")
            except Exception:
                pass
        
        # Fallback to project root directory name if config doesn't have project_name
        if not project_name:
            project_name = self.project_root.name
        
        project_name = sanitize_project_name(project_name)
        compose_project_name = f"{project_name}-{branch_name}"
        site_domain = f"{compose_project_name}.localhost"  # RFC-compliant hostname
        allowed_hosts = get_allowed_hosts_for_worktree(branch_name)
        
        return f"""# Dockertree environment configuration for {branch_name}
COMPOSE_PROJECT_NAME={compose_project_name}
PROJECT_ROOT={self.project_root}
SITE_DOMAIN={site_domain}
ALLOWED_HOSTS={allowed_hosts}
DEBUG=True
USE_X_FORWARDED_HOST=True
CSRF_TRUSTED_ORIGINS=http://{site_domain}
"""
    
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
    
    def _should_use_secure_cookies(self, site_domain: str) -> bool:
        """Determine if secure cookies should be used based on SITE_DOMAIN.
        
        Args:
            site_domain: SITE_DOMAIN value (may include http:// or https:// prefix)
            
        Returns:
            True if secure cookies should be used (HTTPS/production),
            False for HTTP/localhost/IP deployments
        """
        # Strip protocol prefix if present
        domain = site_domain
        if domain.startswith('https://'):
            return True
        elif domain.startswith('http://'):
            return False
        
        # Check if it's a localhost domain
        if domain.endswith('.localhost') or domain == 'localhost' or domain.startswith('127.0.0.1'):
            return False
        
        # Check if it's an IP address
        import re
        if re.match(r'^\d+\.\d+\.\d+\.\d+', domain):
            return False
        
        # For production domains (not localhost, not IP), use secure cookies
        # This handles cases where SITE_DOMAIN is just the domain without protocol
        return is_domain(domain)
    
    def get_domain_name(self, branch_name: str) -> str:
        """Get the domain name for a worktree.
        
        Reads SITE_DOMAIN from env.dockertree if available, otherwise
        constructs the default localhost domain pattern.
        
        Args:
            branch_name: Branch name for the worktree
            
        Returns:
            Domain name (without http:// or https:// prefix)
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
                # Strip http:// or https:// prefix if present
                domain = site_domain_value
                if domain.startswith('https://'):
                    domain = domain[8:]
                elif domain.startswith('http://'):
                    domain = domain[7:]
                # Remove trailing slash if present
                domain = domain.rstrip('/')
                # Strip surrounding quotes if present (single or double)
                domain = domain.strip("'\"")
                return domain
        except Exception:
            pass
        # Fallback: build from computed domain
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
    
    def get_database_url(self, branch_name: str) -> str:
        """Get the database URL for a worktree.
        
        Reads POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB from environment variables.
        These should be set in .dockertree/env.dockertree or .env files.
        
        Args:
            branch_name: Branch name for the worktree
            
        Returns:
            Database URL in format: postgres://user:password@host:port/database
        """
        from ..config.settings import get_project_name, sanitize_project_name
        from ..utils.env_loader import get_env_compose_file_path, load_env_file
        
        # Get environment variables from worktree's env.dockertree file
        worktree_path, _ = get_worktree_paths(branch_name)
        env_file = get_env_compose_file_path(worktree_path)
        env_vars = load_env_file(env_file) if env_file.exists() else {}
        
        # Fallback to project root env.dockertree if worktree doesn't have one
        if not env_vars.get('POSTGRES_USER'):
            project_root = get_project_root()
            root_env_file = project_root / ".dockertree" / "env.dockertree"
            if root_env_file.exists():
                root_env = load_env_file(root_env_file)
                env_vars.update(root_env)
        
        # Get PostgreSQL credentials from environment variables
        postgres_user = env_vars.get('POSTGRES_USER') or os.getenv('POSTGRES_USER')
        postgres_password = env_vars.get('POSTGRES_PASSWORD') or os.getenv('POSTGRES_PASSWORD')
        postgres_db = env_vars.get('POSTGRES_DB') or os.getenv('POSTGRES_DB')
        
        if not postgres_user or not postgres_password or not postgres_db:
            raise ValueError(
                "PostgreSQL credentials not found in environment variables. "
                "Please set POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB in "
                ".dockertree/env.dockertree or .env file."
            )
        
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
        from ..config.settings import DOCKERTREE_DIR, sanitize_project_name
        from ..utils.logging import log_warning
        import yaml
        
        project_root = self.project_root
        
        # Get project name from config in self.project_root (not current directory)
        project_name = None
        config_path = self.project_root / DOCKERTREE_DIR / "config.yml"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f) or {}
                    project_name = config.get("project_name")
            except Exception:
                pass
        
        # Fallback to project root directory name if config doesn't have project_name
        if not project_name:
            project_name = self.project_root.name
        
        project_name = sanitize_project_name(project_name)
        compose_project_name = f"{project_name}-{branch_name}"
        
        # Construct URLs from domain
        site_domain = f"https://{domain}"
        allowed_hosts = f"localhost,127.0.0.1,{domain}"
        
        # Extract base domain (everything after first dot)
        if '.' in domain:
            base_domain = domain.split('.', 1)[1]
            allowed_hosts += f",*.{base_domain}"
        allowed_hosts += ",web"
        
        # Determine CADDY_EMAIL: check if already set in env.dockertree, otherwise use default
        default_caddy_email = f"admin@{domain}"
        caddy_email = default_caddy_email
        
        # Check if env.dockertree exists and has CADDY_EMAIL
        worktree_path = Path(project_root) / "worktrees" / branch_name
        env_compose_path = get_env_compose_file_path(worktree_path)
        if env_compose_path.exists():
            from ..utils.env_loader import load_env_file
            existing_env = load_env_file(env_compose_path)
            if 'CADDY_EMAIL' in existing_env:
                caddy_email = existing_env['CADDY_EMAIL']
            else:
                log_warning(f"CADDY_EMAIL not set in env.dockertree. Using default: {default_caddy_email}")
                log_warning("This email is used for Let's Encrypt certificate notifications.")
                log_warning("To customize, add CADDY_EMAIL=your-email@example.com to .dockertree/env.dockertree")
        else:
            log_warning(f"CADDY_EMAIL not set. Using default: {default_caddy_email}")
            log_warning("This email is used for Let's Encrypt certificate notifications.")
            log_warning("To customize, add CADDY_EMAIL=your-email@example.com to .dockertree/env.dockertree")
        
        # Determine secure cookie setting
        use_secure_cookies = self._should_use_secure_cookies(site_domain)
        
        return f"""# Dockertree environment configuration for {branch_name}
# Domain override: {domain}
COMPOSE_PROJECT_NAME={compose_project_name}
PROJECT_ROOT={project_root}
SITE_DOMAIN={site_domain}
ALLOWED_HOSTS={allowed_hosts}
DEBUG=False
USE_X_FORWARDED_HOST=True
CSRF_TRUSTED_ORIGINS=https://{domain} http://{domain} https://*.{base_domain}
USE_SECURE_COOKIES={str(use_secure_cookies)}
CADDY_EMAIL={caddy_email}
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

                # Ensure proxy/CSRF headers for domain deployments
                # USE_X_FORWARDED_HOST
                if 'USE_X_FORWARDED_HOST=' in content:
                    content = re.sub(r'USE_X_FORWARDED_HOST=.*', 'USE_X_FORWARDED_HOST=True', content, flags=re.MULTILINE)
                else:
                    content += "\nUSE_X_FORWARDED_HOST=True\n"

                # SECURE_PROXY_SSL_HEADER hint (value consumed by Django settings if supported)
                if 'SECURE_PROXY_SSL_HEADER=' in content:
                    content = re.sub(r'SECURE_PROXY_SSL_HEADER=.*', 'SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https', content, flags=re.MULTILINE)
                else:
                    content += "\nSECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https\n"

                # CSRF_TRUSTED_ORIGINS
                csrf_value = f"https://{domain} http://{domain}"
                if base_domain:
                    csrf_value += f" https://*.{base_domain}"
                if 'CSRF_TRUSTED_ORIGINS=' in content:
                    content = re.sub(r'CSRF_TRUSTED_ORIGINS=.*', f'CSRF_TRUSTED_ORIGINS={csrf_value}', content, flags=re.MULTILINE)
                else:
                    content += f"\nCSRF_TRUSTED_ORIGINS={csrf_value}\n"
                
                # USE_SECURE_COOKIES (HTTPS domain deployments require secure cookies)
                use_secure_cookies = self._should_use_secure_cookies(https_url)
                if 'USE_SECURE_COOKIES=' in content:
                    content = re.sub(r'USE_SECURE_COOKIES=.*', f'USE_SECURE_COOKIES={str(use_secure_cookies)}', content, flags=re.MULTILINE)
                else:
                    content += f"\nUSE_SECURE_COOKIES={str(use_secure_cookies)}\n"
                
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
                from ..utils.env_loader import load_env_file
                existing_env = load_env_file(env_dockertree)
                content = env_dockertree.read_text()
                
                # Check if CADDY_EMAIL is already set
                if 'CADDY_EMAIL' not in existing_env:
                    # Set default CADDY_EMAIL based on domain
                    default_caddy_email = f"admin@{domain}"
                    log_warning(f"CADDY_EMAIL not set in env.dockertree. Using default: {default_caddy_email}")
                    log_warning("This email is used for Let's Encrypt certificate notifications.")
                    log_warning("To customize, add CADDY_EMAIL=your-email@example.com to .dockertree/env.dockertree")
                    
                    # Add CADDY_EMAIL to content if not present
                    if 'CADDY_EMAIL=' not in content:
                        content += f"\nCADDY_EMAIL={default_caddy_email}\n"
                
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

                # Ensure proxy/CSRF headers in env.dockertree
                if 'USE_X_FORWARDED_HOST=' in content:
                    content = re.sub(r'USE_X_FORWARDED_HOST=.*', 'USE_X_FORWARDED_HOST=True', content, flags=re.MULTILINE)
                else:
                    content += "\nUSE_X_FORWARDED_HOST=True\n"

                if 'SECURE_PROXY_SSL_HEADER=' in content:
                    content = re.sub(r'SECURE_PROXY_SSL_HEADER=.*', 'SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https', content, flags=re.MULTILINE)
                else:
                    content += "\nSECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https\n"

                csrf_value = f"https://{domain} http://{domain}"
                if base_domain:
                    csrf_value += f" https://*.{base_domain}"
                if 'CSRF_TRUSTED_ORIGINS=' in content:
                    content = re.sub(r'CSRF_TRUSTED_ORIGINS=.*', f'CSRF_TRUSTED_ORIGINS={csrf_value}', content, flags=re.MULTILINE)
                else:
                    content += f"\nCSRF_TRUSTED_ORIGINS={csrf_value}\n"
                
                # USE_SECURE_COOKIES (HTTPS domain deployments require secure cookies)
                use_secure_cookies = self._should_use_secure_cookies(https_url)
                if 'USE_SECURE_COOKIES=' in content:
                    content = re.sub(r'USE_SECURE_COOKIES=.*', f'USE_SECURE_COOKIES={str(use_secure_cookies)}', content, flags=re.MULTILINE)
                else:
                    content += f"\nUSE_SECURE_COOKIES={str(use_secure_cookies)}\n"
                
                env_dockertree.write_text(content)
                log_info(f"Applied domain overrides to env.dockertree: {domain}")
            
            # Update docker-compose.worktree.yml to replace localhost patterns with domain
            from ..utils.path_utils import get_compose_override_path
            compose_file = get_compose_override_path(worktree_path)
            if compose_file and compose_file.exists():
                try:
                    import yaml
                    compose_content = compose_file.read_text()
                    compose_data = yaml.safe_load(compose_content)
                    
                    if compose_data and 'services' in compose_data:
                        updated = False
                        for service_name, service_config in compose_data['services'].items():
                            if 'labels' in service_config:
                                labels = service_config['labels']
                                # Handle both list and dict formats
                                if isinstance(labels, list):
                                    for i, label in enumerate(labels):
                                        if isinstance(label, str) and 'caddy.proxy=' in label:
                                            # Replace localhost pattern with domain
                                            if '${COMPOSE_PROJECT_NAME}.localhost' in label or '.localhost' in label:
                                                labels[i] = f"caddy.proxy={domain}"
                                                updated = True
                                                log_info(f"Updated Caddy label for {service_name}: {domain}")
                                elif isinstance(labels, dict):
                                    if 'caddy.proxy' in labels:
                                        old_value = labels['caddy.proxy']
                                        if '${COMPOSE_PROJECT_NAME}.localhost' in str(old_value) or '.localhost' in str(old_value):
                                            labels['caddy.proxy'] = domain
                                            updated = True
                                            log_info(f"Updated Caddy label for {service_name}: {domain}")
                        
                        if updated:
                            # Remove version field if it's null (Docker Compose v2 doesn't require it)
                            from ..utils.file_utils import clean_compose_version_field
                            clean_compose_version_field(compose_data)
                            
                            # Write YAML with proper formatting
                            yaml_content = yaml.dump(compose_data, default_flow_style=False, sort_keys=False, allow_unicode=True)
                            compose_file.write_text(yaml_content)
                            log_info(f"Updated docker-compose.worktree.yml with domain: {domain}")
                            log_info(f"Caddy will route {domain} to containers when they start")
                except Exception as e:
                    log_warning(f"Failed to update docker-compose.worktree.yml: {e}")
            
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

                # Proxy/CSRF headers for IP deployments (HTTP-only)
                if 'USE_X_FORWARDED_HOST=' in content:
                    content = re.sub(r'USE_X_FORWARDED_HOST=.*', 'USE_X_FORWARDED_HOST=True', content, flags=re.MULTILINE)
                else:
                    content += "\nUSE_X_FORWARDED_HOST=True\n"

                # No SECURE_PROXY_SSL_HEADER for IP/http
                csrf_value = f"http://{ip}"
                if 'CSRF_TRUSTED_ORIGINS=' in content:
                    content = re.sub(r'CSRF_TRUSTED_ORIGINS=.*', f'CSRF_TRUSTED_ORIGINS={csrf_value}', content, flags=re.MULTILINE)
                else:
                    content += f"\nCSRF_TRUSTED_ORIGINS={csrf_value}\n"
                
                # USE_SECURE_COOKIES (IP deployments are HTTP-only, no secure cookies)
                use_secure_cookies = self._should_use_secure_cookies(http_url)
                if 'USE_SECURE_COOKIES=' in content:
                    content = re.sub(r'USE_SECURE_COOKIES=.*', f'USE_SECURE_COOKIES={str(use_secure_cookies)}', content, flags=re.MULTILINE)
                else:
                    content += f"\nUSE_SECURE_COOKIES={str(use_secure_cookies)}\n"

                env_file.write_text(content)
                log_info(f"Applied IP overrides to .env file: {ip}")

            # Update env.dockertree
            env_dockertree = get_env_compose_file_path(worktree_path)
            if env_dockertree.exists():
                content = env_dockertree.read_text()
                content = re.sub(r'SITE_DOMAIN=.*', f'SITE_DOMAIN={http_url}', content, flags=re.MULTILINE)
                content = re.sub(r'ALLOWED_HOSTS=.*', f'ALLOWED_HOSTS=localhost,127.0.0.1,{ip},web', content, flags=re.MULTILINE)
                content = re.sub(r'DEBUG=.*', 'DEBUG=False', content, flags=re.MULTILINE | re.IGNORECASE)
                
                # USE_SECURE_COOKIES (IP deployments are HTTP-only, no secure cookies)
                use_secure_cookies = self._should_use_secure_cookies(http_url)
                if 'USE_SECURE_COOKIES=' in content:
                    content = re.sub(r'USE_SECURE_COOKIES=.*', f'USE_SECURE_COOKIES={str(use_secure_cookies)}', content, flags=re.MULTILINE)
                else:
                    content += f"\nUSE_SECURE_COOKIES={str(use_secure_cookies)}\n"
                if 'USE_X_FORWARDED_HOST=' in content:
                    content = re.sub(r'USE_X_FORWARDED_HOST=.*', 'USE_X_FORWARDED_HOST=True', content, flags=re.MULTILINE)
                else:
                    content += "\nUSE_X_FORWARDED_HOST=True\n"
                csrf_value = f"http://{ip}"
                if 'CSRF_TRUSTED_ORIGINS=' in content:
                    content = re.sub(r'CSRF_TRUSTED_ORIGINS=.*', f'CSRF_TRUSTED_ORIGINS={csrf_value}', content, flags=re.MULTILINE)
                else:
                    content += f"\nCSRF_TRUSTED_ORIGINS={csrf_value}\n"
                
                # USE_SECURE_COOKIES (IP deployments are HTTP-only, no secure cookies)
                use_secure_cookies = self._should_use_secure_cookies(http_url)
                if 'USE_SECURE_COOKIES=' in content:
                    content = re.sub(r'USE_SECURE_COOKIES=.*', f'USE_SECURE_COOKIES={str(use_secure_cookies)}', content, flags=re.MULTILINE)
                else:
                    content += f"\nUSE_SECURE_COOKIES={str(use_secure_cookies)}\n"
                
                env_dockertree.write_text(content)
                log_info(f"Applied IP overrides to env.dockertree: {ip}")
            
            # Update docker-compose.worktree.yml to replace localhost patterns with IP
            from ..utils.path_utils import get_compose_override_path
            compose_file = get_compose_override_path(worktree_path)
            if compose_file and compose_file.exists():
                try:
                    import yaml
                    compose_content = compose_file.read_text()
                    compose_data = yaml.safe_load(compose_content)
                    
                    if compose_data and 'services' in compose_data:
                        updated = False
                        for service_name, service_config in compose_data['services'].items():
                            if 'labels' in service_config:
                                labels = service_config['labels']
                                # Handle both list and dict formats
                                if isinstance(labels, list):
                                    for i, label in enumerate(labels):
                                        if isinstance(label, str) and 'caddy.proxy=' in label:
                                            # Replace localhost pattern with IP
                                            if '${COMPOSE_PROJECT_NAME}.localhost' in label or '.localhost' in label:
                                                labels[i] = f"caddy.proxy={ip}"
                                                updated = True
                                                log_info(f"Updated Caddy label for {service_name}: {ip}")
                                elif isinstance(labels, dict):
                                    if 'caddy.proxy' in labels:
                                        old_value = labels['caddy.proxy']
                                        if '${COMPOSE_PROJECT_NAME}.localhost' in str(old_value) or '.localhost' in str(old_value):
                                            labels['caddy.proxy'] = ip
                                            updated = True
                                            log_info(f"Updated Caddy label for {service_name}: {ip}")
                        
                        if updated:
                            # Remove version field if it's null (Docker Compose v2 doesn't require it)
                            from ..utils.file_utils import clean_compose_version_field
                            clean_compose_version_field(compose_data)
                            
                            compose_file.write_text(yaml.dump(compose_data, default_flow_style=False, sort_keys=False))
                            log_info(f"Updated docker-compose.worktree.yml with IP: {ip}")
                except Exception as e:
                    log_warning(f"Failed to update docker-compose.worktree.yml: {e}")
            
            return True
        except Exception as e:
            log_warning(f"Failed to apply IP overrides: {e}")
            return False
    
    def get_push_config(self, branch_name: str) -> Dict[str, Optional[str]]:
        """Get push configuration from worktree's env.dockertree file.
        
        Reads PUSH_SCP_TARGET, PUSH_BRANCH_NAME, PUSH_DOMAIN, PUSH_IP from
        the worktree's env.dockertree file.
        
        Args:
            branch_name: Branch name for the worktree
            
        Returns:
            Dictionary with push configuration keys (scp_target, branch_name, domain, ip)
            Values are None if not found
        """
        from ..config.settings import get_worktree_paths
        from ..utils.env_loader import load_env_file
        
        try:
            worktree_path, legacy_path = get_worktree_paths(branch_name)
            env_path = get_env_compose_file_path(worktree_path)
            if not env_path.exists() and legacy_path.exists():
                env_path = get_env_compose_file_path(legacy_path)
            
            if not env_path.exists():
                return {
                    'scp_target': None,
                    'branch_name': None,
                    'domain': None,
                    'ip': None
                }
            
            env_vars = load_env_file(env_path)
            
            return {
                'scp_target': env_vars.get('PUSH_SCP_TARGET'),
                'branch_name': env_vars.get('PUSH_BRANCH_NAME'),
                'domain': env_vars.get('PUSH_DOMAIN'),
                'ip': env_vars.get('PUSH_IP')
            }
        except Exception:
            return {
                'scp_target': None,
                'branch_name': None,
                'domain': None,
                'ip': None
            }
    
    def save_push_config(self, branch_name: str, scp_target: str, domain: Optional[str] = None, 
                        ip: Optional[str] = None) -> bool:
        """Save push configuration to worktree's env.dockertree file.
        
        Appends or updates PUSH_SCP_TARGET, PUSH_BRANCH_NAME, PUSH_DOMAIN, PUSH_IP
        in the worktree's env.dockertree file.
        
        Args:
            branch_name: Branch name for the worktree
            scp_target: SCP target in format username@server:path
            domain: Optional domain override
            ip: Optional IP override (mutually exclusive with domain)
            
        Returns:
            True if successful, False otherwise
        """
        from ..config.settings import get_worktree_paths
        import re
        
        try:
            worktree_path, legacy_path = get_worktree_paths(branch_name)
            env_path = get_env_compose_file_path(worktree_path)
            if not env_path.exists() and legacy_path.exists():
                env_path = get_env_compose_file_path(legacy_path)
            
            # Ensure .dockertree directory exists
            env_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Read existing content or create new
            if env_path.exists():
                content = env_path.read_text()
            else:
                content = f"# Dockertree environment configuration for {branch_name}\n"
            
            # Update or add push configuration variables
            # Remove existing push config lines
            content = re.sub(r'^PUSH_SCP_TARGET=.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'^PUSH_BRANCH_NAME=.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'^PUSH_DOMAIN=.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'^PUSH_IP=.*$', '', content, flags=re.MULTILINE)
            
            # Remove multiple blank lines
            content = re.sub(r'\n\n\n+', '\n\n', content)
            
            # Add push configuration at the end
            content += "\n# Push configuration (auto-saved after successful push)\n"
            content += f"PUSH_SCP_TARGET={scp_target}\n"
            content += f"PUSH_BRANCH_NAME={branch_name}\n"
            if domain:
                content += f"PUSH_DOMAIN={domain}\n"
            if ip:
                content += f"PUSH_IP={ip}\n"
            
            env_path.write_text(content)
            log_info(f"Saved push configuration to {env_path}")
            return True
        except Exception as e:
            log_warning(f"Failed to save push configuration: {e}")
            return False