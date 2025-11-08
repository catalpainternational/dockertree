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

# Global MCP mode flag - when True, don't print to stdout
_mcp_mode = False

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

def set_mcp_mode(enabled: bool) -> None:
    """Set MCP mode - when enabled, don't print to stdout."""
    global _mcp_mode
    _mcp_mode = enabled

def is_mcp_mode() -> bool:
    """Check if MCP mode is enabled."""
    return _mcp_mode

def is_verbose() -> bool:
    """Check if verbose mode is enabled."""
    return _verbose_mode

def log_info(message: str) -> None:
    """Log an info message (only shown in verbose mode)."""
    if _verbose_mode:
        console.print(f"[{Colors.BLUE}][INFO][/{Colors.BLUE}] {message}")

def log_success(message: str) -> None:
    """Log a success message."""
    if not _mcp_mode:
        console.print(f"[{Colors.GREEN}][SUCCESS][/{Colors.GREEN}] {message}")

def log_warning(message: str) -> None:
    """Log a warning message (only shown in verbose mode)."""
    if _verbose_mode:
        console.print(f"[{Colors.YELLOW}][WARNING][/{Colors.YELLOW}] {message}")

def log_error(message: str) -> None:
    """Log an error message."""
    if not _mcp_mode:
        console.print(f"[{Colors.RED}][ERROR][/{Colors.RED}] {message}")

def log_phase(message: str) -> None:
    """Log a phase message."""
    if not _mcp_mode:
        console.print(f"[{Colors.PURPLE}][PHASE][/{Colors.PURPLE}] {message}")

def log_test(message: str) -> None:
    """Log a test message."""
    if not _mcp_mode:
        console.print(f"[{Colors.CYAN}][TEST][/{Colors.CYAN}] {message}")

def print_plain(message: str) -> None:
    """Print plain text without any prefix."""
    if not _mcp_mode:
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

Create isolated development environments using Git worktrees with Docker Compose.
Each worktree gets its own database, Redis, media storage, and unique URL.

USAGE:
    dockertree <worktree_name> up|down
    dockertree <command> [options]

COMMANDS:
    start                    Start global Caddy proxy container
    stop                     Stop global Caddy proxy container
    create <branch-name>     Create worktree for specified branch
    <worktree> up            Start worktree environment
    <worktree> down          Stop worktree environment
    delete <branch-name>     Delete worktree and branch completely
    remove <branch-name>     Remove worktree but keep git branch
    list                     List all active worktrees
    prune                    Remove prunable worktree references
    volumes                  Manage Docker volumes for worktrees
    packages                 Manage environment packages
    droplets                 Manage DigitalOcean droplets
    domains                  Manage DNS domains and records
    push                     Push package to remote server
    setup                    Initialize dockertree for project
    completion               Manage shell completion
    --version, -v            Show version information
    help                     Show this help message

EXAMPLES:
    # Start global Caddy proxy
    dockertree start
    
    # Create and start a worktree
    dockertree create feature-auth
    dockertree feature-auth up
    
    # Access environment (URL format: http://project-branch.localhost)
    open http://myproject-feature-auth.localhost
    
    # Stop and remove worktree (keeps git branch)
    dockertree feature-auth down
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
    dockertree volumes list                    List all worktree volumes
    dockertree volumes size                    Show volume sizes
    dockertree volumes backup <branch-name>    Backup worktree volumes
    dockertree volumes restore <branch-name> <backup-file.tar>
                                                Restore worktree volumes
    dockertree volumes clean <branch-name>     Clean up worktree volumes

For more information, use: dockertree <command> --help"""
    
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
