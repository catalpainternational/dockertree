"""
Worktree lifecycle management commands for dockertree CLI.

This module provides commands for creating, starting, stopping, and removing worktrees.
"""

import os
from pathlib import Path
from typing import Optional

from ..config.settings import get_project_root, get_script_dir, COMPOSE_WORKTREE
from ..core.docker_manager import DockerManager
from ..core.git_manager import GitManager
from ..core.environment_manager import EnvironmentManager
from ..utils.logging import log_info, log_success, log_warning, log_error
from ..utils.path_utils import (
    get_compose_override_path, 
    get_worktree_branch_name,
    ensure_main_repo
)
from ..utils.validation import validate_branch_exists
from ..utils.validation import validate_worktree_directory
from ..utils.pattern_matcher import has_wildcard, get_matching_branches
from ..utils.confirmation import confirm_batch_operation


class WorktreeManager:
    """Manages worktree lifecycle operations."""

    def __init__(self):
        """Initialize worktree manager."""
        self.docker_manager = DockerManager()
        self.git_manager = GitManager()
        self.env_manager = EnvironmentManager()
        self.project_root = get_project_root()

    def _find_true_project_root(self) -> Optional[Path]:
        """Find the true project root containing .dockertree/config.yml.
        
        This searches upward from current directory to find the root .dockertree
        that contains config.yml, not just any .dockertree directory.
        """
        current = Path.cwd()
        
        # Check current directory
        dockertree_dir = current / ".dockertree"
        if dockertree_dir.exists() and (dockertree_dir / "config.yml").exists():
            return current
        
        # Search upward through parent directories
        for parent in current.parents:
            dockertree_dir = parent / ".dockertree"
            if dockertree_dir.exists() and (dockertree_dir / "config.yml").exists():
                return parent
        
        # Fallback to current project root
        return self.project_root

    def _copy_dockertree_to_worktree(self, worktree_path: Path) -> bool:
        """Copy .dockertree directory from project root to worktree.
        
        This implements the fractal design where each worktree gets its own
        .dockertree configuration directory.
        """
        import shutil
        
        # Find the true project root
        true_project_root = self._find_true_project_root()
        if not true_project_root:
            log_warning("Could not find project root with .dockertree directory")
            return False
        
        source_dockertree = true_project_root / ".dockertree"
        target_dockertree = worktree_path / ".dockertree"
        
        # Verify source exists
        if not source_dockertree.exists():
            log_warning(f"Source .dockertree directory not found: {source_dockertree}")
            return False
        
        # Don't copy if target already exists
        if target_dockertree.exists():
            log_info(f"Worktree already has .dockertree directory, skipping copy")
            return True
        
        try:
            log_info("Copying .dockertree configuration to worktree...")
            
            # Define ignore function to skip worktrees subdirectory
            def ignore_worktrees(dir_path, names):
                """Ignore .dockertree/worktrees/ subdirectory during copy."""
                if dir_path == str(source_dockertree):
                    # Skip the worktrees subdirectory at the root level
                    return ['worktrees'] if 'worktrees' in names else []
                return []
            
            # Copy the entire .dockertree directory, excluding worktrees
            shutil.copytree(source_dockertree, target_dockertree, ignore=ignore_worktrees)
            
            log_success("Copied .dockertree configuration to worktree")
            return True
            
        except Exception as e:
            log_error(f"Failed to copy .dockertree to worktree: {e}")
            return False
    
    def create_worktree(self, branch_name: str) -> bool:
        """Create a new worktree."""
        if not branch_name:
            log_error("Branch name is required")
            return False
        
        log_info(f"Creating worktree for branch: {branch_name}")
        
        # Check if worktree already exists
        if self.git_manager.validate_worktree_exists(branch_name):
            log_info(f"Worktree for branch {branch_name} already exists")
            worktree_path = self.git_manager.find_worktree_path(branch_name)
            if worktree_path:
                log_success(f"Worktree for {branch_name} is ready at: {worktree_path}")
                return True
            else:
                log_error(f"Worktree directory not found for branch '{branch_name}'. The worktree may be corrupted.")
                return False
        
        # Create branch if it doesn't exist
        if not self.git_manager.create_branch(branch_name):
            return False
        
        # Validate worktree creation (after branch is created)
        can_create, error_msg = self.git_manager.validate_worktree_creation(branch_name)
        if not can_create:
            log_error(error_msg)
            return False
        
        # Get worktree paths
        new_path, legacy_path = self.git_manager.get_worktree_paths(branch_name)
        
        # Create worktree
        if not self.git_manager.create_worktree(branch_name, new_path):
            return False
        
        # Copy .dockertree configuration to worktree for fractal design
        if not self._copy_dockertree_to_worktree(new_path):
            log_warning("Failed to copy .dockertree to worktree, but continuing...")
        
        # Create worktree-specific volumes
        if not self.docker_manager.create_worktree_volumes(branch_name, force_copy=True):
            log_warning("Failed to create some worktree volumes")
        
        # Create environment file
        if not self.env_manager.create_worktree_env(branch_name, new_path):
            log_warning("Failed to create environment file")
        
        # Get worktree path for user information
        worktree_path = self.git_manager.find_worktree_path(branch_name)
        if worktree_path:
            # Calculate relative path for user-friendly display
            try:
                relative_path = worktree_path.relative_to(self.project_root)
                log_success(f"Worktree created for {branch_name}")
                log_info(f"📁 Location: {relative_path}")
                log_info(f"💡 Navigate: cd {relative_path}")
                log_info(f"🚀 Next: dockertree up {branch_name}")
            except ValueError:
                # Fallback if relative path calculation fails
                log_success(f"Worktree created for {branch_name}")
                log_info(f"📁 Location: {worktree_path}")
        else:
            log_success(f"Worktree created for {branch_name}")
        
        return True
    
    def start_worktree(self, branch_name: str) -> bool:
        """Start worktree environment for specified branch."""
        log_info(f"Starting worktree environment for branch: {branch_name}")
        
        # Validate worktree exists
        if not self.git_manager.validate_worktree_exists(branch_name):
            log_error(f"Worktree for branch '{branch_name}' does not exist. Please create it first with: dockertree create {branch_name}")
            return False
        
        # Resolve worktree path
        worktree_path = self.git_manager.find_worktree_path(branch_name)
        if not worktree_path:
            log_error(f"Could not find worktree directory for branch '{branch_name}'")
            return False
        
        # Get the correct path to the compose override file
        compose_override_path = get_compose_override_path(worktree_path)
        if not compose_override_path:
            log_error("Could not find compose override file. Please ensure dockertree directory exists.")
            return False
        
        # Get branch name and ensure worktree volumes exist
        branch_name = get_worktree_branch_name(worktree_path)
        if not branch_name:
            log_error("Could not determine branch name from worktree path")
            return False
        
        log_info(f"Ensuring volumes exist for branch: {branch_name}")
        self.docker_manager.create_worktree_volumes(branch_name, force_copy=False)
        
        # Create network if it doesn't exist
        if not self.docker_manager.create_network():
            return False
        
        # Ensure global Caddy is running
        from .caddy import CaddyManager
        caddy_manager = CaddyManager()
        if not caddy_manager.is_caddy_running():
            log_info("Global Caddy not running, starting it...")
            if not caddy_manager.start_global_caddy():
                log_error("Failed to start global Caddy")
                return False
        
        # Validate environment files exist
        env_file = worktree_path / ".dockertree" / "env.dockertree"
        main_env_file = worktree_path / ".env"

        if not env_file.exists() or not main_env_file.exists():
            log_warning("Environment files missing, attempting to create them...")
            # Try to create missing environment files
            if not self.env_manager.create_worktree_env(branch_name, worktree_path):
                log_error("Failed to create environment files")
                return False
            
            # Re-validate after creation
            if not env_file.exists():
                log_error("Worktree env.dockertree file not found after creation")
                return False
            if not main_env_file.exists():
                log_error("Worktree .env file not found after creation")
                return False

        # Use the compose file found by get_compose_override_path
        compose_file = compose_override_path

        if not compose_file.exists():
            log_error(f"Compose worktree file not found: {compose_file}")
            return False

        # Get the full compose project name (project-branch format)
        from ..config.settings import get_project_name, sanitize_project_name
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        
        success = self.docker_manager.run_compose_command(compose_file, ["up", "-d"], env_file, compose_project_name, worktree_path)
        if success:
            log_success("Worktree environment started successfully")

            # Give containers time to initialize before configuring Caddy
            import time
            log_info("Waiting for containers to fully initialize...")
            time.sleep(5)

            # Configure Caddy routes for dynamic routing
            caddy_success = self._configure_caddy_routes()

            # Get the correct domain name with project prefix
            domain_name = self.env_manager.get_domain_name(branch_name)
            
            # Provide user with access information
            log_success(f"🌐 Application available at: http://{domain_name}/")
            log_info(f"📋 Domain: {domain_name}")
            log_info(f"🔗 Full URL: http://{domain_name}/")

            if caddy_success:
                log_info("✅ Caddy routing configuration completed")
            else:
                log_warning("⚠️ Caddy routing configuration may have failed")
        else:
            log_error("Failed to start worktree environment")

        return success
    
    def _configure_caddy_routes(self) -> bool:
        """Configure Caddy routes for dynamic routing."""
        try:
            import subprocess
            import sys

            # Get the path to the dynamic config script
            script_path = get_script_dir() / "scripts" / "caddy-dynamic-config.py"

            if not script_path.exists():
                log_warning("Caddy dynamic configuration script not found")
                return False

            log_info("Configuring Caddy routes...")
            
            # Run the dynamic configuration script using current Python interpreter
            result = subprocess.run([
                sys.executable, str(script_path)
            ], capture_output=True, text=True, check=False)  # Don't raise exception on non-zero exit

            # Parse the output to determine the routing method used
            output_lines = result.stdout.split('\n')
            routing_method = "unknown"
            validation_passed = False
            misconfigurations_detected = False
            network_issues_detected = False
            
            for line in output_lines:
                if "Successfully updated Caddy configuration via admin API" in line:
                    routing_method = "admin API"
                elif "Using container label-based routing" in line:
                    routing_method = "container labels"
                elif "All route configurations validated successfully" in line:
                    validation_passed = True
                elif "Route validation passed:" in line:
                    validation_passed = True
                elif "Route misconfiguration detected:" in line:
                    log_error(f"Caddy route misconfiguration: {line}")
                    misconfigurations_detected = True
                elif "Detected" in line and "misconfigurations" in line:
                    log_warning(f"Caddy configuration issues: {line}")
                    misconfigurations_detected = True
                elif "Network connectivity test failed" in line:
                    log_warning(f"Network connectivity issue: {line}")
                    network_issues_detected = True
                elif "Network issues detected" in line:
                    log_warning(f"Network issues: {line}")
                    network_issues_detected = True

            if result.returncode == 0:
                if routing_method == "admin API":
                    log_info("✅ Caddy routes configured via admin API")
                elif routing_method == "container labels":
                    log_info("✅ Caddy routes configured via container labels (normal)")
                else:
                    log_info("✅ Caddy routes configured successfully")
                
                # Report validation status
                if validation_passed:
                    log_success("✅ Route validation passed")
                else:
                    log_warning("⚠️ Route validation status unknown")
                
                if misconfigurations_detected:
                    log_warning("⚠️ Some routing misconfigurations detected - routes may not work correctly")
                
                if network_issues_detected:
                    log_warning("⚠️ Network connectivity issues detected - some routes may not work correctly")
                    log_warning("💡 Consider checking container logs and network configuration")
                
                return True
            else:
                # Check if it's a fallback scenario (which is actually success)
                if "Using container label-based routing" in result.stdout:
                    log_info("✅ Caddy routes configured via container labels (normal)")
                    return True
                else:
                    log_warning(f"Failed to configure Caddy routes: {result.stderr}")
                    return False

        except Exception as e:
            log_warning(f"Failed to configure Caddy routes: {e}")
            return False
    
    def stop_worktree(self, branch_name: str, remove_images: bool = False) -> bool:
        """Stop worktree environment for specified branch.
        
        Args:
            branch_name: Name of the branch/worktree to stop
            remove_images: If True, removes locally built images with --rmi local
        """
        log_info(f"Stopping worktree environment for branch: {branch_name}")
        
        # Validate worktree exists (allow stopping even if not found for cleanup)
        if not self.git_manager.validate_worktree_exists(branch_name):
            log_warning(f"Worktree for branch '{branch_name}' does not exist, skipping container stop")
            return True
        
        # Resolve worktree path
        worktree_path = self.git_manager.find_worktree_path(branch_name)
        if not worktree_path:
            log_warning(f"Could not find worktree directory for branch '{branch_name}', skipping container stop")
            return True
        
        # Get the correct path to the compose override file (same as start_worktree)
        compose_file = get_compose_override_path(worktree_path)
        if not compose_file:
            log_warning("Could not find compose override file, skipping container stop")
            return True
        env_file = (worktree_path / ".dockertree" / "env.dockertree").resolve()

        if not compose_file.exists():
            log_warning("Compose worktree file not found, skipping container stop")
            return True

        if not env_file.exists():
            log_warning(f"Environment file not found: {env_file}, skipping container stop")
            return True

        # Add --rmi local flag if remove_images is True
        extra_flags = ["--rmi", "local"] if remove_images else None
        
        # Get the full compose project name (project-branch format)
        from ..config.settings import get_project_name, sanitize_project_name
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        
        success = self.docker_manager.run_compose_command(
            compose_file, ["down"], env_file, compose_project_name, worktree_path, extra_flags
        )
        
        if success:
            if remove_images:
                log_success("Worktree environment stopped and images removed")
            else:
                log_success("Worktree environment stopped")
        else:
            log_warning("Failed to stop some services (may not be running)")
        
        return True  # Always return True for stop operations
    
    def remove_worktree(self, branch_name: str, force: bool = False, delete_branch: bool = True) -> bool:
        """Remove worktree completely."""
        if not branch_name:
            log_error("Branch name is required")
            return False
        
        # Ensure we're in the main repository directory
        ensure_main_repo()
        
        log_info(f"Removing worktree for branch: {branch_name}")
        
        # Check if worktree exists
        worktree_exists = self.git_manager.validate_worktree_exists(branch_name)
        
        if not worktree_exists:
            # Check if branch exists to determine appropriate action
            if validate_branch_exists(branch_name):
                log_warning(f"Worktree for branch '{branch_name}' does not exist, but the branch exists. Proceeding to delete the branch.")
                # Skip worktree removal and go directly to branch deletion
                if delete_branch:
                    branch_deleted = self.git_manager.delete_branch_safely(branch_name, force)
                    if branch_deleted:
                        log_success(f"Branch '{branch_name}' deleted successfully")
                        return True
                    else:
                        log_error(f"Failed to delete branch '{branch_name}'")
                        return False
                else:
                    log_info(f"Branch '{branch_name}' exists but worktree removal was skipped (delete_branch=False)")
                    return True
            else:
                log_error(f"Neither worktree nor branch '{branch_name}' exists. Please check the branch name and try again.")
                return False
        
        # Stop worktree environment if running
        # Always remove images when deleting a worktree
        worktree_path = self.git_manager.find_worktree_path(branch_name)
        if worktree_path:
            stop_success = self.stop_worktree(branch_name, remove_images=True)
            if not stop_success:
                log_warning("Failed to stop worktree environment, but continuing with removal")

        # Remove worktree-specific volumes (only if containers are stopped)
        log_info("Removing worktree-specific volumes")
        volume_removal_success = self.docker_manager.remove_volumes(branch_name)
        if not volume_removal_success:
            log_warning("Some volumes may not have been removed completely")
        
        # Remove worktree
        if worktree_path:
            if not self.git_manager.remove_worktree(worktree_path, force=True):
                log_error(f"Failed to remove worktree for {branch_name}")
                return False
        else:
            log_error(f"Worktree directory not found for branch '{branch_name}'. The worktree may be corrupted.")
            return False
        
        # Delete the git branch if requested
        if delete_branch:
            self.git_manager.delete_branch_safely(branch_name, force)
        
        log_success(f"Worktree removed for {branch_name}")
        return True
    
    def list_worktrees(self) -> list:
        """List active worktrees."""
        log_info("Active worktrees:")
        worktrees = self.git_manager.list_worktrees()
        
        for path, commit, branch in worktrees:
            log_info(f"{path} {commit} [{branch}]")
        
        return worktrees
    
    def prune_worktrees(self) -> int:
        """Prune worktrees."""
        log_info("Pruning worktrees...")
        pruned_count = self.git_manager.prune_worktrees()
        return pruned_count
    
    def remove_all_worktrees(self, force: bool = False, delete_branch: bool = True) -> bool:
        """Remove all worktrees, containers, and volumes."""
        # Ensure we're in the main repository directory
        ensure_main_repo()
        
        log_info("Removing all worktrees...")
        
        # Get all active worktrees
        worktrees = self.git_manager.list_worktrees()
        
        if not worktrees:
            log_info("No worktrees found to remove")
            return True
        
        # Filter out the main repository to avoid removing it
        current_branch = self.git_manager.get_current_branch()
        filtered_worktrees = []
        
        for path, commit, branch in worktrees:
            # Skip the main repository (current branch)
            if branch == current_branch:
                log_info(f"Skipping main repository worktree: {branch}")
                continue
            filtered_worktrees.append((path, commit, branch))
        
        if not filtered_worktrees:
            log_info("No worktrees found to remove (excluding main repository)")
            return True
        
        log_info(f"Found {len(filtered_worktrees)} worktree(s) to remove")
        
        # Track results
        success_count = 0
        failure_count = 0
        failed_branches = []
        
        # Process each worktree
        for path, commit, branch in filtered_worktrees:
            log_info(f"Removing worktree: {branch}")
            try:
                # Use existing remove_worktree method for each worktree
                if self.remove_worktree(branch, force, delete_branch):
                    success_count += 1
                    log_success(f"Successfully removed worktree: {branch}")
                else:
                    failure_count += 1
                    failed_branches.append(branch)
                    log_error(f"Failed to remove worktree: {branch}")
            except Exception as e:
                failure_count += 1
                failed_branches.append(branch)
                log_error(f"Error removing worktree {branch}: {e}")
        
        # Summary
        if failure_count == 0:
            log_success(f"Successfully removed all {success_count} worktree(s)")
            return True
        else:
            log_warning(f"Removed {success_count} worktree(s), failed to remove {failure_count} worktree(s)")
            if failed_branches:
                log_warning(f"Failed branches: {', '.join(failed_branches)}")
            return failure_count == 0  # Return True only if all succeeded
    
    def get_worktree_info(self, branch_name: str) -> dict:
        """Get information about a worktree."""
        return {
            "branch_name": branch_name,
            "exists": self.git_manager.validate_worktree_exists(branch_name),
            "path": self.git_manager.find_worktree_path(branch_name),
            "branch_info": self.git_manager.get_branch_info(branch_name),
            "volumes": self.env_manager.get_worktree_volume_names(branch_name),
            "config": self.env_manager.get_worktree_config(branch_name)
        }
    
    def remove_worktrees_by_pattern(self, pattern: str, force: bool = False, delete_branch: bool = True) -> bool:
        """Remove worktrees matching a wildcard pattern.
        
        Args:
            pattern: Wildcard pattern to match branch names
            force: Force removal even with unmerged changes
            delete_branch: Whether to delete the git branch as well
            
        Returns:
            True if all operations succeeded, False if any failed
        """
        if not pattern:
            log_error("Pattern is required")
            return False
        
        # Ensure we're in the main repository directory
        ensure_main_repo()
        
        log_info(f"Removing worktrees matching pattern: {pattern}")
        
        # Get all branches and find matches
        all_branches = self.git_manager.list_all_branches()
        if not all_branches:
            log_error("No branches found")
            return False
        
        # Get current branch to exclude it from deletion
        current_branch = self.git_manager.get_current_branch()
        
        # Find matching branches
        matching_branches = get_matching_branches(pattern, all_branches, current_branch)
        
        if not matching_branches:
            log_info(f"No branches found matching pattern: {pattern}")
            return True
        
        # Show confirmation prompt
        operation = "delete" if delete_branch else "remove"
        if not confirm_batch_operation(matching_branches, operation):
            log_info("Operation cancelled by user")
            return True
        
        # Track results
        success_count = 0
        failure_count = 0
        failed_branches = []
        
        # Process each matching branch
        for branch_name in matching_branches:
            log_info(f"Removing worktree: {branch_name}")
            try:
                if self.remove_worktree(branch_name, force, delete_branch):
                    success_count += 1
                    log_success(f"Successfully removed worktree: {branch_name}")
                else:
                    failure_count += 1
                    failed_branches.append(branch_name)
                    log_error(f"Failed to remove worktree: {branch_name}")
            except Exception as e:
                failure_count += 1
                failed_branches.append(branch_name)
                log_error(f"Error removing worktree {branch_name}: {e}")
        
        # Summary
        if failure_count == 0:
            log_success(f"Successfully removed all {success_count} worktree(s)")
            return True
        else:
            log_warning(f"Removed {success_count} worktree(s), failed to remove {failure_count} worktree(s)")
            if failed_branches:
                log_warning(f"Failed branches: {', '.join(failed_branches)}")
            return failure_count == 0  # Return True only if all succeeded
