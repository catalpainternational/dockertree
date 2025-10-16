"""
Logging and output utilities for dockertree CLI.

This module provides colored output and logging functionality that matches
the bash script's output format.
"""

from typing import Any, Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.text import Text

# Initialize console for colored output
console = Console()

# Global verbose mode flag
_verbose_mode = False

# Color constants (matching bash script)
class Colors:
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    BLUE = "blue"
    PURPLE = "purple"
    CYAN = "cyan"

def set_verbose(enabled: bool) -> None:
    """Set verbose mode for logging output."""
    global _verbose_mode
    _verbose_mode = enabled

def is_verbose() -> bool:
    """Check if verbose mode is enabled."""
    return _verbose_mode

def log_info(message: str) -> None:
    """Log an info message (only shown in verbose mode)."""
    if _verbose_mode:
        console.print(f"[{Colors.BLUE}][INFO][/{Colors.BLUE}] {message}")

def log_success(message: str) -> None:
    """Log a success message."""
    console.print(f"[{Colors.GREEN}][SUCCESS][/{Colors.GREEN}] {message}")

def log_warning(message: str) -> None:
    """Log a warning message (only shown in verbose mode)."""
    if _verbose_mode:
        console.print(f"[{Colors.YELLOW}][WARNING][/{Colors.YELLOW}] {message}")

def log_error(message: str) -> None:
    """Log an error message."""
    console.print(f"[{Colors.RED}][ERROR][/{Colors.RED}] {message}")

def log_phase(message: str) -> None:
    """Log a phase message."""
    console.print(f"[{Colors.PURPLE}][PHASE][/{Colors.PURPLE}] {message}")

def log_test(message: str) -> None:
    """Log a test message."""
    console.print(f"[{Colors.CYAN}][TEST][/{Colors.CYAN}] {message}")

def print_plain(message: str) -> None:
    """Print plain text without any prefix."""
    console.print(message)

def show_version() -> None:
    """Show version information."""
    from dockertree.config.settings import VERSION, AUTHOR
    
    version_text = f"""Dockertree v{VERSION}
{AUTHOR}

Git Worktrees for Isolated Development Environments"""
    
    console.print(Panel(version_text, title="Dockertree", border_style=Colors.BLUE))

def show_help() -> None:
    """Show help information."""
    help_text = """Dockertree: Git Worktrees for Isolated Development Environments

USAGE:
    dockertree <command> [options]

COMMANDS:
    start                    Start global Caddy container
    stop                     Stop global Caddy container
    create <branch-name>     Create worktree and change directory
    up -d                    Start worktree environment
    down                     Stop worktree environment
    delete <branch-name> [--force]  Delete worktree and branch completely
    remove <branch-name> [--force]  Remove worktree and containers/volumes but keep git branch
    list                     List active worktrees
    prune                    Remove prunable worktree references
    --version|-v             Show version information
    help                     Show this help message

EXAMPLES:
    # Start global Caddy
    dockertree start
    
    # Create and start a worktree
    dockertree create feature-auth
    dockertree up -d
    
    # Access environment (URL format: http://project-branch.localhost)
    open http://myproject-feature-auth.localhost
    
    # Stop and remove worktree (keeps git branch)
    dockertree down
    dockertree remove feature-auth
    
    # Or delete worktree completely (removes git branch)
    dockertree delete feature-auth
    
    # Force remove worktree with unmerged changes
    dockertree remove feature-auth --force
    
    # Clean up prunable worktrees
    dockertree prune
    
    # Stop global Caddy
    dockertree stop

VOLUME MANAGEMENT:
    dockertree volumes list                    # List all worktree volumes
    dockertree volumes size                    # Show volume sizes
    dockertree volumes backup <branch-name>     # Backup worktree volumes
    dockertree volumes restore <branch-name> <backup-file.tar>  # Restore worktree volumes
    dockertree volumes clean <branch-name>     # Clean up worktree volumes"""
    
    console.print(Panel(help_text, title="Dockertree Help", border_style=Colors.BLUE))

def show_progress(message: str) -> Progress:
    """Show a progress indicator for long-running operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn(f"[{Colors.BLUE}]{message}[/{Colors.BLUE}]"),
        console=console,
        transient=True
    )

def error_exit(message: str, exit_code: int = 1) -> None:
    """Log an error and exit."""
    log_error(message)
    raise SystemExit(exit_code)
