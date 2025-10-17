"""
Click CLI framework for dockertree CLI.

This module provides the main CLI interface using Click framework.
"""

import sys
from pathlib import Path
from typing import Optional

import click

from .commands.caddy import CaddyManager
from .commands.worktree import WorktreeManager
from .commands.utility import UtilityManager
from .commands.volumes import VolumeManager
from .commands.setup import SetupManager
from .utils.logging import log_error, error_exit, set_verbose
from .utils.validation import check_prerequisites, check_setup_or_prompt
from .utils.pattern_matcher import has_wildcard


class DockertreeCLI(click.MultiCommand):
    """Custom MultiCommand to handle worktree-name-first pattern and dash-prefixed aliases."""
    
    def parse_args(self, ctx, args):
        """Override parse_args to handle worktree-name-first pattern and dash-prefixed commands."""
        if not args:
            return super().parse_args(ctx, args)
        
        # Handle dash-prefixed commands
        if args[0] in ['-D', '-r']:
            if args[0] == '-D':
                args[0] = 'delete'
            elif args[0] == '-r':
                args[0] = 'remove'
        
        # Handle worktree-name-first pattern for up/down commands
        elif len(args) >= 2 and args[1] in ['up', 'down']:
            # Check if first argument is not a reserved command name
            reserved_commands = {
                'start-proxy', 'stop-proxy', 'start', 'stop', 'create', 
                'delete', 'remove', 'remove-all', 'delete-all', 'list', 'prune', 
                'volumes', 'setup', 'help', 'completion', '-D', '-r'
            }
            
            if args[0] not in reserved_commands:
                # This is a worktree name, restructure args
                worktree_name = args[0]
                command = args[1]
                remaining_args = args[2:] if len(args) > 2 else []
                
                # Restructure: worktree_name up -> up worktree_name
                new_args = [command, worktree_name] + remaining_args
                return super().parse_args(ctx, new_args)
        
        # Handle docker compose passthrough pattern: <worktree_name> <compose-args...>
        elif len(args) >= 2:
            # Check if first argument is not a reserved command name
            reserved_commands = {
                'start-proxy', 'stop-proxy', 'start', 'stop', 'create', 
                'delete', 'remove', 'remove-all', 'delete-all', 'list', 'prune', 
                'volumes', 'setup', 'help', 'completion', '-D', '-r'
            }
            
            # Common docker compose subcommands that should trigger passthrough
            compose_commands = {
                'exec', 'logs', 'ps', 'run', 'build', 'pull', 'push', 'restart',
                'start', 'stop', 'up', 'down', 'config', 'images', 'port',
                'top', 'events', 'kill', 'pause', 'unpause', 'scale'
            }
            
            if (args[0] not in reserved_commands and 
                (args[1] in compose_commands or args[1].startswith('-'))):
                # This is a passthrough pattern: worktree_name compose-args
                worktree_name = args[0]
                compose_args = args[1:]
                
                # Store passthrough info in context for later use
                ctx.meta['passthrough'] = {
                    'worktree_name': worktree_name,
                    'compose_args': compose_args
                }
                
                # Route to passthrough command
                new_args = ['passthrough', worktree_name] + compose_args
                return super().parse_args(ctx, new_args)
        
        # Reject old pattern: up/down as first argument
        elif args[0] in ['up', 'down']:
            from .utils.logging import error_exit
            error_exit(f"Error: The command pattern has changed. Use 'dockertree <worktree_name> {args[0]}' instead of 'dockertree {args[0]} <worktree_name>'")
        
        return super().parse_args(ctx, args)
    
    def list_commands(self, ctx):
        """Return list of available commands."""
        return sorted([
            'create', 'delete', 'remove', 'start-proxy', 'stop-proxy', 'start', 'stop', 
            'list', 'prune', 'volumes', 'help', 'delete-all', 'remove-all',
            'setup', 'clean-legacy', 'completion', '_completion', '-D', '-r'  # Add dash-prefixed aliases
        ])
    
    def get_command(self, ctx, name):
        """Get command by name, handling aliases."""
        # Handle dash-prefixed aliases
        if name == '-D':
            return self.get_command(ctx, 'delete')
        elif name == '-r':
            return self.get_command(ctx, 'remove')
        
        # Handle standard commands
        if name == 'delete':
            return delete
        elif name == 'remove':
            return remove
        elif name == 'create':
            return create
        elif name == 'start-proxy':
            return start_proxy
        elif name == 'stop-proxy':
            return stop_proxy
        elif name == 'start':
            return start
        elif name == 'stop':
            return stop
        elif name == 'up':
            return up
        elif name == 'down':
            return down
        elif name == 'list':
            return list
        elif name == 'prune':
            return prune
        elif name == 'volumes':
            return volumes
        elif name == 'help':
            return help
        elif name == 'delete-all':
            return delete_all
        elif name == 'remove-all':
            return remove_all
        elif name == 'setup':
            return setup
        elif name == 'completion':
            return completion
        elif name == '_completion':
            return _completion
        elif name == 'passthrough':
            return passthrough
        return None

