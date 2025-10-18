"""
Direct Python API for dockertree operations.

This module provides direct access to dockertree core functionality,
bypassing CLI commands for richer responses and better integration
with the MCP server.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import MCPConfig
from dockertree.core.worktree_orchestrator import WorktreeOrchestrator


class DockertreeAPI:
    """Direct Python API for dockertree operations."""
    
    def __init__(self, config: MCPConfig):
        """Initialize the dockertree API."""
        self.config = config
        self.orchestrator = WorktreeOrchestrator(config.working_directory, mcp_mode=True)
        
        # Project context
        self.project_name = self._detect_project_name()
        self.dockertree_initialized = self._is_dockertree_initialized()
    
        
    def _detect_project_name(self) -> str:
        """Detect project name from dockertree config or directory."""
        try:
            # Try to read from .dockertree/config.yml
            config_path = Path(self.config.working_directory) / ".dockertree" / "config.yml"
            if config_path.exists():
                import yaml
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f)
                    return config_data.get('project_name', 'unknown')
        except Exception:
            pass
        
        # Fallback to directory name
        return Path(self.config.working_directory).name
    
    def _is_dockertree_initialized(self) -> bool:
        """Check if dockertree is initialized in this project."""
        dockertree_dir = Path(self.config.working_directory) / ".dockertree"
        return dockertree_dir.exists() and (dockertree_dir / "config.yml").exists()
    
    def get_project_context(self) -> Dict[str, Any]:
        """Get current project context and configuration."""
        return {
            "project_name": self.project_name,
            "working_directory": str(self.config.working_directory),
            "dockertree_initialized": self.dockertree_initialized,
            "url_pattern": f"http://{self.project_name}-{{branch_name}}.localhost",
            "dockertree_dir": str(Path(self.config.working_directory) / ".dockertree"),
            "worktrees_dir": str(Path(self.config.working_directory) / ".dockertree" / "worktrees")
        }
    
    def _enrich_error(self, result: Dict[str, Any], branch_name: str = None) -> Dict[str, Any]:
        """Enrich error result with dockertree context."""
        return {
            "success": False,
            "error": result['error'],
            "dockertree_context": {
                "concept": "Dockertree creates isolated environments for Git branches",
                "troubleshooting": [
                    "Check if Docker is running: docker ps",
                    "Verify you're in a Git repository",
                    "Ensure dockertree is initialized: dockertree setup"
                ]
            }
        }
    
    async def create_worktree_api(self, branch_name: str) -> Dict[str, Any]:
        """Create a new worktree - MCP interface."""
        result = self.orchestrator.create_worktree(branch_name)
        
        # MCP-specific: Add dockertree_context
        if result['success']:
            return {
                "success": True,
                "data": result['data'],
                "dockertree_context": {
                    "concept": f"Created isolated development environment for branch '{branch_name}'",
                    "project": self.project_name,
                    "branch": branch_name,
                    "url": f"http://{self.project_name}-{branch_name}.localhost",
                    "next_steps": [
                        f"Use start_worktree('{branch_name}') to launch containers",
                        f"Access at http://{self.project_name}-{branch_name}.localhost",
                        f"Use get_worktree_info('{branch_name}') to see status"
                    ],
                    "workflow_stage": "created"
                }
            }
        else:
            return self._enrich_error(result, branch_name)
    
    async def start_worktree_api(self, branch_name: str) -> Dict[str, Any]:
        """Start worktree containers - MCP interface."""
        result = self.orchestrator.start_worktree(branch_name)
        
        # MCP context enrichment
        if result['success']:
            data = result['data']
            return {
                "success": True,
                "data": data,
                "dockertree_context": {
                    "concept": f"Started isolated development environment for branch '{branch_name}'",
                    "project": self.project_name,
                    "branch": branch_name,
                    "url": f"http://{self.project_name}-{branch_name}.localhost",
                    "next_steps": [
                        f"Access your environment at http://{self.project_name}-{branch_name}.localhost",
                        f"Use get_worktree_info('{branch_name}') to see detailed status",
                        f"Use stop_worktree('{branch_name}') to stop when done"
                    ],
                    "workflow_stage": "running"
                }
            }
        else:
            return self._enrich_error(result, branch_name)
    
    async def stop_worktree_api(self, branch_name: str) -> Dict[str, Any]:
        """Stop worktree containers - MCP interface."""
        result = self.orchestrator.stop_worktree(branch_name)
        
        # MCP context enrichment
        if result['success']:
            return {
                "success": True,
                "data": result['data'],
                "dockertree_context": {
                    "concept": f"Stopped isolated development environment for branch '{branch_name}'",
                    "project": self.project_name,
                    "branch": branch_name,
                    "next_steps": [
                        f"Data is preserved in branch-specific volumes",
                        f"Use start_worktree('{branch_name}') to restart",
                        f"Use remove_worktree('{branch_name}') to clean up completely"
                    ],
                    "workflow_stage": "stopped"
                }
            }
        else:
            return self._enrich_error(result, branch_name)
    
    async def get_worktree_status_api(self, branch_name: str) -> Dict[str, Any]:
        """Get comprehensive worktree status - MCP interface."""
        result = self.orchestrator.get_worktree_info(branch_name)
        
        # MCP context enrichment
        if result['success']:
            data = result['data']
            is_running = data.get('status') == 'running'
            return {
                "success": True,
                "data": data,
                "dockertree_context": {
                    "concept": f"Status of isolated development environment for branch '{branch_name}'",
                    "project": self.project_name,
                    "branch": branch_name,
                    "url": f"http://{self.project_name}-{branch_name}.localhost",
                    "next_steps": [
                        f"Access at http://{self.project_name}-{branch_name}.localhost" if is_running else f"Use start_worktree('{branch_name}') to launch",
                        f"Use stop_worktree('{branch_name}') to stop" if is_running else f"Environment is stopped, data preserved in volumes"
                    ],
                    "workflow_stage": "running" if is_running else "stopped"
                }
            }
        else:
            return self._enrich_error(result, branch_name)
    
    async def list_worktrees_api(self) -> Dict[str, Any]:
        """List all worktrees - MCP interface."""
        result = self.orchestrator.list_worktrees()
        
        # MCP context enrichment
        if result['success']:
            worktrees = result['data']
            return {
                "success": True,
                "data": worktrees,
                "dockertree_context": {
                    "concept": f"Found {len(worktrees)} isolated development environments",
                    "project": self.project_name,
                    "next_steps": [
                        f"Access any running environment at http://{self.project_name}-{{branch}}.localhost",
                        f"Use get_worktree_info('branch-name') for detailed status",
                        f"Create new environment: create_worktree('new-feature')"
                    ]
                }
            }
        else:
            return self._enrich_error(result)
    
    async def remove_worktree_api(self, branch_name: str, force: bool = False) -> Dict[str, Any]:
        """Remove worktree and containers but keep git branch - MCP interface."""
        result = self.orchestrator.remove_worktree(branch_name, force, delete_branch=False)
        
        # MCP context enrichment
        if result['success']:
            return {
                "success": True,
                "data": result['data'],
                "dockertree_context": {
                    "concept": f"Removed isolated development environment for branch '{branch_name}' (git branch preserved)",
                    "project": self.project_name,
                    "branch": branch_name,
                    "next_steps": [
                        f"Git branch '{branch_name}' still exists",
                        f"Use create_worktree('{branch_name}') to recreate environment",
                        f"Use delete_worktree('{branch_name}') to also delete git branch"
                    ],
                    "workflow_stage": "removed"
                }
            }
        else:
            return self._enrich_error(result, branch_name)
    
    async def delete_worktree_api(self, branch_name: str, force: bool = False) -> Dict[str, Any]:
        """Delete worktree, containers, and git branch completely - MCP interface."""
        result = self.orchestrator.delete_worktree(branch_name, force)
        
        # MCP context enrichment
        if result['success']:
            return {
                "success": True,
                "data": result['data'],
                "dockertree_context": {
                    "concept": f"Completely deleted isolated development environment and git branch '{branch_name}'",
                    "project": self.project_name,
                    "branch": branch_name,
                    "next_steps": [
                        f"Environment and git branch '{branch_name}' are completely removed",
                        f"Create new branch and environment: create_worktree('new-feature')",
                        f"Use remove_worktree() to keep git branch in future"
                    ],
                    "workflow_stage": "deleted"
                }
            }
        else:
            return self._enrich_error(result, branch_name)
