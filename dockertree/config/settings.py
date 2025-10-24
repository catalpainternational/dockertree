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
VERSION = "0.9.0"
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

# Environment file generation
def generate_env_compose_content(branch_name: str) -> str:
    """Generate env.dockertree content for a worktree."""
    project_root = get_project_root()
    project_name = sanitize_project_name(get_project_name())  # Converts underscores to hyphens
    compose_project_name = f"{project_name}-{branch_name}"
    site_domain = f"{compose_project_name}.localhost"  # RFC-compliant hostname
    
    return f"""# Dockertree environment configuration for {branch_name}
COMPOSE_PROJECT_NAME={compose_project_name}
PROJECT_ROOT={project_root}
SITE_DOMAIN={site_domain}
ALLOWED_HOSTS=localhost,127.0.0.1,${{COMPOSE_PROJECT_NAME}}.localhost,*.localhost,web,${{COMPOSE_PROJECT_NAME}}-web
DEBUG=True
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