# Create the CLI instance
cli = DockertreeCLI(help='Dockertree: Git Worktrees for Isolated Development Environments\n\nUsage: dockertree <worktree_name> up|down  or  dockertree <command>')
cli = click.version_option(version="0.9.0", prog_name="dockertree")(cli)

# Add global verbose option
def verbose_callback(ctx, param, value):
    """Callback to set verbose mode."""
    set_verbose(value)
    return value

cli = click.option('--verbose', '-v', is_flag=True, default=False, 
                   help='Show INFO and WARNING messages', 
                   callback=verbose_callback, expose_value=False, is_eager=True)(cli)


def add_verbose_option(f):
    """Decorator to add verbose option to commands."""
    return click.option('--verbose', '-v', is_flag=True, default=False,
                       help='Show INFO and WARNING messages',
                       callback=verbose_callback, expose_value=False, is_eager=True)(f)


@cli.command('start-proxy')
@add_verbose_option
def start_proxy():
    """Start global Caddy proxy container."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        caddy_manager = CaddyManager()
        success = caddy_manager.start_global_caddy()
        if not success:
            error_exit("Failed to start global Caddy container")
    except Exception as e:
        error_exit(f"Error starting global Caddy: {e}")


@cli.command('stop-proxy')
@add_verbose_option
def stop_proxy():
    """Stop global Caddy proxy container."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        caddy_manager = CaddyManager()
        success = caddy_manager.stop_global_caddy()
        if not success:
            error_exit("Failed to stop global Caddy container")
    except Exception as e:
        error_exit(f"Error stopping global Caddy: {e}")


@cli.command('start')
@add_verbose_option
def start():
    """Start global Caddy proxy container (alias for start-proxy)."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        caddy_manager = CaddyManager()
        success = caddy_manager.start_global_caddy()
        if not success:
            error_exit("Failed to start global Caddy container")
    except Exception as e:
        error_exit(f"Error starting global Caddy: {e}")


@cli.command('stop')
@add_verbose_option
def stop():
    """Stop global Caddy proxy container (alias for stop-proxy)."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        caddy_manager = CaddyManager()
        success = caddy_manager.stop_global_caddy()
        if not success:
            error_exit("Failed to stop global Caddy container")
    except Exception as e:
        error_exit(f"Error stopping global Caddy: {e}")


@cli.command()
@click.argument('branch_name')
@add_verbose_option
def create(branch_name: str):
    """Create worktree in worktrees directory."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        success = worktree_manager.create_worktree(branch_name)
        if not success:
            error_exit(f"Failed to create worktree for {branch_name}")
    except Exception as e:
        error_exit(f"Error creating worktree: {e}")


@cli.command()
@click.argument('branch_name')
@click.option('-d', '--detach', is_flag=True, default=True, help='Run in detached mode')
@add_verbose_option
def up(branch_name: str, detach: bool):
    """Start worktree environment for specified branch.
    
    Usage: dockertree <worktree_name> up [-d]
    """
    if not detach:
        error_exit("Usage: dockertree <worktree_name> up -d")
    
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        success = worktree_manager.start_worktree(branch_name)
        if not success:
            error_exit(f"Failed to start worktree environment for {branch_name}")
    except Exception as e:
        error_exit(f"Error starting worktree: {e}")


@cli.command()
@click.argument('branch_name')
@add_verbose_option
def down(branch_name: str):
    """Stop worktree environment for specified branch.
    
    Usage: dockertree <worktree_name> down
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        worktree_manager.stop_worktree(branch_name)
    except Exception as e:
        error_exit(f"Error stopping worktree: {e}")


