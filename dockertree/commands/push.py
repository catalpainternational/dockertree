"""
Push command for deploying dockertree packages to remote servers.

This module provides functionality to export dockertree packages and transfer
them to remote servers via SCP for deployment.
"""

import subprocess
import re
import socket
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from ..core.package_manager import PackageManager
from ..core.dns_manager import DNSManager, parse_domain, is_domain
from ..core.droplet_manager import DropletManager
# Import DNS providers to trigger registration
from ..core import dns_providers  # noqa: F401
from ..utils.logging import log_info, log_success, log_warning, log_error, print_plain
from ..utils.path_utils import detect_execution_context, get_worktree_branch_name
from ..utils.confirmation import confirm_action
from ..utils.ssh_manager import SSHConnectionManager, SCPTarget
from ..utils.streaming import execute_with_streaming
from ..utils.remote_scripts import (
    get_server_prep_script, compose_remote_import_script,
    SERVER_PREP_SCRIPT_VERSION, check_script_cached, mark_script_cached
)


class PushManager:
    """Manages push operations for deploying packages to remote servers."""
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialize push manager.
        
        Args:
            project_root: Project root directory. If None, uses current working directory.
        """
        if project_root is None:
            from ..config.settings import get_project_root
            self.project_root = get_project_root()
        else:
            self.project_root = Path(project_root).resolve()
        
        self.package_manager = PackageManager(project_root=self.project_root)
        self.ssh_manager = SSHConnectionManager()
        
        # Caching for expensive operations
        self._ip_cache: Dict[str, str] = {}
        self._dns_cache: Dict[str, Tuple[bool, str]] = {}
        self._package_metadata_cache: Dict[str, Dict[str, Any]] = {}
        self._server_prep_cache: Dict[str, bool] = {}
    
    def _validate_and_prepare_inputs(self, branch_name: Optional[str], 
                                     scp_target: Optional[str],
                                     create_droplet: bool) -> Tuple[Optional[str], Optional[SCPTarget]]:
        """Validate and prepare input parameters.
        
        Returns:
            Tuple of (branch_name, scp_target_obj) or (None, None) on error
        """
        # Auto-detect branch name if not provided
        if not branch_name:
            log_info("Branch name not provided, attempting auto-detection...")
            branch_name = self._detect_current_branch()
            if not branch_name:
                log_error("Could not detect branch name. Please specify branch_name.")
                return None, None
            log_info(f"Auto-detected branch: {branch_name}")
        else:
            log_info(f"Using provided branch name: {branch_name}")
        
        # Validate SCP target if provided
        scp_target_obj = None
        if scp_target:
            try:
                scp_target_obj = SCPTarget(scp_target)
            except ValueError as e:
                log_error(str(e))
                return None, None
        
        return branch_name, scp_target_obj
    
    def _handle_droplet_creation(self, scp_target_obj: Optional[SCPTarget],
                                 branch_name: str,
                                 droplet_name: Optional[str],
                                 droplet_region: Optional[str],
                                 droplet_size: Optional[str],
                                 droplet_image: Optional[str],
                                 droplet_ssh_keys: Optional[list],
                                 dns_token: Optional[str]) -> Optional[SCPTarget]:
        """Handle droplet creation and return updated SCP target.
        
        Returns:
            Updated SCPTarget with droplet IP, or None on error
        """
        # Determine username and path
        if scp_target_obj:
            username = scp_target_obj.username
            remote_path = scp_target_obj.remote_path
            log_info(f"Using username '{username}' and path '{remote_path}' from provided SCP target")
        else:
            username = "root"
            remote_path = "/root"
            log_info(f"Using default username '{username}' and path '{remote_path}' for new droplet")
        
        # Create droplet
        log_info("Droplet creation requested, creating new droplet...")
        droplet_info = self._create_droplet_for_push(
            droplet_name=droplet_name or branch_name,
            droplet_region=droplet_region,
            droplet_size=droplet_size,
            droplet_image=droplet_image,
            droplet_ssh_keys=droplet_ssh_keys,
            api_token=dns_token
        )
        if not droplet_info or not droplet_info.ip_address:
            log_error("Failed to create droplet or get IP address. Aborting push.")
            return None
        
        # Update SCP target with droplet IP
        server = droplet_info.ip_address
        new_target = f"{username}@{server}:{remote_path}"
        log_info(f"Updated SCP target to use droplet IP address: {new_target}")
        return SCPTarget(new_target)
    
    def _handle_package_export(self, branch_name: str, output_dir: Path,
                               resume: bool, scp_target_obj: SCPTarget) -> Tuple[Optional[Path], Optional[str]]:
        """Handle package export.
        
        Returns:
            Tuple of (package_path, remote_file_path) or (None, None) on error
        """
        # Check if worktree exists
        from ..core.git_manager import GitManager
        git_manager = GitManager(project_root=self.project_root, validate=False)
        if not git_manager.validate_worktree_exists(branch_name):
            log_error(f"Worktree for branch '{branch_name}' does not exist")
            log_info("Available worktrees:")
            for wt in git_manager.list_worktrees():
                log_info(f"  - {wt}")
            return None, None
        
        # Check resume mode for existing package
        if resume:
            found_package = self._find_existing_package(
                scp_target_obj.username, scp_target_obj.server,
                scp_target_obj.remote_path, branch_name
            )
            if found_package:
                log_info(f"✓ Found existing package on server: {found_package}")
                log_info("Skipping package export...")
                return None, found_package
        
        # Export package
        log_info(f"Exporting package for branch: {branch_name}")
        log_info(f"Output directory: {output_dir}")
        export_result = self.package_manager.export_package(
            branch_name=branch_name,
            output_dir=output_dir,
            include_code=True,
            compressed=True
        )
        
        if not export_result.get("success"):
            log_error(f"Failed to export package: {export_result.get('error')}")
            return None, None
        
        package_path = Path(export_result.get("package_path"))
        if not package_path.exists():
            log_error(f"Package file not found: {package_path}")
            return None, None
        
        package_size_mb = self._get_package_size_mb(package_path)
        log_success(f"Package exported successfully: {package_path.name} ({package_size_mb:.2f} MB)")
        
        # Cache metadata
        self._package_metadata_cache[branch_name] = export_result.get("metadata", {})
        
        remote_file_path = scp_target_obj.get_remote_file_path(package_path.name)
        return package_path, remote_file_path
    
    def _get_package_size_mb(self, package_path: Path) -> float:
        """Get package size in MB (cached calculation)."""
        return package_path.stat().st_size / 1024 / 1024
    
    def _handle_server_preparation(self, username: str, server: str,
                                  resume: bool, auto_import: bool) -> bool:
        """Handle server preparation.
        
        Returns:
            True if server is prepared, False otherwise
        """
        # Check cache/resume mode
        cache_key = f"{username}@{server}"
        if resume:
            if self._verify_dockertree_installed(username, server):
                log_info("✓ Server already prepared (dockertree found)")
                self._server_prep_cache[cache_key] = True
                return True
        
        if cache_key in self._server_prep_cache and self._server_prep_cache[cache_key]:
            log_info("Server preparation skipped (already prepared)")
            return True
        
        # Auto-import requires server preparation
        if auto_import:
            log_info("Auto-import requires server preparation. Enabling server preparation...")
        
        log_info("Server preparation requested, installing dependencies...")
        if self._prepare_server(username, server):
            self._server_prep_cache[cache_key] = True
            log_info("Server preparation completed successfully")
            return True
        else:
            log_error("Server preparation failed.")
            return False
                
    def _handle_package_transfer(self, package_path: Path, scp_target_obj: SCPTarget) -> bool:
        """Handle package transfer to remote server.
        
        Returns:
            True if successful, False otherwise
        """
        log_info(f"Starting transfer to {scp_target_obj.server}...")
        return self._scp_transfer(package_path, scp_target_obj)
    
    def _handle_remote_import(self, username: str, server: str, remote_file: str,
                             branch_name: str, domain: Optional[str], ip: Optional[str]) -> None:
        """Handle remote import and startup."""
        log_info("Auto-import enabled, running remote import and startup...")
        self._run_remote_import(username, server, remote_file, branch_name, domain, ip)
    
    def _display_next_steps(self, package_name: str, scp_target_obj: SCPTarget,
                           package_size_mb: float, remote_package_path: str,
                           branch_name: str, username: str, server: str) -> None:
        """Display package info and next steps."""
        print_plain(f"\n📦 Package: {package_name}")
        print_plain(f"📁 Remote Location: {scp_target_obj}")
        if package_size_mb > 0:
            print_plain(f"💾 Size: {package_size_mb:.1f} MB")
        print_plain(f"\n📋 Next Steps:")
        print_plain(f"   1. SSH to the server:")
        print_plain(f"      ssh {username}@{server}")
        print_plain(f"   ")
        print_plain(f"   2. Import the package:")
        print_plain(f"      dockertree packages import {remote_package_path} --standalone")
        print_plain(f"   ")
        print_plain(f"   3. Start the services:")
        print_plain(f"      cd <project-directory>")
        print_plain(f"      dockertree start-proxy")
        print_plain(f"      dockertree {branch_name} up -d")
            
    def push_package(self, branch_name: Optional[str], scp_target: Optional[str], 
                    output_dir: Path = None, keep_package: bool = False,
                    auto_import: bool = False, domain: Optional[str] = None,
                    ip: Optional[str] = None, prepare_server: bool = False,
                    dns_token: Optional[str] = None,
                    skip_dns_check: bool = False,
                    create_droplet: bool = False,
                    droplet_name: Optional[str] = None,
                    droplet_region: Optional[str] = None,
                    droplet_size: Optional[str] = None,
                    droplet_image: Optional[str] = None,
                    droplet_ssh_keys: Optional[list] = None,
                    resume: bool = False) -> bool:
        """Export and push package to remote server via SCP.
        
        Args:
            branch_name: Branch/worktree name (optional, auto-detects if not provided)
            scp_target: SCP target in format username@server:path (optional when create_droplet is True)
            output_dir: Temporary package location (default: ./packages)
            keep_package: Don't delete package after successful push
            
        Returns:
            True if successful, False otherwise
        """
        try:
            log_info("Starting push operation...")
            
            # Validate and prepare inputs
            branch_name, scp_target_obj = self._validate_and_prepare_inputs(
                branch_name, scp_target, create_droplet
            )
            if not branch_name:
                return False
            
            # Handle droplet creation if requested
            if create_droplet:
                scp_target_obj = self._handle_droplet_creation(
                    scp_target_obj, branch_name, droplet_name, droplet_region,
                    droplet_size, droplet_image, droplet_ssh_keys, dns_token
                )
                if not scp_target_obj:
                    return False
            elif not scp_target_obj:
                log_error("scp_target is required when --create-droplet is not used")
                return False
            
            username = scp_target_obj.username
            server = scp_target_obj.server
            remote_path = scp_target_obj.remote_path
            
            # Set output directory
            if output_dir is None:
                output_dir = self.project_root / "packages"
            
            # Ensure remote directory exists
            remote_dir = self._infer_remote_directory(remote_path)
            if remote_dir and remote_dir not in ['.', '']:
                self._ensure_remote_dir(username, server, remote_dir)
            
            # Parallelize independent operations: DNS check and package export
            dns_success = True
            package_path = None
            remote_file_path = None
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                
                # Submit DNS management if needed
                if domain and not skip_dns_check:
                    log_info(f"Domain provided: {domain}, managing DNS records...")
                    futures['dns'] = executor.submit(
                        self._handle_dns_management, domain, server, dns_token, create_droplet
                    )
                else:
                    log_info("Skipping DNS management" + (" (--skip-dns-check)" if skip_dns_check else ""))
                
                # Submit package export
                log_info("Starting package export...")
                futures['export'] = executor.submit(
                    self._handle_package_export, branch_name, output_dir, resume, scp_target_obj
                )
                
                # Wait for both to complete
                for future in as_completed(futures.values()):
                    if future == futures.get('dns'):
                        dns_success = future.result()
                        if not dns_success:
                            log_warning("DNS management failed, but continuing with push...")
                    elif future == futures.get('export'):
                        package_path, remote_file_path = future.result()
                        if remote_file_path is None:
                            log_error("Package export failed")
                            return False
            
            # Determine if we need to transfer
            package_already_on_server = (resume and package_path is None and remote_file_path is not None)
            
            # Handle server preparation
            if prepare_server or auto_import:
                if not self._handle_server_preparation(username, server, resume, auto_import):
                    return False
            
            # Transfer package if needed
            if not package_already_on_server and package_path:
                if not self._handle_package_transfer(package_path, scp_target_obj):
                    return False
                log_success(f"Package pushed successfully to {scp_target_obj}")
            
            # Determine final remote package path
            if package_path:
                remote_package_path = scp_target_obj.get_remote_file_path(package_path.name)
                package_name = package_path.name
                package_size_mb = self._get_package_size_mb(package_path)
            else:
                remote_package_path = remote_file_path
                package_name = os.path.basename(remote_package_path) if remote_package_path else "existing package"
                package_size_mb = 0
            
            # Display package info and next steps
            self._display_next_steps(package_name, scp_target_obj, package_size_mb, 
                                   remote_package_path, branch_name, username, server)
            
            # Show server versions after prepare
            if prepare_server:
                self._check_server_requirements(username, server)

            # Handle auto-import if requested
            if auto_import:
                self._handle_remote_import(username, server, remote_package_path, 
                                         branch_name, domain, ip)
            
            # Clean up package unless keep_package is True
            if package_path and not keep_package and package_path.exists():
                log_info("Cleaning up local package file...")
                try:
                    package_path.unlink()
                    log_info(f"Cleaned up local package: {package_path.name}")
                except Exception as e:
                    log_warning(f"Failed to clean up package: {e}")
            
            log_info("Push operation completed successfully")
            return True
            
        except Exception as e:
            log_error(f"Error pushing package: {e}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            # Cleanup SSH connections
            self.ssh_manager.cleanup()
    
    def _detect_current_branch(self) -> Optional[str]:
        """Detect current branch name from working directory.
        
        Returns:
            Branch name if detected, None otherwise
        """
        try:
            # Try to detect execution context (worktree or git root)
            worktree_path, branch_name, is_worktree = detect_execution_context()
            
            if is_worktree and branch_name:
                return branch_name
            
            # Fallback: try git branch --show-current
            try:
                result = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=self.project_root
                )
                branch = result.stdout.strip()
                if branch:
                    return branch
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Fallback: extract from directory name
            current_path = Path.cwd()
            if "worktrees" in str(current_path):
                branch = get_worktree_branch_name(current_path)
                if branch:
                    return branch
            
            return None
            
        except Exception:
            return None
    
    def _scp_transfer(self, package_path: Path, scp_target_obj: SCPTarget) -> bool:
        """Transfer package to remote server via rsync (faster) or SCP (fallback).
        
        Uses rsync with compression for faster transfers, falls back to SCP if rsync unavailable.
        
        Args:
            package_path: Path to package file
            scp_target_obj: SCPTarget object
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure host key is added
            self.ssh_manager.ensure_host_key(scp_target_obj.server)
            
            remote_file_path = scp_target_obj.get_remote_file_path(package_path.name)
            log_info(f"Remote file path: {remote_file_path}")
            
            package_size_mb = self._get_package_size_mb(package_path)
            
            # Try rsync first (faster with compression and progress)
            if subprocess.run(["which", "rsync"], capture_output=True).returncode == 0:
                log_info("Using rsync for faster transfer with compression...")
                log_info(f"Transferring {package_size_mb:.2f} MB package (this may take a while)...")
                
                # Build rsync command with SSH options from manager
                ssh_opts = self.ssh_manager.build_ssh_command(
                    scp_target_obj.username, scp_target_obj.server, use_control_master=True
                )
                # Extract SSH options (skip 'ssh' and target)
                ssh_opts_str = ' '.join(opt for opt in ssh_opts[1:-1] if opt.startswith('-'))
                
                cmd = [
                    "rsync",
                    "-avz",  # archive, verbose, compress
                    "--progress",  # show progress
                    "--partial",  # keep partial transfers
                    "--inplace",  # update in-place for faster completion
                    "-e", f"ssh {ssh_opts_str}" if ssh_opts_str else "ssh",
                    str(package_path),
                    f"{scp_target_obj.username}@{scp_target_obj.server}:{remote_file_path}"
                ]
                log_info(f"Executing rsync command: {' '.join(cmd)}")
                
                # Use Popen for real-time progress output
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                # Stream output for progress
                for line in iter(process.stdout.readline, ''):
                    if line:
                        line = line.rstrip()
                        # Show progress lines
                        if '%' in line or 'speedup' in line.lower():
                            log_info(f"  {line}")
                
                process.wait()
                
                if process.returncode != 0:
                    log_error(f"rsync transfer failed with exit code {process.returncode}")
                    log_info("Falling back to SCP...")
                else:
                    log_success(f"Package transferred successfully via rsync")
                    log_info(f"Transfer completed: {package_path.name} -> {remote_file_path}")
                    return True
            
            # Fallback to SCP with compression
            log_info("Using SCP with compression for transfer...")
            log_info(f"Transferring {package_size_mb:.2f} MB package (this may take a while)...")
            
            scp_cmd = self.ssh_manager.build_scp_command(
                str(package_path),
                f"{scp_target_obj.username}@{scp_target_obj.server}:{remote_file_path}"
            )
            log_info(f"Executing SCP command: {' '.join(scp_cmd)}")
            log_info("Transfer in progress (this may take a while for large packages)...")
            
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown SCP error"
                log_error(f"SCP transfer failed: {error_msg}")
                if result.stdout:
                    log_info(f"SCP stdout: {result.stdout}")
                
                # Provide helpful error messages for common issues
                if "Connection refused" in error_msg or "Could not resolve" in error_msg:
                    log_info("Tip: Check that the server is accessible and SSH is running")
                elif "Permission denied" in error_msg or "Authentication failed" in error_msg:
                    log_info("Tip: Ensure SSH keys are set up or password authentication is enabled")
                elif "No space left" in error_msg or "disk full" in error_msg.lower():
                    log_info("Tip: Free up disk space on the remote server")
                
                return False
            
            log_success(f"Package transferred successfully")
            log_info(f"Transfer completed: {package_path.name} -> {remote_file_path}")
            return True
            
        except FileNotFoundError as e:
            cmd_name = "rsync" if "rsync" in str(e) else "scp"
            log_error(f"{cmd_name} command not found. Please ensure OpenSSH (and optionally rsync) is installed.")
            return False
        except Exception as e:
            log_error(f"Unexpected error during transfer: {e}")
            return False

    def _check_remote_file_exists(self, username: str, server: str, remote_file_path: str) -> bool:
        """Check if a file exists on the remote server.
        
        Args:
            username: SSH username
            server: Server hostname or IP
            remote_file_path: Full path to file on remote server
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            result = self.ssh_manager.execute_remote(
                username, server,
                f"test -f {remote_file_path} && echo EXISTS || echo NOT_FOUND",
                timeout=10,
                check=False
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                return output == "EXISTS"
            return False
        except Exception as e:
            log_warning(f"Failed to check remote file existence: {e}")
            return False
    
    def _find_existing_package(self, username: str, server: str, remote_path: str, branch_name: str) -> Optional[str]:
        """Find an existing dockertree package file on the remote server for the given branch.
        
        Args:
            username: SSH username
            server: Server hostname or IP
            remote_path: Remote directory to search
            branch_name: Branch name to match
            
        Returns:
            Full path to package file if found, None otherwise
        """
        try:
            result = self.ssh_manager.execute_remote(
                username, server,
                f"find {remote_path} -maxdepth 1 -type f -name \"*{branch_name}*.dockertree-package.tar.gz\" 2>/dev/null | head -1",
                timeout=10,
                check=False
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    return output
            return None
        except Exception as e:
            log_warning(f"Failed to search for existing package: {e}")
            return None
    
    def _ensure_remote_dir(self, username: str, server: str, remote_dir: str) -> None:
        """Create the remote directory with mkdir -p (best effort)."""
        try:
            log_info(f"Ensuring remote directory exists: {remote_dir}")
            self.ssh_manager.execute_remote(
                username, server,
                f"mkdir -p {remote_dir}",
                timeout=10,
                check=False
            )
        except Exception as e:
            log_warning(f"Failed to ensure remote directory: {e}")

    def _infer_remote_directory(self, remote_path: str) -> str:
        """Infer the directory to create on the remote side for the given target path.

        If the target looks like a directory (no archive suffix and no filename),
        return it directly; otherwise return its parent directory.
        """
        try:
            # Treat trailing slash as a directory
            if remote_path.endswith('/'):
                return remote_path.rstrip('/')
            # Heuristic: common archive/file suffixes
            lower = remote_path.lower()
            archive_suffixes = ('.tar.gz', '.tgz', '.tar', '.zip')
            if any(lower.endswith(suf) for suf in archive_suffixes):
                return str(Path(remote_path).parent)
            # If there is a dot in the last path segment, assume it's a file
            last = Path(remote_path).name
            if '.' in last:
                return str(Path(remote_path).parent)
            # Otherwise assume it's a directory
            return remote_path
        except Exception:
            return str(Path(remote_path).parent)

    def _check_server_requirements(self, username: str, server: str) -> None:
        """Run a basic non-fatal check for required tools on the server."""
        try:
            log_info("Checking server requirements...")
            self.ssh_manager.execute_remote(
                username, server,
                "set -e; (docker --version || true); (docker compose version || true); (git --version || true); (dockertree --version || true)",
                timeout=30,
                check=False
            )
        except Exception as e:
            log_warning(f"Server requirement check failed: {e}")
    
    def _verify_dockertree_installed(self, username: str, server: str) -> bool:
        """Verify that dockertree is installed on the remote server.
        
        Args:
            username: SSH username
            server: Server hostname or IP
            
        Returns:
            True if dockertree is found, False otherwise
        """
        try:
            result = self.ssh_manager.execute_remote(
                username, server,
                "which dockertree || [ -x /opt/dockertree-venv/bin/dockertree ] || echo NOT_FOUND",
                timeout=10,
                check=False
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and output != "NOT_FOUND":
                    log_info("Verified dockertree is installed on server")
                    return True
                else:
                    return False
                return False
        except Exception as e:
            log_warning(f"Error verifying dockertree installation: {e}")
            return False

    def _prepare_server(self, username: str, server: str) -> bool:
        """Install required dependencies on the remote server non-interactively.

        Installs: curl, git, python3, python3-pip, Docker (Engine + Compose v2),
        and dockertree from GitHub via pip.
        """
        try:
            log_info(f"Preparing server: {username}@{server}")
            log_info("This will install: curl, git, Python 3.11+, Docker, and dockertree")
            log_info("This may take 5-10 minutes depending on server state and network speed...")
            
            # Check if script is cached
            script_name = "dtprep.sh"
            if check_script_cached(username, server, script_name, SERVER_PREP_SCRIPT_VERSION, self.ssh_manager):
                log_info("Server prep script is cached, using cached version")
            else:
                log_info("Server prep script not cached or version mismatch, will transfer")
            
            # Get script from module
            remote_script = get_server_prep_script()
            
            # Build SSH command
            exec_cmd = f"cat > /tmp/{script_name} && chmod +x /tmp/{script_name} && /tmp/{script_name} && rm -f /tmp/{script_name}"
            ssh_cmd = self.ssh_manager.build_ssh_command(username, server, exec_cmd)
            
            # Execute with streaming
            success, stdout_lines, stderr_lines = execute_with_streaming(
                ssh_cmd,
                script=remote_script,
                timeout=600,  # 10 minutes
                progress_interval=30,
                prefix="  ",
                filter_keywords=['error', 'failed', 'success', 'installing', 'completed']
            )
            
            if success:
                # Mark script as cached
                mark_script_cached(username, server, script_name, SERVER_PREP_SCRIPT_VERSION, self.ssh_manager)
                log_info("Server preparation script completed successfully")
                return True
            else:
                log_error("Remote preparation failed")
                if stderr_lines:
                    log_error("Server preparation errors:")
                    for line in stderr_lines[-20:]:  # Show last 20 lines
                        log_error(f"  {line}")
                return False
                
        except Exception as e:
            log_error(f"Error preparing server: {e}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")
            return False

    def _run_remote_import(self, username: str, server: str, remote_file: str, branch_name: str,
                           domain: Optional[str], ip: Optional[str]) -> None:
        """Run remote import and start services via SSH using streaming utilities."""
        try:
            log_info("Composing remote import script...")
            script = compose_remote_import_script(
                remote_file=remote_file,
                branch_name=branch_name,
                domain=domain,
                ip=ip,
            )
            
            exec_cmd = "cat > /tmp/dtrun.sh && chmod +x /tmp/dtrun.sh && /tmp/dtrun.sh && rm -f /tmp/dtrun.sh"
            ssh_cmd = self.ssh_manager.build_ssh_command(username, server, exec_cmd)
            
            log_info("Executing remote import and startup script...")
            log_info("This will: import package, start proxy, and bring up the worktree environment")
            
            # Execute with streaming
            success, stdout_lines, stderr_lines = execute_with_streaming(
                ssh_cmd,
                script=script,
                timeout=1800,  # 30 minutes
                progress_interval=30,
                prefix="[REMOTE] ",
                filter_keywords=['error', 'failed', 'success', 'starting', 'completed', 'timeout', 'import']
            )
            
            if success:
                log_success("Remote import script completed successfully")
            else:
                log_error("Remote import script returned non-zero exit code")
                if stderr_lines:
                    log_error("Remote import errors:")
                    for line in stderr_lines[-30:]:  # Show last 30 lines
                        log_error(f"  {line}")
                        
        except Exception as e:
            log_error(f"Remote import failed: {e}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")

    def _handle_dns_management(self, domain: str, server: str, 
                               dns_token: Optional[str] = None,
                               create_droplet: bool = False) -> bool:
        """Handle DNS management for domain deployment using Digital Ocean DNS.
        
        Args:
            domain: Full domain name (e.g., 'app.example.com')
            server: Server hostname or IP
            dns_token: Digital Ocean API token
            create_droplet: Whether a new droplet was created (auto-updates DNS if True)
            
        Returns:
            True if DNS is configured successfully, False otherwise
        """
        try:
            log_info(f"Starting DNS management for domain: {domain}")
            
            # Validate domain format
            log_info("Validating domain format...")
            if not is_domain(domain):
                log_error(f"Invalid domain format: {domain}")
                return False
            
            # Parse domain into components
            try:
                subdomain, base_domain = parse_domain(domain)
                log_info(f"Parsed domain - Subdomain: {subdomain}, Base Domain: {base_domain}")
            except ValueError as e:
                log_error(str(e))
                return False
            
            # Resolve API token
            log_info("Resolving DNS API token...")
            api_token = DNSManager.resolve_dns_token(dns_token)
            if not api_token:
                log_error("DNS API token not found. Set DIGITALOCEAN_API_TOKEN or DNS_API_TOKEN environment variable, or use --dns-token")
                return False
            log_info("DNS API token resolved successfully")
            
            # Create Digital Ocean provider instance
            log_info("Creating Digital Ocean DNS provider...")
            provider = DNSManager.create_provider('digitalocean', api_token)
            if not provider:
                log_error("Failed to create DNS provider")
                return False
            log_info("DNS provider created successfully")
            
            log_info(f"Checking DNS records for {domain}...")
            
            # Check if domain exists
            exists, current_ip = provider.check_domain_exists(subdomain, base_domain)
            log_info(f"DNS record exists: {exists}, Current IP: {current_ip}")
            
            # Extract server IP from server string (could be hostname or IP)
            log_info(f"Resolving server IP for: {server}")
            server_ip = self._resolve_server_ip(server)
            log_info(f"Server IP resolved to: {server_ip}")
            
            if exists:
                if current_ip == server_ip:
                    log_success(f"DNS record already exists and points to {server_ip}")
                    log_info("No DNS changes needed")
                    return True
                else:
                    log_warning(f"DNS record exists but points to {current_ip} (expected {server_ip})")
                    
                    # Auto-update DNS when creating new droplet (automated deployment)
                    if create_droplet:
                        log_info(f"Auto-updating DNS for new droplet: {domain} -> {server_ip}")
                        log_info(f"Updating DNS A record: {domain} -> {server_ip}")
                        if provider.update_subdomain(subdomain, base_domain, server_ip):
                            log_success(f"DNS record updated successfully: {domain} -> {server_ip}")
                            
                            # Verify on authoritative nameservers
                            log_info("Verifying DNS record on authoritative nameservers...")
                            if self._verify_dns_on_authoritative(domain, server_ip):
                                log_info("DNS record verified on Digital Ocean nameservers")
                            else:
                                log_warning("DNS record updated but not yet visible on nameservers (may take a few seconds)")
                            
                            return True
                        else:
                            log_error("Failed to update DNS record")
                            return False
                    else:
                        # Manual deployment: ask for confirmation
                        if confirm_action(f"Update DNS record to point to {server_ip}?"):
                            log_info(f"Updating DNS A record: {domain} -> {server_ip}")
                            if provider.update_subdomain(subdomain, base_domain, server_ip):
                                log_success(f"DNS record updated successfully: {domain} -> {server_ip}")
                                
                                # Verify on authoritative nameservers
                                log_info("Verifying DNS record on authoritative nameservers...")
                                if self._verify_dns_on_authoritative(domain, server_ip):
                                    log_info("DNS record verified on Digital Ocean nameservers")
                                else:
                                    log_warning("DNS record updated but not yet visible on nameservers (may take a few seconds)")
                                
                                return True
                            else:
                                log_error("Failed to update DNS record")
                                return False
                        else:
                            log_info("Continuing with existing DNS configuration...")
                            return True
            else:
                # Domain doesn't exist, auto-create it
                log_info(f"No DNS record found for {domain}")
                log_info(f"Creating DNS A record: {domain} -> {server_ip}")
                log_info("Sending DNS creation request to Digital Ocean API...")
                if provider.create_subdomain(subdomain, base_domain, server_ip):
                    log_success(f"DNS record created successfully: {domain} -> {server_ip}")
                    
                    # Verify on authoritative nameservers
                    log_info("Verifying DNS record on authoritative nameservers...")
                    if self._verify_dns_on_authoritative(domain, server_ip):
                        log_info("DNS record verified on Digital Ocean nameservers")
                    else:
                        log_warning("DNS record created but not yet visible on nameservers (may take a few seconds)")
                    
                    # Provide helpful information about propagation
                    log_info("")
                    log_info("DNS Propagation Information:")
                    log_info("  - DNS propagation typically takes 5-60 minutes to reach all resolvers")
                    log_info("  - The record is immediately available on Digital Ocean nameservers")
                    log_info("  - You can verify on authoritative nameservers:")
                    log_info(f"    dig {domain} A @ns1.digitalocean.com")
                    log_info("  - Public resolvers (8.8.8.8, 1.1.1.1) may take longer to update")
                    log_info("")
                    return True
                else:
                    log_error("Failed to create DNS record")
                    return False
                    
        except Exception as e:
            log_error(f"DNS management error: {e}")
            return False
    
    def _verify_dns_on_authoritative(self, domain: str, expected_ip: str) -> bool:
        """Verify DNS record exists on Digital Ocean authoritative nameservers.
        
        Args:
            domain: Domain name to check
            expected_ip: Expected IP address
            
        Returns:
            True if record exists and matches expected IP, False otherwise
        """
        try:
            import subprocess
            # Query Digital Ocean nameservers directly
            nameservers = ['ns1.digitalocean.com', 'ns2.digitalocean.com', 'ns3.digitalocean.com']
            
            for ns in nameservers:
                try:
                    result = subprocess.run(
                        ['dig', '+short', domain, 'A', f'@{ns}'],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False
                    )
                    if result.returncode == 0:
                        ip = result.stdout.strip()
                        if ip == expected_ip:
                            return True
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    # dig not available or timeout, continue to next nameserver
                    continue
            
            return False
        except Exception:
            # If verification fails, don't block the operation
            return False
    
    def _resolve_server_ip(self, server: str) -> str:
        """Resolve server hostname to IP address (with caching).
        
        Args:
            server: Server hostname or IP address
            
        Returns:
            IP address string
        """
        # Check cache first
        if server in self._ip_cache:
            return self._ip_cache[server]
        
        # Check if it's already an IP address
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', server):
            self._ip_cache[server] = server
            return server
        
        # Try to resolve hostname
        try:
            ip = socket.gethostbyname(server)
            log_info(f"Resolved {server} to {ip}")
            self._ip_cache[server] = ip
            return ip
        except socket.gaierror:
            log_warning(f"Could not resolve {server} to IP, using as-is")
            self._ip_cache[server] = server
            return server
    
    def _resolve_ssh_keys(self, provided_keys: Optional[list], defaults: dict, provider) -> Optional[list]:
        """Resolve SSH keys for droplet creation.
        
        Checks in order:
        1. Provided keys (from CLI flag)
        2. Default keys from environment
        3. Auto-detect first available key from Digital Ocean account
        
        Args:
            provided_keys: SSH keys provided via CLI flag
            defaults: Default values from environment
            provider: Digital Ocean provider instance
            
        Returns:
            List of SSH key names, or None if no keys found
        """
        # Use provided keys if available
        if provided_keys:
            log_info(f"Using provided SSH keys: {', '.join(provided_keys)}")
            return provided_keys
        
        # Check defaults from environment
        default_keys = defaults.get('ssh_keys', [])
        if default_keys:
            log_info(f"Using default SSH keys from environment: {', '.join(default_keys)}")
            return default_keys
        
        # Auto-detect: get first available SSH key from Digital Ocean account
        try:
            ssh_keys_list = provider.list_ssh_keys()
            if ssh_keys_list:
                # Get the first key's name
                first_key = ssh_keys_list[0]
                key_name = first_key.get('name', 'unnamed')
                log_info(f"Auto-detected SSH key: {key_name} (no keys specified, using first available)")
                return [key_name]
            else:
                log_warning("No SSH keys found in Digital Ocean account")
                return None
        except Exception as e:
            log_warning(f"Failed to list SSH keys from Digital Ocean: {e}")
            return None
    
    def _create_droplet_for_push(self, droplet_name: str,
                                 droplet_region: Optional[str] = None,
                                 droplet_size: Optional[str] = None,
                                 droplet_image: Optional[str] = None,
                                 droplet_ssh_keys: Optional[list] = None,
                                 api_token: Optional[str] = None):
        """Create a droplet for push deployment.
        
        Always waits for the droplet to be ready before returning, as the push
        operation requires the droplet IP address and SSH access.
        
        Args:
            droplet_name: Name for the droplet
            droplet_region: Droplet region
            droplet_size: Droplet size
            droplet_image: Droplet image
            droplet_ssh_keys: List of SSH key IDs or fingerprints
            api_token: Digital Ocean API token
            
        Returns:
            DropletInfo if successful, None otherwise
        """
        try:
            log_info("Starting droplet creation process...")
            
            # Resolve API token
            log_info("Resolving Digital Ocean API token...")
            token = DropletManager.resolve_droplet_token(api_token)
            if not token:
                log_error("Digital Ocean API token not found. Set DIGITALOCEAN_API_TOKEN or DNS_API_TOKEN environment variable, or use --dns-token")
                return None
            log_info("API token resolved successfully")
            
            # Get defaults from environment
            log_info("Loading droplet defaults from environment...")
            defaults = DropletManager.get_droplet_defaults()
            
            # Use provided values or defaults
            region = droplet_region or defaults.get('region', 'nyc1')
            size = droplet_size or defaults.get('size', 's-1vcpu-1gb')
            image = droplet_image or defaults.get('image', 'ubuntu-22-04-x64')
            
            log_info(f"Droplet configuration:")
            log_info(f"  Name: {droplet_name}")
            log_info(f"  Region: {region}")
            log_info(f"  Size: {size}")
            log_info(f"  Image: {image}")
            
            # Create provider (needed for SSH key resolution)
            log_info("Creating Digital Ocean provider...")
            provider = DropletManager.create_provider('digitalocean', token)
            if not provider:
                log_error("Failed to create droplet provider")
                return None
            log_info("Provider created successfully")
            
            # Resolve SSH keys (required for droplet creation)
            log_info("Resolving SSH keys for droplet...")
            ssh_keys = self._resolve_ssh_keys(droplet_ssh_keys, defaults, provider)
            if not ssh_keys:
                log_error("No SSH keys specified. Use --droplet-ssh-keys or set DROPLET_DEFAULT_SSH_KEYS environment variable.")
                return None
            log_info(f"SSH keys resolved: {', '.join(ssh_keys)}")
            
            log_info(f"Creating droplet: {droplet_name}")
            log_info("Sending droplet creation request to Digital Ocean API...")
            
            # Create droplet
            droplet = provider.create_droplet(
                name=droplet_name,
                region=region,
                size=size,
                image=image,
                ssh_keys=ssh_keys if ssh_keys else None,
                tags=None
            )
            
            if not droplet:
                log_error("Failed to create droplet")
                return None
            
            log_success(f"Droplet created: {droplet_name} (ID: {droplet.id})")
            
            # Always wait for droplet to be ready (required for push operation)
            log_info("Waiting for droplet to be ready (this may take 1-2 minutes)...")
            log_info("Checking droplet status and SSH availability...")
            if not provider.wait_for_droplet_ready(droplet.id, check_ssh=True):
                log_error("Droplet created but not ready within timeout. Cannot proceed with push.")
                return None
            
            log_info("Droplet is ready and SSH is accessible")
            
            # Refresh droplet info to get IP address
            log_info("Refreshing droplet information to get IP address...")
            droplet = provider.get_droplet(droplet.id)
            
            if droplet and droplet.ip_address:
                log_success(f"Droplet IP address: {droplet.ip_address}")
                log_info("Adding SSH host key for new droplet...")
                # Add SSH host key for the new droplet
                self.ssh_manager.ensure_host_key(droplet.ip_address)
                log_info("SSH host key added successfully")
            else:
                log_error("Droplet IP address not available. Cannot proceed with push.")
                return None
            
            log_info("Droplet creation process completed")
            return droplet
            
        except Exception as e:
            log_error(f"Error creating droplet: {e}")
            return None

