"""
Click CLI framework for dockertree CLI.

This module provides the main CLI interface using Click framework.
"""

import sys
import time
from pathlib import Path
from typing import Optional

import click

from .commands.caddy import CaddyManager
from .commands.worktree import WorktreeManager
from .commands.utility import UtilityManager
from .commands.volumes import VolumeManager
from .commands.setup import SetupManager
from .commands.packages import PackageCommands
from .commands.push import PushManager
from .commands.droplets import DropletCommands
from .commands.domains import DomainCommands
from .core.dns_manager import parse_domain
from .utils.logging import log_error, log_info, log_warning, log_success, error_exit, set_verbose, format_elapsed_time, print_plain
from .utils.path_utils import detect_execution_context, get_worktree_branch_name
from .utils.validation import check_prerequisites, check_setup_or_prompt, check_prerequisites_no_git
from .utils.pattern_matcher import has_wildcard
from .utils.json_output import JSONOutput, add_json_option, handle_json_output


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
                'volumes', 'setup', 'help', 'completion', 'droplet', 'domains', '-D', '-r'
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
                'volumes', 'setup', 'help', 'completion', 'packages', 'droplet', 'domains', '-D', '-r'
            }
            
            # Common docker compose subcommands that should trigger passthrough
            compose_commands = {
                'exec', 'logs', 'ps', 'run', 'build', 'pull', 'restart',
                'up', 'down', 'config', 'images', 'port',
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
            'list', 'prune', 'volumes', 'packages', 'help', 'delete-all', 'remove-all',
            'setup', 'clean-legacy', 'completion', '_completion', 'droplet', 'domains', '-D', '-r'  # Add dash-prefixed aliases
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
        elif name == 'packages':
            return packages
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
        elif name == 'droplet':
            return droplet
        elif name == 'domains':
            return domains
        elif name == 'passthrough':
            return passthrough
        return None

# Create the CLI instance
cli = DockertreeCLI(help='''Dockertree: Git Worktrees for Isolated Development Environments

Create isolated development environments using Git worktrees with Docker Compose.
Each worktree gets its own database, Redis, media storage, and unique URL.

Usage:
    dockertree <worktree_name> up|down

    dockertree <command> [options]

Examples:
    # Create and start a worktree
    dockertree create feature-auth

    dockertree feature-auth up

    # Stop and remove a worktree
    dockertree feature-auth down

    dockertree remove feature-auth

    # List all active worktrees
    dockertree list

For more information, use: dockertree <command> --help''')
cli = click.version_option(version="0.9.4", prog_name="dockertree")(cli)

# Add global verbose option
def verbose_callback(ctx, param, value):
    """Callback to set verbose mode."""
    set_verbose(value)
    return value

cli = click.option('--verbose', '-v', is_flag=True, default=False, 
                   help='Enable verbose output (show INFO and WARNING messages)', 
                   callback=verbose_callback, expose_value=False, is_eager=True)(cli)


def add_verbose_option(f):
    """Decorator to add verbose option to commands."""
    return click.option('--verbose', '-v', is_flag=True, default=False,
                       help='Enable verbose output (show INFO and WARNING messages)',
                       callback=verbose_callback, expose_value=False, is_eager=True)(f)


@cli.command('start-proxy')
@click.option('--non-interactive', is_flag=True, default=False, help='Run non-interactively', hidden=True)
@add_json_option
@add_verbose_option
def start_proxy(non_interactive: bool, json: bool):
    """Start the global Caddy proxy container.

    The Caddy proxy enables automatic routing to worktree environments.
    This must be running for worktrees to be accessible via their URLs.

    Examples:

        dockertree start-proxy

        dockertree start  # alias for start-proxy
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        caddy_manager = CaddyManager()
        success = caddy_manager.start_global_caddy()
        if not success:
            if json:
                JSONOutput.print_error("Failed to start global Caddy container")
            else:
                error_exit("Failed to start global Caddy container")
        else:
            if json:
                JSONOutput.print_success("Global Caddy proxy started successfully")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error starting global Caddy: {e}")
        else:
            error_exit(f"Error starting global Caddy: {e}")


@cli.command('stop-proxy')
@click.option('--non-interactive', is_flag=True, default=False, help='Run non-interactively', hidden=True)
@add_json_option
@add_verbose_option
def stop_proxy(non_interactive: bool, json: bool):
    """Stop the global Caddy proxy container.

    Stops the Caddy proxy, which will make all worktree URLs inaccessible.
    Worktree containers will continue running but won't be accessible via HTTP.

    Examples:

        dockertree stop-proxy

        dockertree stop  # alias for stop-proxy
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        caddy_manager = CaddyManager()
        success = caddy_manager.stop_global_caddy()
        if not success:
            if json:
                JSONOutput.print_error("Failed to stop global Caddy container")
            else:
                error_exit("Failed to stop global Caddy container")
        else:
            if json:
                JSONOutput.print_success("Global Caddy proxy stopped successfully")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error stopping global Caddy: {e}")
        else:
            error_exit(f"Error stopping global Caddy: {e}")


@cli.command('start')
@add_verbose_option
def start():
    """Start the global Caddy proxy container (alias for start-proxy).

    Examples:

        dockertree start
    """
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
    """Stop the global Caddy proxy container (alias for stop-proxy).

    Examples:

        dockertree stop
    """
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
@add_json_option
@add_verbose_option
def create(branch_name: str, json: bool):
    """Create a new worktree for the specified branch.

    Creates a Git worktree in the worktrees directory and sets up the
    necessary Docker Compose override file for isolated development.

    Examples:

        dockertree create feature-auth

        dockertree create bugfix-123
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        
        # In JSON mode, skip interactive prompts
        success, result_data = worktree_manager.create_worktree(branch_name, interactive=not json)
        
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to create worktree for {branch_name}")
            else:
                error_exit(f"Failed to create worktree for {branch_name}")
        else:
            if json:
                worktree_path = worktree_manager.git_manager.find_worktree_path(branch_name)
                status = result_data.get('data', {}).get('status', 'created')
                
                JSONOutput.print_success(f"Worktree ready for {branch_name}", {
                    "branch_name": branch_name,
                    "worktree_path": str(worktree_path) if worktree_path else None,
                    "status": status
                })
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error creating worktree: {e}")
        else:
            error_exit(f"Error creating worktree: {e}")


@cli.command()
@click.argument('branch_name')
@click.option('-d', '--detach', is_flag=True, default=True, help='Run containers in detached mode (default: True)')
@click.option('--profile', help='Docker Compose profile to use (e.g., worker)')
@add_json_option
@add_verbose_option
def up(branch_name: str, detach: bool, profile: Optional[str], json: bool):
    """Start the worktree environment for the specified branch.

    Starts all Docker containers for the worktree environment, including
    database, Redis, and application containers. The environment will be
    accessible via a unique URL.

    Use --profile to start only services with a specific profile. For example,
    if your compose file defines services with profiles: ["worker"], you can
    start only those services with --profile worker.

    Examples:

        dockertree feature-auth up

        dockertree feature-auth up -d

        dockertree feature-auth up -d --profile worker
    """
    if not detach:
        if json:
            JSONOutput.print_error("Usage: dockertree <worktree_name> up -d")
        else:
            error_exit("Usage: dockertree <worktree_name> up -d")
    
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        success = worktree_manager.start_worktree(branch_name, profile=profile)
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to start worktree environment for {branch_name}")
            else:
                error_exit(f"Failed to start worktree environment for {branch_name}")
        else:
            if json:
                access_url = worktree_manager.env_manager.get_access_url(branch_name)
                JSONOutput.print_success(f"Worktree environment started for {branch_name}", {
                    "branch_name": branch_name,
                    "url": access_url,
                    "profile": profile
                })
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error starting worktree: {e}")
        else:
            error_exit(f"Error starting worktree: {e}")


@cli.command()
@click.argument('branch_name')
@add_json_option
@add_verbose_option
def down(branch_name: str, json: bool):
    """Stop the worktree environment for the specified branch.

    Stops all Docker containers for the worktree environment. Data in
    volumes is preserved and can be restored when starting again.

    Examples:

        dockertree feature-auth down
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        worktree_manager = WorktreeManager()
        success = worktree_manager.stop_worktree(branch_name)
        if json:
            if success:
                JSONOutput.print_success(f"Worktree environment stopped for {branch_name}", {
                    "branch_name": branch_name
                })
            else:
                JSONOutput.print_error(f"Failed to stop worktree environment for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error stopping worktree: {e}")
        else:
            error_exit(f"Error stopping worktree: {e}")


@cli.command()
@click.argument('branch_name')
@click.option('--force', is_flag=True, help='Force deletion even with unmerged changes (skip confirmation)')
@add_json_option
@add_verbose_option
def delete(branch_name: str, force: bool, json: bool):
    """Delete worktree and Git branch completely.

    Permanently removes the worktree, all associated containers, volumes,
    and the Git branch. This action cannot be undone.

    Supports wildcard patterns for batch deletion:
    - test-* matches all branches starting with "test-"
    - feature-? matches single character wildcards
    - bugfix-[abc] matches character classes

    Examples:

        dockertree delete feature-auth

        dockertree delete feature-* --force
        dockertree delete test-?
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
                if json:
                    JSONOutput.print_error(f"Failed to remove worktrees matching pattern: {branch_name}")
                else:
                    error_exit(f"Failed to remove worktrees matching pattern: {branch_name}")
            else:
                if json:
                    JSONOutput.print_success(f"Successfully removed worktrees matching pattern: {branch_name}")
        else:
            # Use single branch removal
            success = worktree_manager.remove_worktree(branch_name, force)
            if not success:
                if json:
                    JSONOutput.print_error(f"Failed to remove worktree for {branch_name}")
                else:
                    error_exit(f"Failed to remove worktree for {branch_name}")
            else:
                if json:
                    JSONOutput.print_success(f"Successfully removed worktree for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error removing worktree: {e}")
        else:
            log_error(f"Error removing worktree '{branch_name}': {e}")
            log_info("Safety check: Only the specified worktree should be affected.")
            error_exit(f"Operation failed for '{branch_name}'")




@cli.command()
@click.option('--force', is_flag=True, help='Force deletion without confirmation')
@add_verbose_option
def delete_all(force: bool):
    """Delete all worktrees, containers, volumes, and Git branches.

    Permanently removes all worktrees and their associated resources.
    This is a destructive operation that cannot be undone.

    Examples:

        dockertree delete-all

        dockertree delete-all --force
    """
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
@click.option('--force', is_flag=True, help='Force removal even with unmerged changes (skip confirmation)')
@add_json_option
@add_verbose_option
def remove(branch_name: str, force: bool, json: bool):
    """Remove worktree and containers/volumes but keep the Git branch.

    Removes the worktree and all associated Docker resources (containers
    and volumes), but preserves the Git branch for future use.

    Supports wildcard patterns for batch removal:
    - test-* matches all branches starting with "test-"
    - feature-? matches single character wildcards
    - bugfix-[abc] matches character classes

    Examples:

        dockertree remove feature-auth

        dockertree remove feature-* --force
        dockertree remove test-?
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
                if json:
                    JSONOutput.print_error(f"Failed to remove worktrees matching pattern: {branch_name}")
                else:
                    error_exit(f"Failed to remove worktrees matching pattern: {branch_name}")
            else:
                if json:
                    JSONOutput.print_success(f"Successfully removed worktrees matching pattern: {branch_name}")
        else:
            # Use single branch removal
            success = worktree_manager.remove_worktree(branch_name, force, delete_branch=False)
            if not success:
                if json:
                    JSONOutput.print_error(f"Failed to remove worktree for {branch_name}")
                else:
                    error_exit(f"Failed to remove worktree for {branch_name}")
            else:
                if json:
                    JSONOutput.print_success(f"Successfully removed worktree for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error removing worktree: {e}")
        else:
            log_error(f"Error removing worktree '{branch_name}': {e}")
            log_info("Safety check: Only the specified worktree should be affected.")
            error_exit(f"Operation failed for '{branch_name}'")




@cli.command()
@click.option('--force', is_flag=True, help='Force removal without confirmation')
@add_verbose_option
def remove_all(force: bool):
    """Remove all worktrees and containers/volumes but keep Git branches.

    Removes all worktrees and their Docker resources, but preserves all
    Git branches for future use.

    Examples:

        dockertree remove-all

        dockertree remove-all --force
    """
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
@add_json_option
@add_verbose_option
def list(json: bool):
    """List all active worktrees.

    Displays information about all worktrees including branch names,
    status, and access URLs.

    Examples:

        dockertree list

        dockertree list --json
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        utility_manager = UtilityManager()
        if json:
            worktrees = utility_manager.list_worktrees_json()
            JSONOutput.print_json(worktrees)
        else:
            utility_manager.list_worktrees()
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error listing worktrees: {e}")
        else:
            error_exit(f"Error listing worktrees: {e}")


@cli.command()
@add_json_option
@add_verbose_option
def prune(json: bool):
    """Remove prunable worktree references.

    Cleans up stale Git worktree references that are no longer valid.
    This is useful after manually removing worktree directories.

    Examples:

        dockertree prune

        dockertree prune --json
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        utility_manager = UtilityManager()
        if json:
            pruned_count = utility_manager.prune_worktrees_json()
            JSONOutput.print_success(f"Pruned {pruned_count} worktree(s)", {
                "pruned_count": pruned_count
            })
        else:
            utility_manager.prune_worktrees()
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error pruning worktrees: {e}")
        else:
            error_exit(f"Error pruning worktrees: {e}")


@cli.group()
@add_verbose_option
def volumes():
    """Manage Docker volumes for worktrees.

    Provides commands for listing, backing up, restoring, and cleaning
    Docker volumes associated with worktree environments.

    Examples:

        dockertree volumes list

        dockertree volumes backup feature-auth
    """
    pass


@volumes.command('list')
@add_json_option
@add_verbose_option
def volumes_list(json: bool):
    """List all worktree volumes.

    Displays all Docker volumes associated with worktree environments,
    including volume names and their associated branch names.

    Examples:

        dockertree volumes list

        dockertree volumes list --json
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        if json:
            volumes = volume_manager.list_volumes_json()
            JSONOutput.print_json(volumes)
        else:
            volume_manager.list_volumes()
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error listing volumes: {e}")
        else:
            error_exit(f"Error listing volumes: {e}")


@volumes.command('size')
@add_json_option
@add_verbose_option
def volumes_size(json: bool):
    """Show sizes of all worktree volumes.

    Displays the disk space usage for each worktree volume, helping
    identify which volumes are consuming the most space.

    Examples:

        dockertree volumes size

        dockertree volumes size --json
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        if json:
            sizes = volume_manager.get_volume_sizes_json()
            JSONOutput.print_json(sizes)
        else:
            volume_manager.show_volume_sizes()
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error showing volume sizes: {e}")
        else:
            error_exit(f"Error showing volume sizes: {e}")


@volumes.command('backup')
@click.argument('branch_name')
@click.option('--backup-dir', type=click.Path(), help='Directory to save backup (default: ./backups)')
@add_json_option
@add_verbose_option
def volumes_backup(branch_name: str, backup_dir: Optional[str], json: bool):
    """Backup worktree volumes to a tar archive.

    Creates a backup of all volumes associated with the specified worktree.
    The backup can be restored later using the restore command.

    Examples:

        dockertree volumes backup feature-auth

        dockertree volumes backup feature-auth --backup-dir /path/to/backups
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        backup_path = Path(backup_dir) if backup_dir else None
        success = volume_manager.backup_volumes(branch_name, backup_path)
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to backup volumes for {branch_name}")
            else:
                error_exit(f"Failed to backup volumes for {branch_name}")
        else:
            if json:
                JSONOutput.print_success(f"Successfully backed up volumes for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error backing up volumes: {e}")
        else:
            error_exit(f"Error backing up volumes: {e}")


@volumes.command('restore')
@click.argument('branch_name')
@click.argument('backup_file', type=click.Path(exists=True))
@add_json_option
@add_verbose_option
def volumes_restore(branch_name: str, backup_file: str, json: bool):
    """Restore worktree volumes from a backup archive.

    Restores volumes for the specified worktree from a previously created
    backup. The worktree must exist before restoring volumes.

    Examples:

        dockertree volumes restore feature-auth ./backups/feature-auth.tar.gz
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        success = volume_manager.restore_volumes(branch_name, Path(backup_file))
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to restore volumes for {branch_name}")
            else:
                error_exit(f"Failed to restore volumes for {branch_name}")
        else:
            if json:
                JSONOutput.print_success(f"Successfully restored volumes for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error restoring volumes: {e}")
        else:
            error_exit(f"Error restoring volumes: {e}")


@volumes.command('clean')
@click.argument('branch_name')
@add_json_option
@add_verbose_option
def volumes_clean(branch_name: str, json: bool):
    """Clean up (remove) worktree volumes.

    Permanently removes all volumes associated with the specified worktree.
    This action cannot be undone. Make sure to backup volumes first if needed.

    Examples:

        dockertree volumes clean feature-auth
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        volume_manager = VolumeManager()
        success = volume_manager.clean_volumes(branch_name)
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to clean volumes for {branch_name}")
            else:
                error_exit(f"Failed to clean volumes for {branch_name}")
        else:
            if json:
                JSONOutput.print_success(f"Successfully cleaned volumes for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error cleaning volumes: {e}")
        else:
            error_exit(f"Error cleaning volumes: {e}")


@cli.group()
@add_verbose_option
def droplet():
    """Manage DigitalOcean droplets.

    Provides commands for creating, listing, and managing DigitalOcean
    droplets. Requires DIGITALOCEAN_API_TOKEN environment variable or
    --api-token option.

    Examples:

        dockertree droplet list

        dockertree droplet create my-droplet
    """
    pass


@droplet.command('create')
@click.argument('branch_name', required=False)
@click.option('--region', help='Droplet region (default: nyc1 or from DIGITALOCEAN_REGION env var)')
@click.option('--size', help='Droplet size slug (e.g., s-1vcpu-1gb, s-2vcpu-4gb). Use "dockertree droplet sizes" to list all available sizes. Default: s-1vcpu-1gb or from DIGITALOCEAN_SIZE env var')
@click.option('--image', help='Droplet image (default: ubuntu-22-04-x64 or from DIGITALOCEAN_IMAGE env var)')
@click.option('--ssh-keys', type=str, help='SSH key names (comma-separated, e.g., anders,peter)')
@click.option('--tags', multiple=True, help='Tags for the droplet (can be specified multiple times)')
@click.option('--wait', is_flag=True, default=False, help='Wait for droplet to be ready before returning')
@click.option('--api-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--create-only', is_flag=True, default=False, help='Only create droplet, do not push environment (default: creates droplet and pushes environment)')
@click.option('--scp-target', help='SCP target in format username@server:path (optional, defaults to root@<droplet-ip>:/root)')
@click.option('--output-dir', type=click.Path(), default='./packages', help='Temporary package location (default: ./packages)')
@click.option('--keep-package', is_flag=True, default=False, help='Keep package file after successful push (default: delete after push)')
@click.option('--no-auto-import', is_flag=True, default=False, help='Skip automatic import and start on remote server after push (default: auto-import is enabled)')
@click.option('--prepare-server', is_flag=True, default=False, help='Check remote server for required dependencies before push')
@click.option('--domain', help='Domain override for remote import (subdomain.domain.tld). DNS A record will be automatically created if it does not exist.')
@click.option('--ip', help='IP override for remote import (HTTP-only, no TLS)')
@click.option('--dns-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--skip-dns-check', is_flag=True, default=False, help='Skip DNS validation and management')
@click.option('--resume', is_flag=True, default=False, help='Resume a failed push operation by detecting what\'s already completed')
@click.option('--code-only', is_flag=True, default=False, help='Push code-only update to pre-existing server')
@click.option('--build', is_flag=True, default=False, help='Rebuild Docker images after code update (only works with --code-only)')
@click.option('--containers', help='Comma-separated list of worktree.container patterns to push only specific containers and their volumes (e.g., feature-auth.db,feature-auth.redis)')
@click.option('--exclude-deps', help='Comma-separated list of service names to exclude from dependency resolution (e.g., db,redis). Useful when deploying workers that connect to remote services.')
@click.option('--vpc-uuid', help='VPC UUID for the droplet. If not provided, will use the default VPC for the region.')
@click.option('--central-droplet-name', help='Name of central droplet to reuse VPC UUID from (for worker deployments)')
@add_json_option
@add_verbose_option
def droplet_create(branch_name: Optional[str], region: Optional[str], size: Optional[str], image: Optional[str],
                    ssh_keys: Optional[str], tags: tuple, wait: bool, api_token: Optional[str], json: bool,
                    create_only: bool, scp_target: Optional[str],
                    output_dir: str, keep_package: bool, no_auto_import: bool, prepare_server: bool,
                    domain: str, ip: str, dns_token: str, skip_dns_check: bool, resume: bool,
                    code_only: bool, build: bool, containers: Optional[str], exclude_deps: Optional[str],
                    vpc_uuid: Optional[str], central_droplet_name: Optional[str]):
    """Create a new DigitalOcean droplet and optionally push dockertree environment.

    By default, creates a droplet and automatically pushes the dockertree environment
    to it. Use --create-only to only create the droplet without pushing.

    The droplet name is auto-detected:
    - If --domain is provided, uses the subdomain (e.g., app.example.com -> app)
    - Otherwise, uses the branch/worktree name (auto-detected from current directory if not provided)

    When pushing (default behavior), the droplet is always waited for until ready
    before pushing. The scp_target is optional and defaults to root@<droplet-ip>:/root.

    Examples:

        # Create droplet and push environment (auto-detects branch name)
        dockertree droplet create

        # Create droplet with explicit branch name
        dockertree droplet create test

        # Create droplet only, do not push
        dockertree droplet create test --create-only

        # Create droplet with domain (uses subdomain as droplet name)
        dockertree droplet create --domain app.example.com

        # Create droplet with custom configuration and push
        dockertree droplet create test --region sfo3 --size s-2vcpu-4gb
    """
    start_time = time.time()
    try:
        import subprocess
        
        # Auto-detect branch name if not provided
        if not branch_name:
            if not json:
                log_info("Branch name not provided, attempting auto-detection...")
            
            # Try to detect execution context (worktree or git root)
            worktree_path, detected_branch, is_worktree = detect_execution_context()
            
            if is_worktree and detected_branch:
                branch_name = detected_branch
            else:
                # Fallback: try git branch --show-current
                try:
                    from .config.settings import get_project_root
                    project_root = get_project_root()
                    result = subprocess.run(
                        ["git", "branch", "--show-current"],
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=project_root
                    )
                    branch = result.stdout.strip()
                    if branch:
                        branch_name = branch
                except (subprocess.CalledProcessError, FileNotFoundError):
                    pass
                
                # Fallback: extract from directory name
                if not branch_name:
                    current_path = Path.cwd()
                    if "worktrees" in str(current_path):
                        branch = get_worktree_branch_name(current_path)
                        if branch:
                            branch_name = branch
            
            if not branch_name:
                if json:
                    JSONOutput.print_error("Could not detect branch name. Please specify branch_name as argument or use --domain to auto-detect from subdomain.")
                else:
                    error_exit("Could not detect branch name. Please specify branch_name as argument or use --domain to auto-detect from subdomain.")
                return
            
            if not json:
                log_info(f"Auto-detected branch: {branch_name}")
        
        # Determine droplet name: use subdomain from domain if provided, otherwise use branch_name
        if domain:
            try:
                subdomain, base_domain = parse_domain(domain)
                # Check if this is a root domain (subdomain == base domain's first part)
                # For example, "example.com" would parse as subdomain="example", base="com"
                # We want to detect if there's actually a subdomain vs root domain
                domain_parts = domain.split('.')
                if len(domain_parts) == 2:
                    # This is a root domain (e.g., example.com), no subdomain
                    # Fall back to branch_name
                    droplet_name = branch_name
                    if not json:
                        log_info(f"Domain '{domain}' is a root domain (no subdomain), using branch name '{branch_name}' as droplet name")
                else:
                    # This has a subdomain, use it
                    droplet_name = subdomain
                    if not json:
                        log_info(f"Using subdomain '{subdomain}' from domain '{domain}' as droplet name")
            except ValueError:
                # If domain parsing fails, fall back to branch_name
                droplet_name = branch_name
                if not json:
                    log_warning(f"Could not parse domain '{domain}', using branch name '{branch_name}' as droplet name")
        else:
            droplet_name = branch_name
            if not json:
                log_info(f"Using branch name '{branch_name}' as droplet name")
        
        # Get defaults for region, size, image if not provided
        from .core.droplet_manager import DropletManager
        defaults = DropletManager.get_droplet_defaults()
        resolved_region = region or defaults.get('region', 'nyc1')
        resolved_size = size or defaults.get('size', 's-1vcpu-1gb')
        resolved_image = image or defaults.get('image', 'ubuntu-22-04-x64')
        
        # Add initial setup feedback
        if not json:
            log_info("Starting droplet creation process...")
            log_info("Droplet configuration:")
            log_info(f"  Name: {droplet_name}")
            log_info(f"  Region: {resolved_region}")
            log_info(f"  Size: {resolved_size}")
            log_info(f"  Image: {resolved_image}")
            if ssh_keys:
                log_info(f"  SSH Keys: {ssh_keys}")
            if tags:
                log_info(f"  Tags: {', '.join(tags)}")
            if containers:
                log_info(f"  Containers: {containers}")
            if exclude_deps:
                log_info(f"  Exclude Dependencies: {exclude_deps}")
        
        check_prerequisites_no_git()  # Don't require git for droplet operations
        droplet_commands = DropletCommands()
        # Parse comma-separated SSH key names into a list
        ssh_keys_list = [k.strip() for k in ssh_keys.split(',')] if ssh_keys else None
        tags_list = list(tags) if tags else None
        
        # Resolve VPC UUID from central droplet if specified
        resolved_vpc_uuid = vpc_uuid
        central_droplet = None  # Initialize outside conditional block
        if central_droplet_name and not vpc_uuid:
            if not json:
                log_info("Resolving VPC configuration...")
                log_info(f"Looking up VPC UUID from central droplet: {central_droplet_name}")
            from .core.droplet_manager import DropletManager
            token = DropletManager.resolve_droplet_token(api_token or dns_token)
            if token:
                provider = DropletManager.create_provider('digitalocean', token)
                if provider:
                    droplets = provider.list_droplets()
                    for d in droplets:
                        if d.name == central_droplet_name:
                            central_droplet = d
                            break
                    
                    if central_droplet and central_droplet.vpc_uuid:
                        resolved_vpc_uuid = central_droplet.vpc_uuid
                        if not json:
                            log_info(f"Found central droplet '{central_droplet_name}' in region {central_droplet.region}")
                            if central_droplet.region != resolved_region:
                                log_warning("⚠️  Region mismatch detected!")
                                log_warning(f"   Central droplet '{central_droplet_name}' is in region: {central_droplet.region}")
                                log_warning(f"   Worker droplet will be created in region: {resolved_region}")
                                log_warning("   VPCs are region-specific. Ensure both droplets are in the same region.")
                            log_info(f"Using VPC UUID from central droplet: {resolved_vpc_uuid}")
                            if central_droplet.private_ip_address:
                                log_info(f"Central droplet private IP: {central_droplet.private_ip_address}")
                    elif not json:
                        log_warning(f"Central droplet '{central_droplet_name}' not found or has no VPC UUID, using default VPC")
        elif not json and not vpc_uuid:
            log_info("Resolving VPC configuration...")
            log_info(f"Using default VPC for region {resolved_region}")
        
        # Store central droplet info for later use in package export (for worker deployments)
        central_droplet_info = central_droplet if central_droplet_name and central_droplet else None
        
        # Create droplet (always wait when pushing)
        wait_for_push = not create_only
        success = droplet_commands.create_droplet(
            name=droplet_name,
            region=resolved_region,
            size=resolved_size,
            image=resolved_image,
            ssh_keys=ssh_keys_list,
            tags=tags_list,
            wait=wait or wait_for_push,  # Always wait if pushing
            api_token=api_token,
            json=json,
            containers=containers,
            vpc_uuid=resolved_vpc_uuid
        )
        if not success:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error(f"Failed to create droplet: {droplet_name}")
            else:
                error_exit(f"Failed to create droplet: {droplet_name}")
            return
        
        # If create_only, we're done
        if create_only:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            return
        
        # Otherwise, push the environment to the newly created droplet
        if not json:
            log_info("")
            log_info("Droplet created successfully. Preparing to push environment...")
            log_info(f"Will push worktree '{branch_name}' to {droplet_name}")
            if containers:
                log_info(f"Selected containers: {containers}")
            if exclude_deps:
                exclude_deps_preview = [d.strip() for d in exclude_deps.split(',')]
                log_info(f"Excluding dependencies: {', '.join(exclude_deps_preview)}")
            log_info("")
        
        # Get droplet IP address for push
        from .core.droplet_manager import DropletManager
        token = DropletManager.resolve_droplet_token(api_token or dns_token)
        if not token:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("Digital Ocean API token not found for push operation")
            else:
                error_exit("Digital Ocean API token not found for push operation")
            return
        
        provider = DropletManager.create_provider('digitalocean', token)
        if not provider:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("Failed to create droplet provider for push")
            else:
                error_exit("Failed to create droplet provider for push")
            return
        
        # Find droplet by name to get IP
        droplets = provider.list_droplets()
        droplet = None
        for d in droplets:
            if d.name == droplet_name:
                droplet = d
                break
        
        if not droplet or not droplet.ip_address:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error(f"Droplet {droplet_name} created but IP address not available")
            else:
                error_exit(f"Droplet {droplet_name} created but IP address not available")
            return
        
        # Prepare SCP target
        if scp_target:
            # Parse provided scp_target to extract username and path (server will be replaced)
            push_manager = PushManager()
            if not push_manager._validate_scp_target(scp_target):
                elapsed_time = time.time() - start_time
                if not json:
                    print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
                if json:
                    JSONOutput.print_error(f"Invalid SCP target format: {scp_target}")
                else:
                    error_exit(f"Invalid SCP target format: {scp_target}")
                return
            username, _, remote_path = push_manager._parse_scp_target(scp_target)
        else:
            # Use defaults for new droplets
            username = "root"
            remote_path = "/root"
        
        final_scp_target = f"{username}@{droplet.ip_address}:{remote_path}"
        
        # Now push using PushManager
        check_setup_or_prompt()
        check_prerequisites()
        
        # Validate mutual exclusivity
        if domain and ip:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("Options --domain and --ip are mutually exclusive")
            else:
                error_exit("Options --domain and --ip are mutually exclusive")
            return
        
        # Validate --build is only used with --code-only
        if build and not code_only:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("--build can only be used with --code-only")
            else:
                error_exit("--build can only be used with --code-only")
            return
        
        push_manager = PushManager()
        # ssh_keys_list is already a list from line 1034, so we can use it directly
        droplet_ssh_keys_list = ssh_keys_list if ssh_keys_list else None
        
        # Parse exclude_deps from comma-separated string to list
        exclude_deps_list = [d.strip() for d in exclude_deps.split(',')] if exclude_deps else None
        
        try:
            success = push_manager.push_package(
                branch_name=branch_name,
                scp_target=final_scp_target,
                output_dir=Path(output_dir),
                keep_package=keep_package,
                auto_import=not no_auto_import,  # Invert: no_auto_import=True means auto_import=False
                containers=containers,
                exclude_deps=exclude_deps_list,
                domain=domain,
                ip=ip,
                prepare_server=prepare_server,
                dns_token=dns_token or api_token,
                skip_dns_check=skip_dns_check,
                create_droplet=False,  # Already created
                droplet_name=None,
                droplet_region=None,
                droplet_size=None,
                droplet_image=None,
                droplet_ssh_keys=droplet_ssh_keys_list,
                resume=resume,
                code_only=code_only,
                build=build,
                droplet_info=droplet,
                central_droplet_info=central_droplet_info
            )
        except click.exceptions.ClickException as e:
            # Catch Click-specific exceptions
            import traceback
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error(f"Click error during push: {e}")
            else:
                error_exit(f"Click error during push: {e}\n{traceback.format_exc()}")
            return
        except Exception as e:
            import traceback
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error(f"Error during push: {e}")
            else:
                error_exit(f"Error during push: {e}\n{traceback.format_exc()}")
            return
        
        elapsed_time = time.time() - start_time
        if not success:
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error(f"Failed to push package to droplet")
            else:
                error_exit(f"Failed to push package to droplet")
        else:
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_success(f"Droplet created and package pushed successfully")
    except Exception as e:
        elapsed_time = time.time() - start_time
        if not json:
            print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
        if json:
            JSONOutput.print_error(f"Error creating droplet: {e}")
        else:
            error_exit(f"Error creating droplet: {e}")


@droplet.command('list')
@click.option('--api-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--as-json', '--json', 'output_json', is_flag=True, default=False, help='Output results as JSON format')
@click.option('--as-csv', 'output_csv', is_flag=True, default=False, help='Output results as CSV format')
@add_verbose_option
def droplet_list(api_token: Optional[str], output_json: bool, output_csv: bool):
    """List all DigitalOcean droplets.

    Displays all droplets in a formatted table by default. The list includes
    droplet IDs, names, regions, sizes, status, and associated DNS domains.

    Examples:

        dockertree droplet list

        dockertree droplet list --as-json
        dockertree droplet list --as-csv
    """
    try:
        check_prerequisites_no_git()  # Don't require git for droplet operations
        droplet_commands = DropletCommands()
        success = droplet_commands.list_droplets(api_token=api_token, json=output_json, csv=output_csv)
        if not success:
            if output_json or output_csv:
                JSONOutput.print_error("Failed to list droplets")
            else:
                error_exit("Failed to list droplets")
    except Exception as e:
        if output_json or output_csv:
            JSONOutput.print_error(f"Error listing droplets: {e}")
        else:
            error_exit(f"Error listing droplets: {e}")


@droplet.command('sizes')
@click.option('--api-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--as-json', '--json', 'output_json', is_flag=True, default=False, help='Output results as JSON format')
@click.option('--as-csv', 'output_csv', is_flag=True, default=False, help='Output results as CSV format')
@add_verbose_option
def droplet_sizes(api_token: Optional[str], output_json: bool, output_csv: bool):
    """List available DigitalOcean droplet sizes.

    Displays all available droplet sizes with their specifications including
    memory, vCPUs, disk space, and pricing information.

    Examples:

        dockertree droplet sizes

        dockertree droplet sizes --as-json
        dockertree droplet sizes --as-csv
    """
    try:
        check_prerequisites_no_git()  # Don't require git for droplet operations
        droplet_commands = DropletCommands()
        success = droplet_commands.list_sizes(api_token=api_token, json=output_json, csv=output_csv)
        if not success:
            if output_json or output_csv:
                JSONOutput.print_error("Failed to list droplet sizes")
            else:
                error_exit("Failed to list droplet sizes")
    except Exception as e:
        if output_json or output_csv:
            JSONOutput.print_error(f"Error listing droplet sizes: {e}")
        else:
            error_exit(f"Error listing droplet sizes: {e}")


@droplet.command('destroy')
@click.argument('droplet_ids', type=str)
@click.option('--force', is_flag=True, default=False, help='Skip confirmation prompts')
@click.option('--only-droplet', is_flag=True, default=False, help='Only destroy droplet, skip DNS deletion')
@click.option('--only-domain', is_flag=True, default=False, help='Only destroy DNS records, skip droplet deletion')
@click.option('--domain', help='Domain name for DNS deletion (optional, auto-detects if not provided)')
@click.option('--api-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--dns-token', help='DNS API token (if different from droplet token)')
@add_json_option
@add_verbose_option
def droplet_destroy(droplet_ids: str, force: bool, only_droplet: bool, only_domain: bool,
                    domain: Optional[str], api_token: Optional[str], dns_token: Optional[str], json: bool):
    """Destroy DigitalOcean droplet(s) and/or associated DNS records.

    Accepts a single droplet ID or comma-separated list of IDs (e.g., 123,456,789).
    By default, destroys only the droplet(s). Use --only-domain to destroy
    DNS records only, or omit flags to destroy both droplet and DNS records.

    Requires typing the droplet name to confirm (unless --force). When
    deleting DNS records, requires typing the full domain name to confirm
    (unless --force).

    Examples:

        dockertree droplet destroy 123456789

        dockertree droplet destroy 123,456,789

        dockertree droplet destroy 123456789 --force
        dockertree droplet destroy 123,456,789 --force
        dockertree droplet destroy 123456789 --only-domain
    """
    try:
        # Validate flags
        if only_droplet and only_domain:
            if json:
                JSONOutput.print_error("Cannot specify both --only-droplet and --only-domain")
            else:
                error_exit("Cannot specify both --only-droplet and --only-domain")
            return
        
        # Parse comma-separated droplet IDs
        try:
            droplet_id_list = [int(id_str.strip()) for id_str in droplet_ids.split(',') if id_str.strip()]
        except ValueError as e:
            if json:
                JSONOutput.print_error(f"Invalid droplet ID format. All IDs must be integers. Got: {droplet_ids}")
            else:
                error_exit(f"Invalid droplet ID format. All IDs must be integers. Got: {droplet_ids}")
            return
        
        if not droplet_id_list:
            if json:
                JSONOutput.print_error("No valid droplet IDs provided")
            else:
                error_exit("No valid droplet IDs provided")
            return
        
        check_prerequisites_no_git()  # Don't require git for droplet operations
        droplet_commands = DropletCommands()
        
        # Track results for each droplet
        results = []
        success_count = 0
        failure_count = 0
        total = len(droplet_id_list)
        
        # Process each droplet ID
        # When processing multiple droplets, suppress individual JSON output
        # and aggregate results instead
        suppress_json = json and total > 1
        
        for droplet_id in droplet_id_list:
            try:
                success = droplet_commands.destroy_droplet(
                    droplet_id=droplet_id,
                    force=force,
                    api_token=api_token,
                    json=json if not suppress_json else False,  # Suppress JSON for individual calls when aggregating
                    only_droplet=only_droplet,
                    only_domain=only_domain,
                    domain=domain,
                    dns_token=dns_token
                )
                
                if success:
                    success_count += 1
                    results.append({"droplet_id": droplet_id, "success": True})
                else:
                    failure_count += 1
                    results.append({"droplet_id": droplet_id, "success": False, "error": "Failed to destroy droplet"})
            except Exception as e:
                failure_count += 1
                results.append({"droplet_id": droplet_id, "success": False, "error": str(e)})
                # Continue with next droplet even if this one failed
                if not json:
                    log_error(f"Error destroying droplet {droplet_id}: {e}")
        
        # Output summary
        if json:
            if suppress_json:
                # Aggregate JSON output for multiple droplets
                result = {
                    "success": failure_count == 0,
                    "total": total,
                    "succeeded": success_count,
                    "failed": failure_count,
                    "results": results
                }
                JSONOutput.print_json(result)
            # For single droplet, JSON was already output by destroy_droplet
        
        # Non-JSON summary for multiple droplets
        if not json and total > 1:
            if success_count == total:
                log_success(f"Successfully destroyed {success_count} of {total} droplet(s)")
            elif success_count > 0:
                log_error(f"Destroyed {success_count} of {total} droplet(s) successfully ({failure_count} failed)")
            else:
                log_error(f"Failed to destroy all {total} droplet(s)")
        
        # Exit with error code if any failures occurred
        if failure_count > 0:
            if json and suppress_json:
                # JSON output already printed, just exit with error code
                sys.exit(1)
            elif not json:
                error_exit(f"Failed to destroy {failure_count} of {total} droplet(s)")
        
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error destroying droplet(s): {e}")
        else:
            error_exit(f"Error destroying droplet(s): {e}")


@droplet.command('info')
@click.argument('droplet_id', type=int)
@click.option('--api-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@add_json_option
@add_verbose_option
def droplet_info(droplet_id: int, api_token: Optional[str], json: bool):
    """Get detailed information about a droplet.

    Displays comprehensive information about the specified droplet including
    status, region, size, IP addresses, and associated DNS domains.

    Examples:

        dockertree droplet info 123456789

        dockertree droplet info 123456789 --json
    """
    try:
        check_prerequisites_no_git()  # Don't require git for droplet operations
        droplet_commands = DropletCommands()
        success = droplet_commands.get_droplet_info(
            droplet_id=droplet_id,
            api_token=api_token,
            json=json
        )
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to get droplet info: {droplet_id}")
            else:
                error_exit(f"Failed to get droplet info: {droplet_id}")
    except ValueError:
        if json:
            JSONOutput.print_error(f"Invalid droplet ID: {droplet_id}. Must be an integer.")
        else:
            error_exit(f"Invalid droplet ID: {droplet_id}. Must be an integer.")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error getting droplet info: {e}")
        else:
            error_exit(f"Error getting droplet info: {e}")


@cli.group()
@add_verbose_option
def domains():
    """Manage DNS domains and DNS A records.
    
    Provides commands for creating, listing, deleting, and viewing DNS A records
    via Digital Ocean DNS API. Supports managing subdomains and root domain records.
    """
    pass


@domains.command('create')
@click.argument('subdomain')
@click.argument('domain')
@click.argument('ip')
@click.option('--dns-token', help='DNS API token (or use DIGITALOCEAN_API_TOKEN env var)')
@add_json_option
@add_verbose_option
def domains_create(subdomain: str, domain: str, ip: str, dns_token: Optional[str], json: bool):
    """Create a new DNS A record.

    Creates a DNS A record pointing the specified subdomain to an IP address.
    Use '@' as the subdomain to create a record for the root domain.

    Examples:

        dockertree domains create app example.com 192.0.2.1

        dockertree domains create @ example.com 192.0.2.1
        dockertree domains create api staging.example.com 10.0.0.1
    """
    try:
        check_prerequisites_no_git()  # Don't require git for domain operations
        domain_commands = DomainCommands()
        success = domain_commands.create_domain(
            subdomain=subdomain,
            domain=domain,
            ip=ip,
            dns_token=dns_token,
            json=json
        )
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to create DNS A record: {subdomain}.{domain}")
            else:
                error_exit(f"Failed to create DNS A record: {subdomain}.{domain}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error creating DNS A record: {e}")
        else:
            error_exit(f"Error creating DNS A record: {e}")


@domains.command('list')
@click.option('--domain', help='Base domain to filter by (optional, lists all domains if not provided)')
@click.option('--dns-token', help='DNS API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--as-json', '--json', 'output_json', is_flag=True, default=False, help='Output results as JSON format')
@click.option('--as-csv', 'output_csv', is_flag=True, default=False, help='Output results as CSV format')
@add_verbose_option
def domains_list(domain: Optional[str], dns_token: Optional[str], output_json: bool, output_csv: bool):
    """List all DNS A records.

    Displays DNS A records in a formatted table by default. Shows subdomain,
    domain, IP address, and TTL for each record.

    Examples:

        dockertree domains list

        dockertree domains list --domain example.com
        dockertree domains list --as-json

        dockertree domains list --as-csv
    """
    try:
        check_prerequisites_no_git()  # Don't require git for domain operations
        domain_commands = DomainCommands()
        success = domain_commands.list_domains(
            domain=domain,
            dns_token=dns_token,
            json=output_json,
            csv=output_csv
        )
        if not success:
            if output_json or output_csv:
                JSONOutput.print_error("Failed to list DNS A records")
            else:
                error_exit("Failed to list DNS A records")
    except Exception as e:
        if output_json or output_csv:
            JSONOutput.print_error(f"Error listing DNS A records: {e}")
        else:
            error_exit(f"Error listing DNS A records: {e}")


@domains.command('delete')
@click.argument('full_domain')
@click.option('--force', is_flag=True, default=False, help='Skip confirmation prompt')
@click.option('--dns-token', help='DNS API token (or use DIGITALOCEAN_API_TOKEN env var)')
@add_json_option
@add_verbose_option
def domains_delete(full_domain: str, force: bool, dns_token: Optional[str], json: bool):
    """Delete a DNS A record.

    Deletes a DNS A record for the specified domain. Provide the full domain
    (e.g., 'app.example.com' for a subdomain or 'example.com' for root domain).

    Requires typing the full domain name to confirm (unless --force).

    Examples:

        dockertree domains delete app.example.com

        dockertree domains delete example.com

        dockertree domains delete app.example.com --force
    """
    try:
        # Parse full domain into subdomain and domain components
        parts = full_domain.split('.')
        if len(parts) < 2:
            if json:
                JSONOutput.print_error(f"Invalid domain format: {full_domain}. Expected format: subdomain.domain.tld or domain.tld")
            else:
                error_exit(f"Invalid domain format: {full_domain}. Expected format: subdomain.domain.tld or domain.tld")
            return
        
        if len(parts) == 2:
            # This is a root domain (e.g., 'example.com' -> subdomain='', domain='example.com')
            subdomain = ''
            domain = full_domain
        else:
            # This is a subdomain (e.g., 'app.example.com' -> subdomain='app', domain='example.com')
            try:
                subdomain, domain = parse_domain(full_domain)
            except ValueError as e:
                if json:
                    JSONOutput.print_error(f"Invalid domain format: {e}")
                else:
                    error_exit(f"Invalid domain format: {e}")
                return
        
        check_prerequisites_no_git()  # Don't require git for domain operations
        domain_commands = DomainCommands()
        success = domain_commands.delete_domain(
            subdomain=subdomain,
            domain=domain,
            force=force,
            dns_token=dns_token,
            json=json
        )
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to delete DNS A record: {full_domain}")
            else:
                error_exit(f"Failed to delete DNS A record: {full_domain}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error deleting DNS A record: {e}")
        else:
            error_exit(f"Error deleting DNS A record: {e}")


@domains.command('info')
@click.argument('full_domain')
@click.option('--dns-token', help='DNS API token (or use DIGITALOCEAN_API_TOKEN env var)')
@add_json_option
@add_verbose_option
def domains_info(full_domain: str, dns_token: Optional[str], json: bool):
    """Get detailed information about a DNS A record.

    Displays detailed information about a DNS A record including IP address,
    TTL, and record ID. Provide the full domain (e.g., 'app.example.com'
    for a subdomain or 'example.com' for root domain).

    Examples:

        dockertree domains info app.example.com

        dockertree domains info example.com
        dockertree domains info app.example.com --json
    """
    try:
        # Parse full domain into subdomain and domain components
        parts = full_domain.split('.')
        if len(parts) < 2:
            if json:
                JSONOutput.print_error(f"Invalid domain format: {full_domain}. Expected format: subdomain.domain.tld or domain.tld")
            else:
                error_exit(f"Invalid domain format: {full_domain}. Expected format: subdomain.domain.tld or domain.tld")
            return
        
        if len(parts) == 2:
            # This is a root domain (e.g., 'example.com' -> subdomain='', domain='example.com')
            subdomain = ''
            domain = full_domain
        else:
            # This is a subdomain (e.g., 'app.example.com' -> subdomain='app', domain='example.com')
            try:
                subdomain, domain = parse_domain(full_domain)
            except ValueError as e:
                if json:
                    JSONOutput.print_error(f"Invalid domain format: {e}")
                else:
                    error_exit(f"Invalid domain format: {e}")
                return
        
        check_prerequisites_no_git()  # Don't require git for domain operations
        domain_commands = DomainCommands()
        success = domain_commands.get_domain_info(
            subdomain=subdomain,
            domain=domain,
            dns_token=dns_token,
            json=json
        )
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to get DNS A record info: {full_domain}")
            else:
                error_exit(f"Failed to get DNS A record info: {full_domain}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error getting DNS A record info: {e}")
        else:
            error_exit(f"Error getting DNS A record info: {e}")


@cli.group()
@add_verbose_option
def packages():
    """Manage environment packages for sharing and deployment.

    Provides commands for exporting, importing, listing, and validating
    complete worktree environment packages that can be shared or deployed.

    Examples:

        dockertree packages export feature-auth

        dockertree packages import ./packages/feature-auth.tar.gz
    """
    pass


@packages.command('export')
@click.argument('branch_name')
@click.option('--output-dir', type=click.Path(), default='./packages', help='Output directory for packages (default: ./packages)')
@click.option('--include-code/--no-code', default=True, help='Include git archive of code in package (default: True)')
@click.option('--compressed/--no-compress', default=True, help='Compress package to .tar.gz format (default: True)')
@click.option('--skip-volumes', is_flag=True, default=False, help='Skip volume backup (fallback when volume backup fails)')
@add_json_option
@add_verbose_option
def export_package(branch_name: str, output_dir: str, include_code: bool, compressed: bool, skip_volumes: bool, json: bool):
    """Export worktree environment to a shareable package.

    Creates a complete package containing the worktree environment including
    Docker Compose configuration, volumes, and optionally the codebase. The
    package can be shared with others or deployed to remote servers.

    Examples:

        dockertree packages export feature-auth

        dockertree packages export feature-auth --output-dir /path/to/packages
        dockertree packages export feature-auth --no-code

        dockertree packages export feature-auth --skip-volumes
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        package_commands = PackageCommands()
        success = package_commands.export(branch_name, Path(output_dir), include_code, compressed, skip_volumes)
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to export package for {branch_name}")
            else:
                error_exit(f"Failed to export package for {branch_name}")
        else:
            if json:
                JSONOutput.print_success(f"Package exported successfully for {branch_name}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error exporting package: {e}")
        else:
            error_exit(f"Error exporting package: {e}")


@packages.command('import')
@click.argument('package_file', type=click.Path(exists=True))
@click.option('--target-branch', help='Target branch name (for normal mode, optional)')
@click.option('--restore-data/--no-data', default=True, help='Restore volume data from backup (default: True)')
@click.option('--standalone', is_flag=True, default=None,
              help='Force standalone mode (create new project from package)')
@click.option('--target-dir', type=click.Path(),
              help='Target directory for standalone import (default: {project_name}-standalone)')
@click.option('--domain', help='Domain override (subdomain.domain.tld) for production/staging deployments')
@click.option('--ip', help='IP override for HTTP-only deployments (no TLS)')
@click.option('--non-interactive', is_flag=True, default=False, help='Run import/setup non-interactively (auto-accept safe defaults)')
@add_json_option
@add_verbose_option
def import_package(package_file: str, target_branch: str, restore_data: bool,
                  standalone: bool, target_dir: str, domain: str, ip: str, non_interactive: bool, json: bool):
    """Import environment from a package.

    Imports a complete worktree environment from a previously exported package.
    Automatically detects if you're in an existing project or need standalone mode.

    Use --standalone to force creating a new project from the package.
    Use --domain to override localhost URLs for production/staging deployments.

    Examples:

        dockertree packages import ./packages/feature-auth.tar.gz

        dockertree packages import ./packages/feature-auth.tar.gz --standalone
        dockertree packages import ./packages/feature-auth.tar.gz --domain app.example.com

        dockertree packages import ./packages/feature-auth.tar.gz --ip 192.0.2.1
    """
    try:
        # Only check setup if explicitly not standalone
        # (auto-detection happens in PackageManager)
        if standalone is False:
            check_setup_or_prompt()
        
        check_prerequisites_no_git()  # Skip git validation - handled by PackageManager
        package_commands = PackageCommands()
        
        # Pass all parameters to PackageCommands
        # Validate mutual exclusivity
        if domain and ip:
            if json:
                JSONOutput.print_error("Options --domain and --ip are mutually exclusive")
            else:
                error_exit("Options --domain and --ip are mutually exclusive")

        success = package_commands.import_package(
            Path(package_file),
            target_branch,
            restore_data,
            standalone=standalone,
            target_directory=Path(target_dir) if target_dir else None,
            domain=domain,
            ip=ip,
            non_interactive=non_interactive
        )
        
        if not success:
            if json:
                JSONOutput.print_error(f"Failed to import package {package_file}")
            else:
                error_exit(f"Failed to import package {package_file}")
        else:
            if json:
                JSONOutput.print_success(f"Package imported successfully from {package_file}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error importing package: {e}")
        else:
            error_exit(f"Error importing package: {e}")


@packages.command('list')
@click.option('--package-dir', type=click.Path(), default='./packages', help='Package directory to search (default: ./packages)')
@add_json_option
@add_verbose_option
def list_packages(package_dir: str, json: bool):
    """List available packages.

    Displays all available environment packages in the specified directory,
    including package names, sizes, and creation dates.

    Examples:

        dockertree packages list

        dockertree packages list --package-dir /path/to/packages
        dockertree packages list --json
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        package_commands = PackageCommands()
        if json:
            packages = package_commands.list_packages_json(Path(package_dir))
            JSONOutput.print_json(packages)
        else:
            package_commands.list_packages(Path(package_dir))
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error listing packages: {e}")
        else:
            error_exit(f"Error listing packages: {e}")


@packages.command('validate')
@click.argument('package_file', type=click.Path(exists=True))
@add_json_option
@add_verbose_option
def validate_package(package_file: str, json: bool):
    """Validate package integrity.

    Checks that a package file is valid and contains all required components
    for importing. Validates checksums and package structure.

    Examples:

        dockertree packages validate ./packages/feature-auth.tar.gz

        dockertree packages validate ./packages/feature-auth.tar.gz --json
    """
    try:
        check_setup_or_prompt()
        check_prerequisites()
        package_commands = PackageCommands()
        if json:
            result = package_commands.validate_package_json(Path(package_file))
            JSONOutput.print_json(result)
        else:
            success = package_commands.validate_package(Path(package_file))
            if not success:
                error_exit(f"Package validation failed for {package_file}")
    except Exception as e:
        if json:
            JSONOutput.print_error(f"Error validating package: {e}")
        else:
            error_exit(f"Error validating package: {e}")


@droplet.command('push')
@click.argument('branch_name', required=False)
@click.argument('scp_target', required=False)
@click.option('--output-dir', type=click.Path(), default='./packages', help='Temporary package location (default: ./packages)')
@click.option('--keep-package', is_flag=True, default=False, help='Keep package file after successful push (default: delete after push)')
@click.option('--no-auto-import', is_flag=True, default=False, help='Skip automatic import and start on remote server after push (default: auto-import is enabled)')
@click.option('--prepare-server', is_flag=True, default=False, help='Check remote server for required dependencies before push')
@click.option('--domain', help='Domain override for remote import (subdomain.domain.tld). DNS A record will be automatically created if it does not exist.')
@click.option('--ip', help='IP override for remote import (HTTP-only, no TLS)')
@click.option('--dns-token', help='DigitalOcean API token (or use DIGITALOCEAN_API_TOKEN env var)')
@click.option('--skip-dns-check', is_flag=True, default=False, help='Skip DNS validation and management')
@click.option('--resume', is_flag=True, default=False, help='Resume a failed push operation by detecting what\'s already completed (skips export/transfer if package exists, skips server prep if already done)')
@click.option('--code-only', is_flag=True, default=False, help='Push code-only update to pre-existing server (uses stored push config from env.dockertree if available)')
@click.option('--build', is_flag=True, default=False, help='Rebuild Docker images after code update (only works with --code-only)')
@click.option('--containers', help='Comma-separated list of worktree.container patterns to push only specific containers and their volumes (e.g., feature-auth.db,feature-auth.redis)')
@click.option('--exclude-deps', help='Comma-separated list of service names to exclude from dependency resolution (e.g., db,redis). Useful when deploying workers that connect to remote services.')
@add_json_option
@add_verbose_option
def droplet_push(branch_name: Optional[str], scp_target: Optional[str], output_dir: str, keep_package: bool, no_auto_import: bool, prepare_server: bool, domain: str, ip: str, dns_token: str, skip_dns_check: bool, resume: bool, code_only: bool, build: bool, containers: Optional[str], exclude_deps: Optional[str], json: bool):
    """Push dockertree package to remote server via SCP.

    Exports a complete dockertree environment package and transfers it to a
    remote server via SCP. If branch_name is not provided, auto-detects from
    current working directory.

    Use --resume to resume a failed push operation. Resume mode automatically detects:
    - If package already exists on server (skips export and transfer)
    - If server is already prepared (skips server preparation)
    - Continues from where it left off

    Use --code-only for fast code updates on pre-existing servers. Automatically detects
    whether code is stored in volumes or bind mounts and uses appropriate update method.
    Uses stored push configuration from env.dockertree if available (saved after first push).

    Examples:

        # Auto-detect branch from current directory
        dockertree droplet push user@server:/path/to/packages

        # Explicit branch name
        dockertree droplet push feature-auth user@server:/path/to/packages

        # Code-only update (uses stored config from env.dockertree)
        dockertree droplet push --code-only

        # Code-only update with explicit arguments
        dockertree droplet push feature-auth user@server:/path/to/packages --code-only

        # Code-only update with image rebuild
        dockertree droplet push --code-only --build

        # Push with domain configuration
        dockertree droplet push feature-auth user@server:/path/to/packages --domain app.example.com

        # Resume a failed push (skips already completed steps)
        dockertree droplet push feature-auth user@server:/path/to/packages --resume --auto-import

    After pushing, SSH to the server and import with:
        dockertree packages import <package-file> --standalone --domain your-domain.com
    """
    start_time = time.time()
    try:
        check_setup_or_prompt()
        check_prerequisites()
        
        # Validate mutual exclusivity
        if domain and ip:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("Options --domain and --ip are mutually exclusive")
            else:
                error_exit("Options --domain and --ip are mutually exclusive")
            return
        
        # Validate scp_target is provided when not using code-only
        # (code-only can use stored config from env.dockertree)
        if not code_only and not scp_target:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("scp_target is required")
            else:
                error_exit("scp_target is required")
            return
        
        # Validate --build is only used with --code-only
        if build and not code_only:
            elapsed_time = time.time() - start_time
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error("--build can only be used with --code-only")
            else:
                error_exit("--build can only be used with --code-only")
            return
        
        push_manager = PushManager()
        # Parse exclude_deps from comma-separated string to list
        exclude_deps_list = [d.strip() for d in exclude_deps.split(',')] if exclude_deps else None
        
        success = push_manager.push_package(
            branch_name=branch_name,
            scp_target=scp_target,
            output_dir=Path(output_dir),
            keep_package=keep_package,
            auto_import=not no_auto_import,  # Invert: no_auto_import=True means auto_import=False
            domain=domain,
            ip=ip,
            prepare_server=prepare_server,
            dns_token=dns_token,
            skip_dns_check=skip_dns_check,
            create_droplet=False,
            droplet_name=None,
            droplet_region=None,
            droplet_size=None,
            droplet_image=None,
            droplet_ssh_keys=None,
            resume=resume,
            code_only=code_only,
            build=build,
            containers=containers,
            exclude_deps=exclude_deps_list
        )
        
        elapsed_time = time.time() - start_time
        if not success:
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_error(f"Failed to push package")
            else:
                error_exit(f"Failed to push package")
        else:
            if not json:
                print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
            if json:
                JSONOutput.print_success(f"Package pushed successfully")
    except Exception as e:
        elapsed_time = time.time() - start_time
        if not json:
            print_plain(f"Total elapsed time: {format_elapsed_time(elapsed_time)}")
        if json:
            JSONOutput.print_error(f"Error pushing package: {e}")
        else:
            error_exit(f"Error pushing package: {e}")


@cli.command()
@click.option('--project-name', help='Project name (default: directory name)')
@click.option('--monkey-patch', is_flag=True, default=False, help='If a Django project is detected, auto-patch settings.py to read environment variables')
@click.option('--examples', is_flag=True, default=False, help='Regenerate example config files in examples/ directory')
@add_verbose_option
def setup(project_name: Optional[str], monkey_patch: bool, examples: bool):
    """Initialize dockertree for this project.

    Sets up dockertree configuration files and directory structure for the
    current project. This must be run before using other dockertree commands.

    Examples:

        dockertree setup

        dockertree setup --project-name myproject
        dockertree setup --monkey-patch

        dockertree setup --examples
    """
    try:
        setup_manager = SetupManager()
        
        # If --examples flag is set, regenerate example files and return early
        if examples:
            check_prerequisites(project_root=setup_manager.project_root)
            success = setup_manager._regenerate_example_files()
            if not success:
                error_exit("Failed to regenerate example files")
            return
        
        check_prerequisites(project_root=setup_manager.project_root)
        success = setup_manager.setup_project(project_name, monkey_patch=monkey_patch)
        if not success:
            error_exit("Failed to setup dockertree for this project")
    except Exception as e:
        error_exit(f"Error setting up dockertree: {e}")


@cli.command('clean-legacy')
@add_verbose_option
def clean_legacy():
    """Clean legacy dockertree elements from docker-compose.yml.

    Removes outdated dockertree configuration from docker-compose.yml files.
    Useful when upgrading from older versions of dockertree.

    Examples:

        dockertree clean-legacy
    """
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
    """Show help information.

    Displays the main help message with available commands and usage examples.

    Examples:

        dockertree help
    """
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
    """Manage shell completion for dockertree.

    Provides commands for installing, uninstalling, and checking the status
    of shell completion support for bash, zsh, and fish shells.

    Examples:

        dockertree completion install

        dockertree completion status
    """
    pass


@completion.command('install')
@click.argument('shell', required=False)
@add_verbose_option
def completion_install(shell: Optional[str]):
    """Install shell completion for dockertree.

    Installs tab completion support for the specified shell (bash, zsh, or fish).
    If shell is not specified, auto-detects from the current shell.

    Examples:

        dockertree completion install

        dockertree completion install bash
        dockertree completion install zsh
    """
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
    """Remove shell completion for dockertree.

    Uninstalls tab completion support for all shells. Removes completion
    scripts from shell configuration files.

    Examples:

        dockertree completion uninstall
    """
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
    """Show shell completion installation status.

    Displays the current status of shell completion installation for all
    supported shells (bash, zsh, fish).

    Examples:

        dockertree completion status
    """
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

    Executes docker compose commands for the specified worktree with automatic
    resolution of the worktree-specific override file. This allows you to run
    any docker compose command without manually specifying override files.

    Examples:

        dockertree feature-123 exec web python manage.py migrate

        dockertree feature-123 logs -f web
        dockertree feature-123 ps

        dockertree feature-123 build
        dockertree feature-123 run web python manage.py shell
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