@cli.command()
@click.argument('branch_name')
@click.option('--force', is_flag=True, help='Force removal even with unmerged changes')
@add_verbose_option
def delete(branch_name: str, force: bool):
    """Delete worktree and branch completely.
    
    Supports wildcard patterns: test-*, feature-?, bugfix-[abc]
    Case-insensitive matching with confirmation for multiple matches.
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        
        # Check if branch_name contains wildcard characters
        if has_wildcard(branch_name):
            # Use pattern-based removal
            success = worktree_manager.remove_worktrees_by_pattern(branch_name, force, delete_branch=True)
            if not success:
                error_exit(f"Failed to remove worktrees matching pattern: {branch_name}")
        else:
            # Use single branch removal
            success = worktree_manager.remove_worktree(branch_name, force)
            if not success:
                error_exit(f"Failed to remove worktree for {branch_name}")
    except Exception as e:
        error_exit(f"Error removing worktree: {e}")




@cli.command()
@click.option('--force', is_flag=True, help='Force removal even with unmerged changes')
@add_verbose_option
def delete_all(force: bool):
    """Delete all worktrees, containers, and volumes."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        success = worktree_manager.remove_all_worktrees(force)
        if not success:
            error_exit("Failed to remove all worktrees")
    except Exception as e:
        error_exit(f"Error removing all worktrees: {e}")


@cli.command()
@click.argument('branch_name')
@click.option('--force', is_flag=True, help='Force removal even with unmerged changes')
@add_verbose_option
def remove(branch_name: str, force: bool):
    """Remove worktree and containers/volumes but keep git branch.
    
    Supports wildcard patterns: test-*, feature-?, bugfix-[abc]
    Case-insensitive matching with confirmation for multiple matches.
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        
        # Check if branch_name contains wildcard characters
        if has_wildcard(branch_name):
            # Use pattern-based removal
            success = worktree_manager.remove_worktrees_by_pattern(branch_name, force, delete_branch=False)
            if not success:
                error_exit(f"Failed to remove worktrees matching pattern: {branch_name}")
        else:
            # Use single branch removal
            success = worktree_manager.remove_worktree(branch_name, force, delete_branch=False)
            if not success:
                error_exit(f"Failed to remove worktree for {branch_name}")
    except Exception as e:
        error_exit(f"Error removing worktree: {e}")




@cli.command()
@click.option('--force', is_flag=True, help='Force removal even with unmerged changes')
@add_verbose_option
def remove_all(force: bool):
    """Remove all worktrees and containers/volumes but keep git branches."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        success = worktree_manager.remove_all_worktrees(force, delete_branch=False)
        if not success:
            error_exit("Failed to remove all worktrees")
    except Exception as e:
        error_exit(f"Error removing all worktrees: {e}")


@cli.command()
@add_verbose_option
def list():
    """List active worktrees."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        utility_manager = UtilityManager()
        utility_manager.list_worktrees()
    except Exception as e:
        error_exit(f"Error listing worktrees: {e}")


@cli.command()
@add_verbose_option
def prune():
    """Remove prunable worktree references."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        utility_manager = UtilityManager()
        utility_manager.prune_worktrees()
    except Exception as e:
        error_exit(f"Error pruning worktrees: {e}")


@cli.group()
@add_verbose_option
def volumes():
    """Volume management commands."""
    pass


@volumes.command('list')
@add_verbose_option
def volumes_list():
    """List all worktree volumes."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        volume_manager.list_volumes()
    except Exception as e:
        error_exit(f"Error listing volumes: {e}")


@volumes.command('size')
@add_verbose_option
def volumes_size():
    """Show volume sizes."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        volume_manager.show_volume_sizes()
    except Exception as e:
        error_exit(f"Error showing volume sizes: {e}")


@volumes.command('backup')
@click.argument('branch_name')
@click.option('--backup-dir', type=click.Path(), help='Backup directory path')
@add_verbose_option
def volumes_backup(branch_name: str, backup_dir: Optional[str]):
    """Backup worktree volumes."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        backup_path = Path(backup_dir) if backup_dir else None
        success = volume_manager.backup_volumes(branch_name, backup_path)
        if not success:
            error_exit(f"Failed to backup volumes for {branch_name}")
    except Exception as e:
        error_exit(f"Error backing up volumes: {e}")


@volumes.command('restore')
@click.argument('branch_name')
@click.argument('backup_file', type=click.Path(exists=True))
@add_verbose_option
def volumes_restore(branch_name: str, backup_file: str):
    """Restore worktree volumes from backup."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        success = volume_manager.restore_volumes(branch_name, Path(backup_file))
        if not success:
            error_exit(f"Failed to restore volumes for {branch_name}")
    except Exception as e:
        error_exit(f"Error restoring volumes: {e}")


