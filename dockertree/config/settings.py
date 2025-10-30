"""
Configuration settings for dockertree CLI.

This module contains all configuration constants and settings used throughout
the dockertree CLI application.
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

# Version information
VERSION = "0.9.2"
AUTHOR = "Dockertree Contributors"

# Default project configuration (used if .dockertree/config.yml doesn't exist)
# PROJECT_NAME is now dynamically determined from get_project_name()
CADDY_NETWORK = "dockertree_caddy_proxy"
COMPOSE_OVERRIDE_DIR = "dockertree"
DOCKERTREE_DIR = ".dockertree"

# File paths
COMPOSE_OVERRIDE = f"{COMPOSE_OVERRIDE_DIR}/config/docker-compose.dockertree.yml"
COMPOSE_WORKTREE = f"{COMPOSE_OVERRIDE_DIR}/config/docker-compose.worktree.yml"

# Volume names
POSTGRES_VOLUME_SUFFIX = "postgres_data"
REDIS_VOLUME_SUFFIX = "redis_data"
MEDIA_VOLUME_SUFFIX = "media_files"
CADDY_DATA_VOLUME_SUFFIX = "caddy_data"
CADDY_CONFIG_VOLUME_SUFFIX = "caddy_config"

# Protected branches that cannot be deleted
PROTECTED_BRANCHES = {"main", "master", "develop", "production", "staging"}

# Branch name validation pattern
BRANCH_NAME_PATTERN = r"^[a-zA-Z0-9_.-]+$"

# Default environment variables (legacy defaults, overridden by config)
DEFAULT_ENV_VARS = {
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "password",
    "POSTGRES_DB": "database",
    "ALLOWED_HOSTS": "localhost,127.0.0.1,*.localhost,web",
    "DEBUG": "True",
    "DJANGO_SECRET_KEY": "django-insecure-secret-key",
    "SITE_DOMAIN": "localhost:8000",
    "CADDY_EMAIL": "admin@example.com",
}

# Deployment defaults helpers (Phase 2)
def _get_config_value(path_keys: list[str], default: Optional[str] = None) -> Optional[str]:
    """Safely read a nested value from .dockertree/config.yml.

    Args:
        path_keys: List of nested keys to traverse
        default: Default value when not found

    Returns:
        String value or default
    """
    try:
        config_path = get_project_root() / DOCKERTREE_DIR / "config.yml"
        if not config_path.exists():
            return default
        import yaml  # local import to avoid top-level dependency at import time
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        node: Any = cfg
        for key in path_keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        if isinstance(node, (str, int, float)):
            return str(node)
        return default
    except Exception:
        return default


def get_deployment_defaults() -> Dict[str, Optional[str]]:
    """Get deployment default values from config if present.

    Keys:
      - default_server
      - default_domain
      - default_ip
      - ssh_key
    """
    return {
        "default_server": _get_config_value(["deployment", "default_server"], None),
        "default_domain": _get_config_value(["deployment", "default_domain"], None),
        "default_ip": _get_config_value(["deployment", "default_ip"], None),
        "ssh_key": _get_config_value(["deployment", "ssh_key"], None),
    }


def get_default_server() -> Optional[str]:
    return get_deployment_defaults().get("default_server")


def get_default_domain() -> Optional[str]:
    return get_deployment_defaults().get("default_domain")


def get_default_ip() -> Optional[str]:
    return get_deployment_defaults().get("default_ip")


def get_deployment_ssh_key() -> Optional[str]:
    return get_deployment_defaults().get("ssh_key")

# Configuration loading functions
def get_project_config() -> Dict[str, Any]:
    """Load project configuration from .dockertree/config.yml"""
    config_path = get_project_root() / DOCKERTREE_DIR / "config.yml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return get_default_config()

def get_default_config() -> Dict[str, Any]:
    """Default configuration for projects without setup"""
    return {
        "project_name": Path.cwd().name,
        "caddy_network": "dockertree_caddy_proxy",
        "worktree_dir": "worktrees",
        "services": {
            "web": {"container_name_template": "${COMPOSE_PROJECT_NAME}-web"},
            "db": {"container_name_template": "${COMPOSE_PROJECT_NAME}-db"},
            "redis": {"container_name_template": "${COMPOSE_PROJECT_NAME}-redis"},
        },
        "volumes": ["postgres_data", "redis_data", "media_files"],
        "environment": {
            "DEBUG": "True",
            "ALLOWED_HOSTS": "localhost,127.0.0.1,*.localhost,web",
        }
    }

def get_project_name() -> str:
    """Get project name from config or fallback to directory name"""
    config = get_project_config()
    return config.get("project_name", Path.cwd().name)

def sanitize_project_name(name: str) -> str:
    """Sanitize project name for use in Docker resource names.
    
    Converts underscores to hyphens for consistency with hostname requirements.
    While Docker allows underscores, using hyphens everywhere ensures
    consistency between resource names and hostnames.
    """
    import re
    # Replace underscores with hyphens for consistency
    sanitized = name.replace('_', '-')
    # Replace other non-alphanumeric (except dash) with dash
    sanitized = re.sub(r'[^a-zA-Z0-9-]', '-', sanitized)
    # Remove leading/trailing dashes
    sanitized = sanitized.strip('-')
    # Convert to lowercase for consistency
    return sanitized.lower()

def sanitize_hostname(name: str) -> str:
    """Sanitize name for use in hostnames (RFC 1034/1035 compliant).
    
    Converts underscores to hyphens and removes invalid characters.
    This ensures hostnames are valid for web browsers and Django's ALLOWED_HOSTS.
    """
    import re
    # Replace underscores with hyphens for hostname compatibility
    sanitized = name.replace('_', '-')
    # Replace other non-alphanumeric (except dash) with dash
    sanitized = re.sub(r'[^a-zA-Z0-9-]', '-', sanitized)
    # Remove leading/trailing dashes
    sanitized = sanitized.strip('-')
    # Convert to lowercase for consistency
    return sanitized.lower()

def get_worktree_dir() -> str:
    """Get worktree directory from config"""
    config = get_project_config()
    return config.get("worktree_dir", "worktrees")

# Docker Compose command detection
def get_compose_command() -> str:
    """Get the appropriate docker compose command."""
    import subprocess
    try:
        subprocess.run(["docker", "compose", "version"], 
                      capture_output=True, check=True)
        return "docker compose"
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            subprocess.run(["docker-compose", "version"], 
                          capture_output=True, check=True)
            return "docker-compose"
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to docker-compose if both fail
            return "docker-compose"

# Path resolution
def get_project_root() -> Path:
    """Get the project root directory, supporting fractal worktree execution."""
    current = Path.cwd()
    
    # First: Check if we're IN a worktree with its own .dockertree/config.yml (fractal mode)
    if (current / ".dockertree" / "config.yml").exists():
        return current
    
    # Second: Search upward to find parent project root
    for parent in current.parents:
        if (parent / ".dockertree" / "config.yml").exists():
            return parent
    
    # Fallback: check for .dockertree directory without config.yml (legacy)
    if (current / ".dockertree").exists() and (current / ".dockertree").is_dir():
        return current
        
    for parent in current.parents:
        if (parent / ".dockertree").exists() and (parent / ".dockertree").is_dir():
            return parent
    
    # Final fallback
    return current

def get_script_dir() -> Path:
    """Get the dockertree-cli script directory."""
    return Path(__file__).parent.parent.absolute()

def get_package_caddyfile_path() -> Path:
    """Get the path to the package Caddyfile template."""
    return get_script_dir() / "config" / "Caddyfile.dockertree"

def get_package_caddy_compose_path() -> Path:
    """Get the path to the package Caddy compose template."""
    return get_script_dir() / "config" / "docker-compose.global-caddy.yml"

def get_worktree_paths(branch_name: str) -> tuple[Path, Path]:
    """Get worktree paths for a branch (new and legacy)."""
    repo_root = get_project_root()
    worktree_dir = get_worktree_dir()
    new_path = repo_root / worktree_dir / branch_name
    legacy_path = repo_root.parent / branch_name
    return new_path, legacy_path

def get_allowed_hosts_for_worktree(branch_name: str) -> str:
    """Generate ALLOWED_HOSTS string for a worktree with explicit subdomain.
    
    Returns a comma-separated string with:
    - localhost, 127.0.0.1 for local access
    - {project-name}-{branch}.localhost for the specific worktree subdomain
    - *.localhost as a wildcard fallback
    - web for inter-container communication
    
    Args:
        branch_name: Branch name for the worktree
        
    Returns:
        Comma-separated ALLOWED_HOSTS string
        
    Example:
        For project 'business_intelligence' and branch 'beta':
        Returns: 'localhost,127.0.0.1,business-intelligence-beta.localhost,*.localhost,web'
    """
    project_name = sanitize_project_name(get_project_name())
    subdomain = f"{project_name}-{branch_name}.localhost"
    return f"localhost,127.0.0.1,{subdomain},*.localhost,web"

# Environment file generation
def generate_env_compose_content(branch_name: str) -> str:
    """Generate env.dockertree content for a worktree."""
    project_root = get_project_root()
    project_name = sanitize_project_name(get_project_name())  # Converts underscores to hyphens
    compose_project_name = f"{project_name}-{branch_name}"
    site_domain = f"{compose_project_name}.localhost"  # RFC-compliant hostname
    allowed_hosts = get_allowed_hosts_for_worktree(branch_name)
    
    return f"""# Dockertree environment configuration for {branch_name}
COMPOSE_PROJECT_NAME={compose_project_name}
PROJECT_ROOT={project_root}
SITE_DOMAIN={site_domain}
ALLOWED_HOSTS={allowed_hosts}
DEBUG=True
USE_X_FORWARDED_HOST=True
CSRF_TRUSTED_ORIGINS=http://{site_domain}
"""

# Volume naming
def get_volume_name(branch_name: str, volume_type: str) -> str:
    """Get worktree-specific volume name."""
    project_name = sanitize_project_name(get_project_name())
    return f"{project_name}-{branch_name}_{volume_type}"

def get_volume_names(branch_name: str) -> dict[str, str]:
    """Get all volume names for a worktree.
    
    Note: Caddy volumes (caddy_data, caddy_config) are intentionally excluded 
    as they are shared globally across all worktrees, not worktree-specific.
    """
    return {
        "postgres": get_volume_name(branch_name, POSTGRES_VOLUME_SUFFIX),
        "redis": get_volume_name(branch_name, REDIS_VOLUME_SUFFIX),
        "media": get_volume_name(branch_name, MEDIA_VOLUME_SUFFIX),
    }
