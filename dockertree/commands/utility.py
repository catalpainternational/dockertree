"""
Utility commands for dockertree CLI.

This module provides utility commands like listing worktrees, pruning, and showing help.
"""

from ..core.git_manager import GitManager
from ..utils.logging import log_info, log_success, print_plain, show_version, show_help


class UtilityManager:
    """Manages utility commands."""
    
    def __init__(self):
        """Initialize utility manager."""
        self.git_manager = GitManager()
    
    def list_worktrees(self) -> None:
        """List active worktrees."""
        worktrees = self.git_manager.list_worktrees()
        
        if not worktrees:
            print_plain("No worktrees found")
            return
        
        for path, commit, branch in worktrees:
            print_plain(f"{branch}")
    
    def prune_worktrees(self) -> None:
        """Prune worktrees."""
        log_info("Pruning worktrees...")
        pruned_count = self.git_manager.prune_worktrees()
        
        if pruned_count == 0:
            log_info("No prunable worktrees found")
        else:
            log_success(f"Successfully pruned {pruned_count} worktree(s)")
    
    def show_version_info(self) -> None:
        """Show version information."""
        show_version()
    
    def show_help_info(self) -> None:
        """Show help information."""
        show_help()
    
    def get_system_info(self) -> dict:
        """Get system information."""
        return {
            "current_branch": self.git_manager.get_current_branch(),
            "worktrees": self.git_manager.list_worktrees(),
            "git_info": {
                "current_branch": self.git_manager.get_current_branch(),
                "worktree_count": len(self.git_manager.list_worktrees())
            }
        }