@volumes.command('clean')
@click.argument('branch_name')
@add_verbose_option
def volumes_clean(branch_name: str):
    """Clean up worktree volumes."""
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        success = volume_manager.clean_volumes(branch_name)
        if not success:
            error_exit(f"Failed to clean volumes for {branch_name}")
    except Exception as e:
        error_exit(f"Error cleaning volumes: {e}")


@cli.command()
@click.option('--project-name', help='Project name (default: directory name)')
@add_verbose_option
def setup(project_name: Optional[str]):
    """Initialize dockertree for this project."""
    try:
        check_prerequisites()
        setup_manager = SetupManager()
        success = setup_manager.setup_project(project_name)
        if not success:
            error_exit("Failed to setup dockertree for this project")
    except Exception as e:
        error_exit(f"Error setting up dockertree: {e}")


@cli.command('clean-legacy')
@add_verbose_option
def clean_legacy():
    """Clean legacy dockertree elements from docker-compose.yml."""
    try:
        from .commands.setup import SetupManager
        setup_manager = SetupManager()
        success = setup_manager.clean_legacy_elements()
        if not success:
            error_exit("Failed to clean legacy dockertree elements")
    except Exception as e:
        error_exit(f"Error cleaning legacy elements: {e}")


@cli.command()
@add_verbose_option
def help():
    """Show help information."""
    click.echo(cli.get_help(click.Context(cli)))


@cli.command(hidden=True)
@click.argument('completion_type')
@add_verbose_option
def _completion(completion_type: str):
    """Hidden command for shell completion support."""
    from .utils.completion_helper import get_completion_for_context, print_completions
    
    try:
        completions = get_completion_for_context(completion_type)
        print_completions(completions)
    except Exception:
        # If completion fails, don't break the shell
        pass


@cli.group()
@add_verbose_option
def completion():
    """Shell completion management commands."""
    pass


@completion.command('install')
@click.argument('shell', required=False)
@add_verbose_option
def completion_install(shell: Optional[str]):
    """Install shell completion for dockertree."""
    try:
        from .commands.completion import CompletionManager
        completion_manager = CompletionManager()
        success = completion_manager.install_completion(shell)
        if not success:
            error_exit("Failed to install shell completion")
    except Exception as e:
        error_exit(f"Error installing shell completion: {e}")


@completion.command('uninstall')
@add_verbose_option
def completion_uninstall():
    """Remove shell completion for dockertree."""
    try:
        from .commands.completion import CompletionManager
        completion_manager = CompletionManager()
        success = completion_manager.uninstall_completion()
        if not success:
            error_exit("Failed to uninstall shell completion")
    except Exception as e:
        error_exit(f"Error uninstalling shell completion: {e}")


@completion.command('status')
@add_verbose_option
def completion_status():
    """Show shell completion installation status."""
    try:
        from .commands.completion import CompletionManager
        completion_manager = CompletionManager()
        completion_manager.show_completion_status()
    except Exception as e:
        error_exit(f"Error checking completion status: {e}")


@cli.command(context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('branch_name')
@add_verbose_option
def passthrough(branch_name: str):
    """Run docker compose command with automatic override file resolution.
    
    Usage: dockertree <worktree_name> <compose-args...>
    
    Examples:
        dockertree feature-123 exec web python manage.py migrate
        dockertree feature-123 logs -f web
        dockertree feature-123 ps
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        
        # Get the remaining arguments from the context
        import click
        ctx = click.get_current_context()
        compose_args_list = ctx.args
        
        # Validate worktree exists
        from .core.git_manager import GitManager
        git_manager = GitManager()
        if not git_manager.validate_worktree_exists(branch_name):
            error_exit(f"Worktree for branch '{branch_name}' does not exist. Please create it first with: dockertree create {branch_name}")
        
        # Validate compose override exists
        from .utils.validation import validate_compose_override_exists
        if not validate_compose_override_exists(branch_name):
            error_exit(f"Compose override file not found for worktree '{branch_name}'. Please ensure the worktree is properly set up.")
        
        # Run the passthrough command
        from .core.docker_manager import DockerManager
        docker_manager = DockerManager()
        success = docker_manager.run_compose_passthrough(branch_name, compose_args_list)
        
        if not success:
            error_exit(f"Failed to run docker compose command for worktree '{branch_name}'")
            
    except Exception as e:
        error_exit(f"Error running docker compose command: {e}")


def main():
    """Main entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        log_error("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
