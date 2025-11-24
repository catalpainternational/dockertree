"""
Configuration management for dockertree MCP server.

This module provides configuration management for the MCP server with
enhanced project detection and context awareness.
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


class MCPConfig:
    """Configuration for dockertree MCP server with project detection."""
    
    def __init__(
        self,
        working_directory: Optional[Path] = None,
        dockertree_path: Optional[str] = None,
        timeout: int = 300,
        verbose: bool = False
    ):
        """Initialize MCP configuration.
        
        Args:
            working_directory: Target project directory where dockertree should operate.
                              Defaults to current working directory if not provided.
                              This is the directory containing the project's docker-compose.yml
                              and where .dockertree/ directory will be created.
            dockertree_path: Path to dockertree executable (optional)
            timeout: Command timeout in seconds
            verbose: Enable verbose logging
        """
        # Validate and set working directory
        if working_directory is None:
            working_directory = Path.cwd()
        elif isinstance(working_directory, str):
            working_directory = Path(working_directory)
        
        # Track whether the directory currently exists but avoid hard failures so
        # tests (and callers eagerly configuring future paths) can still proceed.
        missing_directory = not working_directory.exists()
        if not missing_directory and not working_directory.is_dir():
            raise ValueError(f"Working directory is not a directory: {working_directory}")

        # Resolve to absolute path even if the directory does not currently exist.
        self.working_directory = working_directory.resolve()
        self.working_directory_exists = not missing_directory
        self.dockertree_path = dockertree_path
        self.timeout = timeout
        self.verbose = verbose
        
        # Environment variables
        self.env = os.environ.copy()
        
        # Project context (detected)
        self.project_name = self._detect_project_name()
        self.dockertree_initialized = self._is_dockertree_initialized()
        self.dockertree_config = self._read_dockertree_config()
        self.available_services = self._get_available_services()
    
    def _detect_project_name(self) -> str:
        """Detect project name from dockertree config or directory."""
        try:
            # Try to read from .dockertree/config.yml
            config_path = self.working_directory / ".dockertree" / "config.yml"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f)
                    raw_name = config_data.get('project_name', 'unknown')
            else:
                # Fallback to directory name
                raw_name = self.working_directory.name
            
            # Sanitize the project name for URL compatibility
            from dockertree.config.settings import sanitize_project_name
            return sanitize_project_name(raw_name)
        except Exception:
            # Fallback to directory name with sanitization
            from dockertree.config.settings import sanitize_project_name
            return sanitize_project_name(self.working_directory.name)
    
    def _is_dockertree_initialized(self) -> bool:
        """Check if dockertree is initialized in this project."""
        dockertree_dir = self.working_directory / ".dockertree"
        # Check if .dockertree exists and has either config.yml OR worktrees directory
        return dockertree_dir.exists() and (
            (dockertree_dir / "config.yml").exists() or 
            (dockertree_dir / "worktrees").exists()
        )
    
    def _read_dockertree_config(self) -> Dict[str, Any]:
        """Read dockertree configuration if available."""
        try:
            config_path = self.working_directory / ".dockertree" / "config.yml"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
        except Exception:
            pass
        return {}
    
    def _get_available_services(self) -> list:
        """Get available services from docker-compose.yml."""
        try:
            compose_path = self.working_directory / "docker-compose.yml"
            if compose_path.exists():
                with open(compose_path, 'r') as f:
                    compose_data = yaml.safe_load(f)
                    return list(compose_data.get('services', {}).keys())
        except Exception:
            pass
        return []
    
    def get_url_pattern(self) -> str:
        """Generate actual URL pattern for this project."""
        return f"http://{self.project_name}-{{branch_name}}.localhost"
    
    def validate_for_dockertree(self) -> Dict[str, Any]:
        """Validate that the working directory is suitable for dockertree operations.
        
        Returns:
            Dict with validation results including warnings and errors
        """
        results = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "suggestions": []
        }
        
        # Check for docker-compose.yml
        compose_file = self.working_directory / "docker-compose.yml"
        if not compose_file.exists():
            results["warnings"].append("No docker-compose.yml found in working directory")
            results["suggestions"].append("Ensure you're in the correct project directory with docker-compose.yml")
        
        # Check if it's a git repository
        git_dir = self.working_directory / ".git"
        if not git_dir.exists():
            results["warnings"].append("Not a Git repository")
            results["suggestions"].append("Initialize with 'git init' or navigate to a Git repository")
        
        # Check for existing dockertree setup
        dockertree_dir = self.working_directory / ".dockertree"
        if dockertree_dir.exists():
            results["suggestions"].append("Dockertree is already initialized in this directory")
        else:
            results["suggestions"].append("Run 'dockertree setup' to initialize dockertree in this directory")
        
        # Check write permissions
        try:
            test_file = self.working_directory / ".dockertree_test_write"
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            results["errors"].append("No write permission in working directory")
            results["valid"] = False
        
        return results
    
    def get_project_context(self) -> Dict[str, Any]:
        """Get comprehensive project context."""
        return {
            "project_name": self.project_name,
            "working_directory": str(self.working_directory),
            "dockertree_initialized": self.dockertree_initialized,
            "url_pattern": self.get_url_pattern(),
            "dockertree_dir": str(self.working_directory / ".dockertree"),
            "worktrees_dir": str(self.working_directory / ".dockertree" / "worktrees"),
            "available_services": self.available_services,
            "config": self.dockertree_config
        }
    
    @classmethod
    def from_env(cls) -> "MCPConfig":
        """Create configuration from environment variables."""
        working_dir = os.getenv("DOCKERTREE_WORKING_DIR")
        dockertree_path = os.getenv("DOCKERTREE_PATH")
        timeout = int(os.getenv("DOCKERTREE_TIMEOUT", "300"))
        verbose = os.getenv("DOCKERTREE_VERBOSE", "false").lower() == "true"
        
        return cls(
            working_directory=Path(working_dir) if working_dir else None,
            dockertree_path=dockertree_path,
            timeout=timeout,
            verbose=verbose
        )
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            "working_directory": str(self.working_directory),
            "dockertree_path": self.dockertree_path,
            "timeout": self.timeout,
            "verbose": self.verbose,
            "project_name": self.project_name,
            "dockertree_initialized": self.dockertree_initialized,
            "available_services": self.available_services
        }
