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
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, List

from ..core.package_manager import PackageManager
from ..core.dns_manager import DNSManager, parse_domain, is_domain
from ..core.droplet_manager import DropletManager, DropletInfo
# Import DNS providers to trigger registration
from ..core import dns_providers  # noqa: F401
from ..utils.logging import log_info, log_success, log_warning, log_error, print_plain, is_verbose
from ..utils.path_utils import detect_execution_context, get_worktree_branch_name
from ..utils.confirmation import confirm_action
from ..utils.ssh_utils import add_ssh_host_key
from ..utils.streaming import execute_with_streaming


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
                    resume: bool = False,
                    code_only: bool = False,
                    build: bool = False,
                    containers: Optional[str] = None,
                    exclude_deps: Optional[List[str]] = None,
                    vpc_uuid: Optional[str] = None,
                    droplet_info: Optional[DropletInfo] = None,
                    central_droplet_info: Optional[DropletInfo] = None) -> bool:
        """Export and push package to remote server via SCP.
        
        Args:
            branch_name: Branch/worktree name (optional, auto-detects if not provided)
            scp_target: SCP target in format username@server:path (optional when create_droplet is True)
            output_dir: Temporary package location (default: ./packages)
            keep_package: Don't delete package after successful push
            containers: Optional comma-separated list of 'worktree.container' patterns
                       to push only specific containers and their volumes
            
        Returns:
            True if successful, False otherwise
        """
        try:
            log_info("Starting push operation...")
            
            # Handle code-only push
            if code_only:
                if output_dir is None:
                    output_dir = self.project_root / "packages"
                return self._push_code_only(branch_name, scp_target, domain, ip, output_dir, build)
            
            # Auto-detect branch name if not provided
            if not branch_name:
                log_info("Branch name not provided, attempting auto-detection...")
                branch_name = self._detect_current_branch()
                if not branch_name:
                    log_error("Could not detect branch name. Please specify branch_name.")
                    return False
                log_info(f"Auto-detected branch: {branch_name}")
            else:
                log_info(f"Using provided branch name: {branch_name}")
            
            # Validate and parse SCP target (required)
            if not scp_target:
                log_error("scp_target is required")
                return False
            
            # Validate SCP target format
            log_info(f"Validating SCP target format: {scp_target}")
            if not self._validate_scp_target(scp_target):
                log_error(f"Invalid SCP target format: {scp_target}")
                log_info("Expected format: username@server:path")
                return False
            log_info("SCP target format is valid")
            
            # Parse SCP target
            username, server, remote_path = self._parse_scp_target(scp_target)
            log_info(f"Parsed SCP target - Username: {username}, Server: {server}, Remote Path: {remote_path}")
            
            # Handle DNS management if domain is provided
            if domain and not skip_dns_check:
                log_info(f"Domain provided: {domain}, managing DNS records...")
                dns_success = self._handle_dns_management(domain, server, dns_token, False)
                if not dns_success:
                    log_warning("DNS management failed, but continuing with push...")
            elif skip_dns_check:
                log_info("DNS check skipped (--skip-dns-check flag)")
            else:
                log_info("No domain provided, skipping DNS management")
            
            # Export package with --include-code (required for production deployments)
            if output_dir is None:
                output_dir = self.project_root / "packages"
            
            log_info(f"Exporting package for branch: {branch_name}")
            log_info(f"Output directory: {output_dir}")
            log_info("Package will include code and be compressed for faster transfer")
            log_info("This includes: environment files, volume backups, and code archive")
            
            # Check if worktree exists before export
            from ..core.git_manager import GitManager
            git_manager = GitManager(project_root=self.project_root, validate=False)
            if not git_manager.validate_worktree_exists(branch_name):
                log_error(f"Worktree for branch '{branch_name}' does not exist")
                log_info("Available worktrees:")
                worktrees = git_manager.list_worktrees()
                for wt in worktrees:
                    log_info(f"  - {wt}")
                return False
            
            # Ensure remote directory exists
            remote_dir = self._infer_remote_directory(remote_path)
            log_info(f"Inferred remote directory: {remote_dir}")
            if remote_dir and remote_dir not in ['.', '']:
                log_info(f"Ensuring remote directory exists: {remote_dir}")
                self._ensure_remote_dir(username, server, remote_dir)
            else:
                log_info("Remote directory is current directory, skipping directory creation")

            # Resume mode: detect what's already done (check BEFORE export)
            package_already_on_server = False
            server_already_prepared = False
            remote_file_path = None
            package_path = None
            
            if resume:
                log_info("Resume mode enabled: checking what's already completed...")
                
                # Check if server is already prepared
                if self._verify_dockertree_installed(username, server):
                    server_already_prepared = True
                    log_info("✓ Server already prepared (dockertree found)")
                    log_info("Skipping server preparation...")
                else:
                    log_info("Server not prepared, will prepare if needed")
                
                # Try to find existing package on server
                found_package = self._find_existing_package(username, server, remote_path, branch_name)
                if found_package:
                    remote_file_path = found_package
                    package_already_on_server = True
                    log_info(f"✓ Found existing package on server: {found_package}")
                    log_info("Skipping package export and transfer...")
                else:
                    log_info("No existing package found on server, will export and transfer")
            
            # Parse container filter if provided
            container_filter = None
            if containers:
                log_info(f"Parsing container selection: {containers}")
                try:
                    from ..utils.container_selector import parse_container_selection
                    container_filter = parse_container_selection(containers, self.project_root)
                    log_info(f"Selected {len(container_filter)} container(s) for export")
                    for selection in container_filter:
                        log_info(f"  - {selection['worktree']}.{selection['container']}")
                    log_info("Service filtering enabled: compose file will be filtered to include only selected services and dependencies")
                    if exclude_deps:
                        log_info(f"Excluding services from dependencies: {', '.join(exclude_deps)}")
                except ValueError as e:
                    log_error(f"Invalid container selection: {e}")
                    return False
            
            # Export package only if not already on server
            if not package_already_on_server:
                log_info("Worktree validated, proceeding with export...")
                export_result = self.package_manager.export_package(
                    branch_name=branch_name,
                    output_dir=output_dir,
                    include_code=True,  # Always include code for deployments
                    compressed=True,    # Always compress for faster transfer
                    container_filter=container_filter,
                    exclude_deps=exclude_deps,
                    droplet_info=droplet_info,
                    central_droplet_info=central_droplet_info
                )
                
                if not export_result.get("success"):
                    log_error(f"Failed to export package: {export_result.get('error')}")
                    return False
                
                package_path = Path(export_result.get("package_path"))
                log_info(f"Package exported successfully: {package_path}")
                if not package_path.exists():
                    log_error(f"Package file not found: {package_path}")
                    return False
                
                package_size_mb = package_path.stat().st_size / 1024 / 1024
                log_success(f"Package size: {package_size_mb:.2f} MB")
                
                # Log package metadata if available
                metadata = export_result.get("metadata", {})
                if metadata:
                    log_info("Package metadata:")
                    log_info(f"  - Branch: {metadata.get('branch_name', 'unknown')}")
                    log_info(f"  - Project: {metadata.get('project_name', 'unknown')}")
                    log_info(f"  - Includes code: {metadata.get('include_code', False)}")
                    log_info(f"  - Volumes skipped: {metadata.get('skip_volumes', False)}")
            else:
                # Extract package name from remote path for display
                if remote_file_path:
                    package_name = os.path.basename(remote_file_path)
                    log_info(f"Using existing package: {package_name}")
            
            # Auto-import requires server preparation
            if auto_import and not prepare_server and not server_already_prepared:
                log_info("Auto-import requires server preparation. Enabling --prepare-server...")
                prepare_server = True

            # Prepare server dependencies if requested (before upload/import)
            if prepare_server and not server_already_prepared:
                log_info("Server preparation requested, installing dependencies...")
                log_info("This may take several minutes depending on server state...")
                ok = self._prepare_server(username, server)
                if not ok:
                    log_error("Server preparation failed. Aborting push.")
                    return False
                log_info("Server preparation completed successfully")
                
                # Verify dockertree is installed (required for auto-import)
                if auto_import:
                    log_info("Verifying dockertree installation on server...")
                    if not self._verify_dockertree_installed(username, server):
                        log_error("dockertree not found on server. Server preparation may have failed.")
                        return False
            elif server_already_prepared:
                log_info("Server preparation skipped (already prepared)")
            else:
                log_info("Server preparation skipped (--prepare-server not specified)")

            # Transfer package via SCP (skip if already on server in resume mode)
            if not (resume and package_already_on_server):
                if not package_path:
                    log_error("Package path not available for transfer")
                    return False
                log_info(f"Starting SCP transfer to {server}...")
                log_info(f"Source: {package_path}")
                log_info(f"Destination: {scp_target}")
                if not self._scp_transfer(package_path, scp_target):
                    log_error("Failed to transfer package to remote server")
                    return False
                
                log_success(f"Package pushed successfully to {scp_target}")
                log_info("SCP transfer completed")
            else:
                log_info(f"Package already on server, skipping transfer")
            
            # Determine remote package path for import
            if resume and package_already_on_server and remote_file_path:
                remote_package_path = remote_file_path
            elif package_path:
                remote_package_path = f"{remote_path}/{package_path.name}"
            else:
                log_error("Cannot determine remote package path")
                return False
            
            # Display package info and next steps
            if package_path:
                package_size_mb = package_path.stat().st_size / 1024 / 1024
                package_name = package_path.name
            else:
                # In resume mode with existing package
                package_name = os.path.basename(remote_package_path) if remote_package_path else "existing package"
                package_size_mb = 0  # Size unknown for existing package
            
            print_plain(f"\n📦 Package: {package_name}")
            print_plain(f"📁 Remote Location: {scp_target}")
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
            
            # Optional: show server versions after prepare
            if prepare_server:
                log_info("Checking server requirements and versions...")
                self._check_server_requirements(username, server)

            # Optional: auto import on server
            if auto_import:
                log_info("Auto-import enabled, running remote import and startup...")
                log_info(f"Remote package path: {remote_package_path}")
                log_info(f"Branch name: {branch_name}")
                if domain:
                    log_info(f"Domain override: {domain}")
                if ip:
                    log_info(f"IP override: {ip}")
                self._run_remote_import(
                    username,
                    server,
                    remote_package_path,
                    branch_name,
                    domain,
                    ip,
                    build=build,
                )
                log_info("Remote import process initiated")
                
                # Configure VPC firewall if enabled and droplet info is available
                if droplet_info:
                    self._configure_vpc_firewall(username, server, droplet_info)
            else:
                log_info("Auto-import disabled, manual import required")
                if build:
                    log_warning("Build flag specified but auto-import disabled. Run 'dockertree "
                                f"{branch_name} build' on the server after importing.")

            # Clean up package unless keep_package is True (only if we created it locally)
            if package_path and not keep_package and package_path.exists():
                log_info("Cleaning up local package file...")
                try:
                    package_path.unlink()
                    log_info(f"Cleaned up local package: {package_path.name}")
                except Exception as e:
                    log_warning(f"Failed to clean up package: {e}")
            elif package_path:
                log_info(f"Keeping local package (--keep-package flag or file not found)")
            
            log_info("Push operation completed successfully")
            
            # Save push configuration for future use (both full and code-only)
            from ..core.environment_manager import EnvironmentManager
            env_manager = EnvironmentManager(project_root=self.project_root)
            # Parse final scp_target to save
            username, server, remote_path = self._parse_scp_target(scp_target)
            final_scp_target = scp_target
            env_manager.save_push_config(
                branch_name,
                final_scp_target,
                domain,
                ip
            )
            
            return True
            
        except Exception as e:
            log_error(f"Error pushing package: {e}")
            return False
    
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
    
    def _validate_scp_target(self, scp_target: str) -> bool:
        """Validate SCP target format.
        
        Args:
            scp_target: SCP target string
            
        Returns:
            True if valid format, False otherwise
        """
        # Pattern: username@host:path
        pattern = r'^[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+:.+$'
        return bool(re.match(pattern, scp_target))
    
    def _parse_scp_target(self, scp_target: str) -> Tuple[str, str, str]:
        """Parse SCP target into components.
        
        Args:
            scp_target: SCP target in format username@server:path
            
        Returns:
            Tuple of (username, server, remote_path)
        """
        # Split at @ to get username and server:path
        parts = scp_target.split('@', 1)
        username = parts[0]
        
        # Split server:path at :
        server_path = parts[1].split(':', 1)
        server = server_path[0]
        remote_path = server_path[1] if len(server_path) > 1 else '.'
        
        return username, server, remote_path
    
    def _scp_transfer(self, package_path: Path, scp_target: str) -> bool:
        """Transfer package to remote server via rsync (faster) or SCP (fallback).
        
        Uses rsync with compression for faster transfers, falls back to SCP if rsync unavailable.
        
        Args:
            package_path: Path to package file
            scp_target: SCP target in format username@server:path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Add SSH host key before transfer
            username, server, _ = self._parse_scp_target(scp_target)
            log_info(f"Adding SSH host key for {server}...")
            add_ssh_host_key(server)
            
            remote_file_path = f"{scp_target}/{package_path.name}" if not scp_target.endswith('/') else f"{scp_target}{package_path.name}"
            log_info(f"Remote file path: {remote_file_path}")
            
            # Try rsync first (faster with compression and progress)
            if subprocess.run(["which", "rsync"], capture_output=True).returncode == 0:
                log_info("Using rsync for faster transfer with compression...")
                package_size_mb = package_path.stat().st_size / 1024 / 1024
                log_info(f"Transferring {package_size_mb:.2f} MB package (this may take a while)...")
                
                # rsync with compression, progress, and partial transfer support
                cmd = [
                    "rsync",
                    "-avz",  # archive, verbose, compress
                    "--progress",  # show progress
                    "--partial",  # keep partial transfers
                    "--inplace",  # update in-place for faster completion
                    "-e", "ssh -o StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
                    str(package_path),
                    remote_file_path
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
                    # Fall through to SCP fallback
                else:
                    log_success(f"Package transferred successfully via rsync")
                    log_info(f"Transfer completed: {package_path.name} -> {remote_file_path}")
                    return True
            
            # Fallback to SCP with compression
            log_info("Using SCP with compression for transfer...")
            package_size_mb = package_path.stat().st_size / 1024 / 1024
            log_info(f"Transferring {package_size_mb:.2f} MB package (this may take a while)...")
            
            cmd = [
                "scp",
                "-C",  # Enable compression
                "-o", "StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
                str(package_path),
                remote_file_path
            ]
            log_info(f"Executing SCP command: {' '.join(cmd)}")
            log_info("Transfer in progress (this may take a while for large packages)...")
            
            result = subprocess.run(
                cmd,
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
            # Add SSH host key before connection
            add_ssh_host_key(server)
            
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
                f"{username}@{server}",
                f"bash -lc 'test -f {remote_file_path} && echo EXISTS || echo NOT_FOUND'"
            ]
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=10
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
            # Add SSH host key before connection
            add_ssh_host_key(server)
            
            # Search for dockertree package files matching the branch name
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
                f"{username}@{server}",
                f"bash -lc 'find {remote_path} -maxdepth 1 -type f -name \"*{branch_name}*.dockertree-package.tar.gz\" 2>/dev/null | head -1'"
            ]
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=10
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
            # Add SSH host key before connection
            add_ssh_host_key(server)
            
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
                f"{username}@{server}",
                f"bash -lc 'mkdir -p {remote_dir}'"
            ]
            log_info(f"Ensuring remote directory exists: {remote_dir}")
            subprocess.run(cmd, check=False, capture_output=True, text=True)
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
            cmd = [
                "ssh", f"{username}@{server}",
                "bash -lc \"set -e; (docker --version || true); (docker compose version || true); (git --version || true); (dockertree --version || true)\""
            ]
            log_info("Checking server requirements...")
            subprocess.run(cmd, check=False)
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
            # Check for dockertree in common locations
            cmd = [
                "ssh", f"{username}@{server}",
                "bash -lc 'which dockertree || [ -x /opt/dockertree-venv/bin/dockertree ] || echo NOT_FOUND'"
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and output != "NOT_FOUND":
                    log_info("Verified dockertree is installed on server")
                    return True
                else:
                    log_error("dockertree not found in PATH or /opt/dockertree-venv/bin/")
                    return False
            else:
                log_warning(f"Failed to verify dockertree installation: {result.stderr}")
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
            
            # Add SSH host key before connection
            log_info("Adding SSH host key...")
            add_ssh_host_key(server)
            remote_script = r'''
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo "[PREP] Detecting distribution..."
if [ -f /etc/os-release ]; then . /etc/os-release; else ID=unknown; fi

# Choose package manager commands
if command -v apt-get >/dev/null 2>&1; then
  PKG_UPDATE='apt-get -y -qq update'
  PKG_INSTALL='apt-get -y -qq install'
  USE_APT=true
elif command -v dnf >/dev/null 2>&1; then
  PKG_UPDATE='dnf -y makecache'
  PKG_INSTALL='dnf install -y -q'
  USE_APT=false
elif command -v yum >/dev/null 2>&1; then
  PKG_UPDATE='yum -y makecache'
  PKG_INSTALL='yum install -y -q'
  USE_APT=false
else
  echo "[PREP] Unsupported distro: cannot find apt/dnf/yum" >&2
  exit 1
fi

# Function to wait for apt lock release (max 60s)
wait_for_apt_lock() {
  if [ "$USE_APT" != "true" ]; then
    return 0
  fi
  
  local max_wait=60
  local waited=0
  local check_interval=2
  
  # Check if unattended-upgrades is running
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet unattended-upgrades 2>/dev/null; then
      echo "[PREP] unattended-upgrades is running, waiting up to ${max_wait}s for it to complete..." >&2
      while [ $waited -lt $max_wait ]; do
        if ! systemctl is-active --quiet unattended-upgrades 2>/dev/null; then
          echo "[PREP] unattended-upgrades completed" >&2
          break
        fi
        sleep $check_interval
        waited=$((waited + check_interval))
      done
    fi
  fi
  
  # Wait for apt locks to be released
  while [ $waited -lt $max_wait ]; do
    if lsof /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || [ -f /var/lib/apt/lists/lock ]; then
      sleep $check_interval
      waited=$((waited + check_interval))
    else
      break
    fi
  done
  
  if [ $waited -ge $max_wait ]; then
    echo "[PREP] Warning: Apt lock still present after ${max_wait}s, proceeding anyway..." >&2
  fi
}

# Retry function for apt operations with improved lock detection
apt_retry() {
  local cmd="$1"
  local max_attempts=5
  local attempt=1
  local wait_times=(2 5 10 20 30)  # Reduced wait times
  
  while [ $attempt -le $max_attempts ]; do
    # Try to run the command first
    if sh -lc "$cmd" 2>/dev/null; then
      return 0
    fi
    
    # Only check for locks on actual failures
    if [ $attempt -lt $max_attempts ]; then
      if [ "$USE_APT" = "true" ]; then
        # Check if failure was due to lock
        if lsof /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || [ -f /var/lib/apt/lists/lock ]; then
          local wait_time=${wait_times[$((attempt-1))]}
          echo "[PREP] Apt lock detected after command failure, waiting ${wait_time}s before retry (attempt ${attempt}/${max_attempts})..." >&2
          sleep $wait_time
        else
          # No lock, but command failed - wait shorter time
          local wait_time=${wait_times[$((attempt-1))]}
          echo "[PREP] Command failed, waiting ${wait_time}s before retry (attempt ${attempt}/${max_attempts})..." >&2
          sleep $wait_time
        fi
      else
        # Non-apt system, just wait
        local wait_time=${wait_times[$((attempt-1))]}
        echo "[PREP] Command failed, waiting ${wait_time}s before retry (attempt ${attempt}/${max_attempts})..." >&2
        sleep $wait_time
      fi
      attempt=$((attempt+1))
    else
      echo "[PREP] Command failed after ${max_attempts} attempts" >&2
      return 1
    fi
  done
}

# Wait for droplet initialization intelligently
if [ "$USE_APT" = "true" ]; then
  echo "[PREP] Checking droplet initialization status..."
  # Wait for apt locks and unattended-upgrades if needed
  wait_for_apt_lock
  echo "[PREP] Droplet initialization check complete"
fi

echo "[PREP] Installing base tools (curl git)..."
apt_retry "$PKG_UPDATE" || true
apt_retry "$PKG_INSTALL curl git" || true

# Configure firewall to allow HTTP, HTTPS, and SSH
echo "[PREP] Configuring firewall..."
if command -v ufw >/dev/null 2>&1; then
  # UFW is available
  if ufw status | grep -q "Status: active"; then
    echo "[PREP] UFW is active, ensuring ports are open..."
    ufw allow 22/tcp comment 'SSH' || true
    ufw allow 80/tcp comment 'HTTP' || true
    ufw allow 443/tcp comment 'HTTPS' || true
  else
    echo "[PREP] UFW is inactive, enabling and configuring..."
    ufw --force enable || true
    ufw default allow outgoing || true
    ufw default deny incoming || true
    ufw allow 22/tcp comment 'SSH' || true
    ufw allow 80/tcp comment 'HTTP' || true
    ufw allow 443/tcp comment 'HTTPS' || true
  fi
  echo "[PREP] UFW status:"
  ufw status verbose || true
elif command -v iptables >/dev/null 2>&1; then
  # Fallback to iptables if ufw not available
  echo "[PREP] Configuring iptables for HTTP/HTTPS/SSH..."
  # Allow SSH (port 22)
  iptables -C INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 22 -j ACCEPT || true
  # Allow HTTP (port 80)
  iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 80 -j ACCEPT || true
  # Allow HTTPS (port 443)
  iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 443 -j ACCEPT || true
  # Save iptables rules if iptables-persistent is available
  if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save || true
  elif command -v iptables-save >/dev/null 2>&1 && [ -w /etc/iptables/rules.v4 ]; then
    iptables-save > /etc/iptables/rules.v4 || true
  fi
  echo "[PREP] iptables rules configured"
else
  echo "[PREP] Warning: No firewall tool (ufw/iptables) found. Ports may need manual configuration." >&2
fi

# Install Python 3.11+ (required for dockertree)
echo "[PREP] Checking Python version..."
PYTHON_CMD=""
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_CMD="python3.11"
  echo "[PREP] Python 3.11 already installed"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_CMD="python3.12"
  echo "[PREP] Python 3.12 already installed"
elif command -v python3.13 >/dev/null 2>&1; then
  PYTHON_CMD="python3.13"
  echo "[PREP] Python 3.13 already installed"
else
  # Try installing Python with uv (fastest method)
  echo "[PREP] Attempting to install Python 3.11 using uv..."
  UV_INSTALLED=false
  UV_CMD=""
  
  # Install uv if not available
  if ! command -v uv >/dev/null 2>&1; then
    echo "[PREP] Installing uv..."
    UV_INSTALL_OUTPUT=$(curl -LsSf https://astral.sh/uv/install.sh 2>&1 | sh 2>&1)
    UV_INSTALL_EXIT=$?
    
    # Update PATH - uv installer may add to different locations
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    
    # Check common uv installation locations
    if [ -x "$HOME/.cargo/bin/uv" ]; then
      UV_CMD="$HOME/.cargo/bin/uv"
      UV_INSTALLED=true
      echo "[PREP] uv installed successfully (found in ~/.cargo/bin)"
    elif [ -x "$HOME/.local/bin/uv" ]; then
      UV_CMD="$HOME/.local/bin/uv"
      UV_INSTALLED=true
      echo "[PREP] uv installed successfully (found in ~/.local/bin)"
    elif command -v uv >/dev/null 2>&1; then
      UV_CMD="uv"
      UV_INSTALLED=true
      echo "[PREP] uv installed successfully (found in PATH)"
    else
      echo "[PREP] uv installation may have failed (exit code: $UV_INSTALL_EXIT)"
      if [ -n "$UV_INSTALL_OUTPUT" ]; then
        echo "[PREP] uv installer output: $UV_INSTALL_OUTPUT" >&2
      fi
    fi
  else
    UV_CMD="uv"
    UV_INSTALLED=true
    echo "[PREP] uv already available"
  fi
  
  # Try to install Python with uv
  if [ "$UV_INSTALLED" = "true" ] && [ -n "$UV_CMD" ]; then
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    echo "[PREP] Installing Python 3.11 using uv..."
    UV_PYTHON_OUTPUT=$("$UV_CMD" python install 3.11 2>&1)
    UV_PYTHON_EXIT=$?
    
    if [ $UV_PYTHON_EXIT -eq 0 ]; then
      # Find the installed Python - uv stores it in ~/.local/bin or ~/.uv/python
      if [ -x "$HOME/.local/bin/python3.11" ]; then
        PYTHON_CMD="$HOME/.local/bin/python3.11"
        echo "[PREP] Python 3.11 installed successfully using uv (found in ~/.local/bin)"
      else
        # Try uv python find
        UV_PYTHON=$("$UV_CMD" python find 3.11 2>/dev/null | head -1)
        if [ -n "$UV_PYTHON" ] && [ -x "$UV_PYTHON" ]; then
          PYTHON_CMD="$UV_PYTHON"
          echo "[PREP] Python 3.11 installed successfully using uv (found via 'uv python find')"
        else
          # Search in common uv locations
          if [ -d "$HOME/.uv/python" ]; then
            UV_PYTHON_PATH=$(find "$HOME/.uv/python" -name "python3" -type f -executable 2>/dev/null | grep -E "3\.11" | head -1)
            if [ -n "$UV_PYTHON_PATH" ] && [ -x "$UV_PYTHON_PATH" ]; then
              PYTHON_CMD="$UV_PYTHON_PATH"
              echo "[PREP] Python 3.11 installed successfully using uv (found in ~/.uv/python)"
            fi
          fi
        fi
      fi
      
      # If we still don't have Python, show error
      if [ -z "$PYTHON_CMD" ]; then
        echo "[PREP] Python 3.11 installed via uv but could not locate binary" >&2
        if [ -n "$UV_PYTHON_OUTPUT" ]; then
          echo "[PREP] uv python install output: $UV_PYTHON_OUTPUT" >&2
        fi
      fi
    else
      echo "[PREP] uv python install failed (exit code: $UV_PYTHON_EXIT)" >&2
      if [ -n "$UV_PYTHON_OUTPUT" ]; then
        echo "[PREP] uv python install output: $UV_PYTHON_OUTPUT" >&2
      fi
    fi
  fi
  
  # Fallback to deadsnakes PPA if uv failed
  if [ -z "$PYTHON_CMD" ]; then
    echo "[PREP] uv installation failed or unavailable, falling back to deadsnakes PPA..."
    if command -v apt-get >/dev/null 2>&1; then
      apt_retry "$PKG_INSTALL software-properties-common" || true
      add-apt-repository -y ppa:deadsnakes/ppa || true
      apt_retry "$PKG_UPDATE" || true
      apt_retry "$PKG_INSTALL python3.11 python3.11-venv python3.11-dev" || true
      PYTHON_CMD="python3.11"
    else
      echo "[PREP] Warning: Cannot install Python 3.11+ on non-Debian/Ubuntu system" >&2
      echo "[PREP] Attempting to use system Python 3.11+ if available..." >&2
      # Try to find any Python 3.11+ in PATH
      for py in python3.11 python3.12 python3.13; do
        if command -v "$py" >/dev/null 2>&1; then
          PYTHON_CMD="$py"
          break
        fi
      done
      if [ -z "$PYTHON_CMD" ]; then
        echo "[PREP] Error: Python 3.11+ not found and cannot be installed automatically" >&2
        exit 1
      fi
    fi
  fi
fi

if [ -z "$PYTHON_CMD" ]; then
  echo "[PREP] Error: Could not determine Python 3.11+ command" >&2
  exit 1
fi

echo "[PREP] Using Python: $PYTHON_CMD"
$PYTHON_CMD --version || true

echo "[PREP] Installing Docker (Engine + Compose v2) via get.docker.com..."
curl -fsSL https://get.docker.com | sh

# Enable/start docker if systemd present
if command -v systemctl >/dev/null 2>&1; then
  systemctl enable docker || true
  systemctl start docker || true
else
  service docker start || true
fi

echo "[PREP] Setting up dockertree in dedicated venv..."
VENV_DIR=/opt/dockertree-venv
mkdir -p "$VENV_DIR"

# Check if uv is available (preferred method for venv creation)
# Note: When Python is installed via uv, it's marked as "externally-managed" (PEP 668)
# which prevents python -m venv from using ensurepip. Using uv venv handles this correctly.
if command -v uv >/dev/null 2>&1; then
  # Use uv venv which handles pip installation properly, especially for uv-installed Python
  echo "[PREP] Using uv venv (uv is available)..."
  uv venv "$VENV_DIR" --python "$PYTHON_CMD" || {
    echo "[PREP] uv venv failed, falling back to standard venv..." >&2
    # Fallback to standard venv
    $PYTHON_CMD -m venv "$VENV_DIR" || {
      echo "[PREP] Standard venv failed, trying --without-pip..." >&2
      # If venv fails (e.g., externally-managed), try without pip
      $PYTHON_CMD -m venv --without-pip "$VENV_DIR" || {
        echo "[PREP] venv creation failed" >&2
        exit 1
      }
      # Install pip using get-pip.py
      curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV_DIR/bin/python" || {
        echo "[PREP] pip installation failed" >&2
        exit 1
      }
    }
  }
else
  # Try standard venv first
  $PYTHON_CMD -m venv "$VENV_DIR" || {
    echo "[PREP] Standard venv failed, trying --without-pip..." >&2
    # If venv fails (e.g., externally-managed), try without pip
    $PYTHON_CMD -m venv --without-pip "$VENV_DIR" || {
      echo "[PREP] venv creation failed" >&2
      exit 1
    }
    # Install pip using get-pip.py
    curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV_DIR/bin/python" || {
      echo "[PREP] pip installation failed" >&2
      exit 1
    }
  }
fi

# Ensure pip is available
if [ ! -f "$VENV_DIR/bin/pip" ]; then
  echo "[PREP] pip not found in venv, installing..." >&2
  curl -sSL https://bootstrap.pypa.io/get-pip.py | "$VENV_DIR/bin/python" || {
    echo "[PREP] pip installation failed" >&2
    exit 1
  }
fi

"$VENV_DIR/bin/pip" install --upgrade pip wheel
"$VENV_DIR/bin/pip" install --upgrade git+https://github.com/catalpainternational/dockertree.git || {
  echo "[PREP] venv install failed, trying pipx/system pip as fallback" >&2
  if command -v pipx >/dev/null 2>&1; then
    pipx install --force git+https://github.com/catalpainternational/dockertree.git || true
  else
    $PYTHON_CMD -m pip install --break-system-packages --upgrade git+https://github.com/catalpainternational/dockertree.git || true
  fi
}
ln -sf "$VENV_DIR/bin/dockertree" /usr/local/bin/dockertree || true

echo "[PREP] Versions:"
docker --version || true
docker compose version || true
git --version || true
dockertree --version || true
'''

            # Send script via SSH stdin and execute under bash -lc
            exec_cmd = "cat > /tmp/dtprep.sh && chmod +x /tmp/dtprep.sh && /tmp/dtprep.sh && rm -f /tmp/dtprep.sh"
            ssh_cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            log_info("Executing server preparation script via SSH...")
            log_info("This may take 5-10 minutes depending on server state and network speed...")
            
            # Use streaming utility for consistent output handling
            success, stdout_lines, stderr_lines = execute_with_streaming(
                ssh_cmd,
                script=remote_script,
                timeout=None,  # No timeout for server prep (can take 5-10 minutes)
                progress_interval=30,
                prefix="  ",
                filter_keywords=None  # Show all output in verbose mode, filtered in non-verbose
            )
            
            if not success:
                log_error("Remote preparation failed")
                if stderr_lines:
                    log_error("Server preparation errors:")
                    for line in stderr_lines:
                        log_error(f"  {line}")
                return False
            
            # Show output summary if not in verbose mode (verbose mode already showed it)
            if not is_verbose() and stdout_lines:
                log_info("Server preparation output:")
                for line in stdout_lines:
                    log_info(f"  {line}")
            
            log_info("Server preparation script completed successfully")
            return True
        except Exception as e:
            log_error(f"Error preparing server: {e}")
            return False

    def _run_remote_import(self, username: str, server: str, remote_file: str, branch_name: str,
                           domain: Optional[str], ip: Optional[str], build: bool = False) -> None:
        """Run remote import and start services via SSH using a robust here-doc script with enhanced logging."""
        try:
            log_info("Composing remote import script...")
            script = self._compose_remote_script(
                remote_file=remote_file,
                branch_name=branch_name,
                domain=domain,
                ip=ip,
                build=build,
            )
            exec_cmd = "cat > /tmp/dtrun.sh && chmod +x /tmp/dtrun.sh && /tmp/dtrun.sh && rm -f /tmp/dtrun.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            log_info("Executing remote import and startup script...")
            log_info("This will: import package, start proxy, and bring up the worktree environment")
            log_info("Streaming output in real-time...")
            
            # Use real-time streaming for better visibility
            if is_verbose():
                # Stream output in real-time for verbose mode
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1  # Line buffered
                )
                
                # Write script to stdin and close
                process.stdin.write(script)
                process.stdin.close()
                
                # Use threading to read from both stdout and stderr concurrently
                stdout_lines = []
                stderr_lines = []
                stdout_done = threading.Event()
                stderr_done = threading.Event()
                
                def read_stdout():
                    """Read stdout lines and log them in real-time."""
                    try:
                        for line in iter(process.stdout.readline, ''):
                            if line:
                                line = line.rstrip()
                                stdout_lines.append(line)
                                log_info(f"[REMOTE] {line}")
                    finally:
                        stdout_done.set()
                
                def read_stderr():
                    """Read stderr lines and log them appropriately."""
                    try:
                        for line in iter(process.stderr.readline, ''):
                            if line:
                                line = line.rstrip()
                                stderr_lines.append(line)
                                # Check if line contains error indicators
                                line_lower = line.lower()
                                if any(indicator in line_lower for indicator in ['✗', 'error', 'failed', 'fatal', 'exception']):
                                    log_error(f"[REMOTE] {line}")
                                elif any(indicator in line for indicator in ['✓', 'SUCCESS', 'successfully']):
                                    log_success(f"[REMOTE] {line}")
                                else:
                                    # Informational message (log, docker ps output, etc.)
                                    log_info(f"[REMOTE] {line}")
                    finally:
                        stderr_done.set()
                
                # Start threads to read from both streams
                stdout_thread = threading.Thread(target=read_stdout, daemon=True)
                stderr_thread = threading.Thread(target=read_stderr, daemon=True)
                stdout_thread.start()
                stderr_thread.start()
                
                # Wait for process to complete with timeout (30 minutes max for import + startup)
                import time
                start_time = time.time()
                timeout_seconds = 1800  # 30 minutes
                
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    if elapsed > timeout_seconds:
                        log_error(f"Remote import script timed out after {timeout_seconds}s")
                        process.kill()
                        process.wait()
                        return
                    time.sleep(1)
                
                # Wait for both threads to finish reading
                stdout_done.wait(timeout=10)
                stderr_done.wait(timeout=10)
                
                if process.returncode != 0:
                    log_error("Remote import script returned non-zero exit code")
                    # Always show errors and key failure points
                    error_found = False
                    if stderr_lines:
                        log_error("Remote import errors and warnings:")
                        for line in stderr_lines:
                            # Check if line is actually an error
                            line_lower = line.lower()
                            if any(indicator in line_lower for indicator in ['✗', 'error', 'failed', 'fatal', 'exception', 'exit code', 'non-zero']):
                                log_error(f"  {line}")
                                error_found = True
                            elif any(indicator in line_lower for indicator in ['warning', '⚠', 'warn']):
                                log_warning(f"  {line}")
                            else:
                                # Show informational lines too when there's an error
                                log_info(f"  {line}")
                    
                    # Also show last few stdout lines for context
                    if stdout_lines and not error_found:
                        log_error("Last output lines for context:")
                        for line in stdout_lines[-10:]:  # Last 10 lines
                            log_info(f"  {line}")
                    return
                
                log_success("Remote import script completed successfully")
                
                # Post-import domain configuration and route refresh
                if domain:
                    log_info("Performing post-import domain configuration...")
                    # Detect worktree path from remote server
                    detect_script = f"""#!/bin/bash
find /root -maxdepth 3 -type f -path "*/worktrees/{branch_name}/.dockertree/env.dockertree" -print -quit 2>/dev/null || echo ""
"""
                    detect_cmd = ["ssh", f"{username}@{server}", "bash", "-lc", "cat > /tmp/dtdetect.sh && chmod +x /tmp/dtdetect.sh && /tmp/dtdetect.sh && rm -f /tmp/dtdetect.sh"]
                    detect_process = subprocess.Popen(
                        detect_cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    stdout, _ = detect_process.communicate(input=detect_script, timeout=10)
                    worktree_path = stdout.strip()
                    if worktree_path:
                        worktree_path = str(Path(worktree_path).parent)  # Remove .dockertree/env.dockertree
                        # Update remote env file (in case import didn't fully apply domain settings)
                        self._update_remote_env_file(username, server, worktree_path, branch_name, domain)
                    # Refresh Caddy routes
                    self._refresh_caddy_routes(username, server, domain)
                    # Verify route
                    self._verify_caddy_route(username, server, domain)
            else:
                # Non-verbose mode: stream output but show key messages
                # Use Popen with timeout to prevent hanging
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Combine stderr into stdout
                    text=True,
                    bufsize=1  # Line buffered
                )
                
                # Write script and close stdin
                process.stdin.write(script)
                process.stdin.close()
                
                # Stream output with timeout using threading
                import time
                start_time = time.time()
                timeout_seconds = 1800  # 30 minutes
                output_lines = []
                output_lock = threading.Lock()
                read_complete = threading.Event()
                
                def read_output():
                    """Read output lines."""
                    try:
                        for line in iter(process.stdout.readline, ''):
                            if line:
                                line = line.rstrip()
                                with output_lock:
                                    output_lines.append(line)
                                # Show important messages even in non-verbose mode
                                if any(keyword in line.lower() for keyword in ['error', 'failed', 'success', 'starting', 'completed', 'timeout', 'import']):
                                    if '[REMOTE]' in line or 'ERROR' in line or 'SUCCESS' in line or 'import' in line.lower():
                                        log_info(f"[REMOTE] {line}")
                    finally:
                        read_complete.set()
                
                # Start reading thread
                read_thread = threading.Thread(target=read_output, daemon=True)
                read_thread.start()
                
                # Wait for process with timeout and show progress
                last_progress_time = start_time
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    if elapsed > timeout_seconds:
                        log_error(f"Remote import script timed out after {timeout_seconds}s")
                        process.kill()
                        process.wait()
                        return
                    
                    # Show progress every 30 seconds
                    if time.time() - last_progress_time > 30:
                        elapsed_min = int(elapsed / 60)
                        elapsed_sec = int(elapsed % 60)
                        log_info(f"[REMOTE] Still running... ({elapsed_min}m {elapsed_sec}s elapsed)")
                        last_progress_time = time.time()
                    
                    time.sleep(1)
                
                # Wait for output reading to complete
                read_complete.wait(timeout=10)
                
                # Create result object
                with output_lock:
                    stdout_text = '\n'.join(output_lines)
                result = type('Result', (), {
                    'returncode': process.returncode,
                    'stdout': stdout_text,
                    'stderr': ''
                })()
                
                if result.returncode != 0:
                    log_error("Remote import script returned non-zero exit code")
                    # Always show errors and key failure information
                    if result.stdout:
                        log_error("Remote import output (showing errors and last lines):")
                        lines = result.stdout.splitlines()
                        error_found = False
                        # First, show any error lines
                        for line in lines:
                            line_lower = line.lower()
                            if any(indicator in line_lower for indicator in ['✗', 'error', 'failed', 'fatal', 'exception', 'exit code', 'non-zero']):
                                log_error(f"  {line}")
                                error_found = True
                            elif any(indicator in line_lower for indicator in ['warning', '⚠', 'warn']):
                                log_warning(f"  {line}")
                        
                        # If no explicit errors found, show last 20 lines for context
                        if not error_found and len(lines) > 0:
                            log_error("Last output lines for context:")
                            for line in lines[-20:]:  # Last 20 lines
                                log_info(f"  {line}")
                    if result.stderr:
                        log_error("Remote import errors:")
                        for line in result.stderr.splitlines():
                            log_error(f"  {line}")
                else:
                    log_success("Remote import script completed successfully")
                    if result.stdout:
                        log_info("Remote import output:")
                        for line in result.stdout.splitlines():
                            log_info(f"  {line}")
                    
                    # Post-import domain configuration and route refresh
                    if domain:
                        log_info("Performing post-import domain configuration...")
                        # Detect worktree path from remote server
                        detect_script = f"""#!/bin/bash
find /root -maxdepth 3 -type f -path "*/worktrees/{branch_name}/.dockertree/env.dockertree" -print -quit 2>/dev/null || echo ""
"""
                        detect_cmd = ["ssh", f"{username}@{server}", "bash", "-lc", "cat > /tmp/dtdetect.sh && chmod +x /tmp/dtdetect.sh && /tmp/dtdetect.sh && rm -f /tmp/dtdetect.sh"]
                        detect_process = subprocess.Popen(
                            detect_cmd,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        stdout, _ = detect_process.communicate(input=detect_script, timeout=10)
                        worktree_path = stdout.strip()
                        if worktree_path:
                            worktree_path = str(Path(worktree_path).parent)  # Remove .dockertree/env.dockertree
                            # Update remote env file (in case import didn't fully apply domain settings)
                            self._update_remote_env_file(username, server, worktree_path, branch_name, domain)
                        # Refresh Caddy routes
                        self._refresh_caddy_routes(username, server, domain)
                        # Verify route
                        self._verify_caddy_route(username, server, domain)
        except Exception as e:
            log_error(f"Remote import failed: {e}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")

    def _configure_vpc_firewall(self, username: str, server: str, droplet_info: DropletInfo) -> bool:
        """Configure UFW firewall rules for VPC-accessible services.
        
        Only activates when:
        - Droplet has VPC information (private IP)
        - Config allows it (opt-in via config.yml)
        
        Args:
            username: SSH username
            server: Server hostname or IP
            droplet_info: Droplet info containing private IP
            
        Returns:
            True if firewall was configured, False otherwise
        """
        try:
            # Check if droplet has VPC info
            private_ip = getattr(droplet_info, 'private_ip_address', None)
            if not private_ip:
                log_info("No private IP found in droplet info, skipping firewall configuration")
                return False
            
            # Check if firewall configuration is enabled in config
            # We need to check the remote server's config, but for now we'll make it opt-in
            # via a simple check - if private IP exists and we're in VPC mode, configure firewall
            log_info("Configuring VPC firewall rules for secure Redis/DB access...")
            log_info(f"Private IP: {private_ip}")
            
            # Standard VPC ports that need firewall rules
            vpc_ports = [5432, 6379]  # PostgreSQL and Redis
            
            # Build firewall configuration script
            script = """#!/bin/bash
set -euo pipefail

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}

log_success() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*" >&2
}

log_warning() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ $*" >&2
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ $*" >&2
}

log "=== Configuring VPC Firewall Rules ==="

# Check if UFW is installed
if ! command -v ufw >/dev/null 2>&1; then
    log_warning "UFW not installed, skipping firewall configuration"
    exit 0
fi

# Check if UFW is active
if ! ufw status | grep -q "Status: active"; then
    log "UFW is not active, enabling..."
    ufw --force enable || {
        log_error "Failed to enable UFW"
        exit 1
    }
    log_success "UFW enabled"
fi

# Configure firewall rules for VPC network (10.0.0.0/8)
VPC_NETWORK="10.0.0.0/8"
PORTS=(5432 6379)

for port in "${PORTS[@]}"; do
    # Check if rule already exists
    if ufw status | grep -q "from ${VPC_NETWORK} to any port ${port}"; then
        log "Firewall rule for port ${port} already exists, skipping"
    else
        log "Adding firewall rule: allow from ${VPC_NETWORK} to port ${port}"
        if ufw allow from ${VPC_NETWORK} to any port ${port} comment "VPC access for dockertree"; then
            log_success "Firewall rule added for port ${port}"
        else
            log_error "Failed to add firewall rule for port ${port}"
        fi
    fi
done

# Reload UFW to apply changes
log "Reloading UFW..."
ufw reload || {
    log_warning "UFW reload failed, but rules may still be applied"
}

log_success "VPC firewall configuration completed"
"""
            
            # Execute firewall configuration script
            exec_cmd = "cat > /tmp/dtfw.sh && chmod +x /tmp/dtfw.sh && /tmp/dtfw.sh && rm -f /tmp/dtfw.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            
            log_info("Executing firewall configuration script...")
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Use communicate() with input to avoid I/O errors from closing stdin manually
            stdout, stderr = process.communicate(input=script, timeout=60)
            
            if process.returncode == 0:
                log_success("VPC firewall configuration completed successfully")
                if stdout:
                    for line in stdout.splitlines():
                        if line.strip():
                            log_info(f"[FIREWALL] {line}")
                return True
            else:
                log_warning(f"Firewall configuration returned non-zero exit code: {process.returncode}")
                if stderr:
                    for line in stderr.splitlines():
                        if line.strip():
                            log_warning(f"[FIREWALL] {line}")
                # Don't fail the whole operation if firewall config fails
                return False
                
        except subprocess.TimeoutExpired:
            log_warning("Firewall configuration script timed out")
            return False
        except Exception as e:
            log_warning(f"Failed to configure firewall: {e}")
            # Don't fail the whole operation if firewall config fails
            return False

    def _refresh_caddy_routes(self, username: str, server: str, domain: Optional[str] = None) -> bool:
        """Refresh Caddy routes by triggering the dynamic config script.
        
        Args:
            username: SSH username
            server: Server hostname or IP
            domain: Optional domain to verify route for
            
        Returns:
            True if routes were refreshed successfully, False otherwise
        """
        try:
            log_info("Refreshing Caddy routes...")
            
            # Script to trigger Caddy route refresh
            script = """#!/bin/bash
set -euo pipefail

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}

log_success() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*" >&2
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ $*" >&2
}

log "Refreshing Caddy routes..."

# Find dockertree binary
DTBIN=""
if [ -x /opt/dockertree-venv/bin/dockertree ]; then
  DTBIN=/opt/dockertree-venv/bin/dockertree
elif command -v dockertree >/dev/null 2>&1; then
  DTBIN="$(command -v dockertree)"
else
  log_error "dockertree binary not found"
  exit 1
fi

# Trigger Caddy route refresh by running the dynamic config script
# The script monitors Docker containers and updates Caddy routes
PYTHON_SCRIPT="/opt/dockertree-venv/lib/python*/site-packages/dockertree/scripts/caddy-dynamic-config.py"
if [ -f "$PYTHON_SCRIPT" ] || python3 -c "import dockertree.scripts.caddy_dynamic_config" 2>/dev/null; then
  log "Running Caddy dynamic configuration..."
  if python3 -m dockertree.scripts.caddy_dynamic_config 2>/dev/null || python3 "$PYTHON_SCRIPT" 2>/dev/null; then
    log_success "Caddy routes refreshed successfully"
    exit 0
  fi
fi

# Fallback: Use dockertree command if available
if [ -n "$DTBIN" ]; then
  log "Using dockertree to refresh routes..."
  # The start-proxy command will refresh routes
  if "$DTBIN" start-proxy --non-interactive >/dev/null 2>&1; then
    log_success "Caddy routes refreshed via dockertree"
    exit 0
  fi
fi

log_warning "Could not refresh Caddy routes automatically"
log "Routes should be updated automatically by the Caddy monitor"
exit 0
"""
            
            exec_cmd = "cat > /tmp/dtcaddyrefresh.sh && chmod +x /tmp/dtcaddyrefresh.sh && /tmp/dtcaddyrefresh.sh && rm -f /tmp/dtcaddyrefresh.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=script, timeout=30)
            
            if process.returncode == 0:
                log_success("Caddy routes refreshed successfully")
                return True
            else:
                log_warning("Caddy route refresh returned non-zero exit code, but continuing...")
                if stderr:
                    for line in stderr.splitlines():
                        if line.strip():
                            log_info(f"[CADDY] {line}")
                return False
                
        except subprocess.TimeoutExpired:
            log_warning("Caddy route refresh timed out, but continuing...")
            return False
        except Exception as e:
            log_warning(f"Failed to refresh Caddy routes: {e}")
            return False
    
    def _verify_caddy_route(self, username: str, server: str, domain: str) -> bool:
        """Verify that Caddy route exists for the given domain.
        
        Args:
            username: SSH username
            server: Server hostname or IP
            domain: Domain to verify route for
            
        Returns:
            True if route exists, False otherwise
        """
        try:
            log_info(f"Verifying Caddy route for {domain}...")
            
            # Script to check Caddy admin API for route
            script = f"""#!/bin/bash
set -euo pipefail

log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}}

log_success() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*" >&2
}}

log_error() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ $*" >&2
}}

# Check if Caddy admin API is accessible
CADDY_ADMIN="http://localhost:2019"
if ! curl -s "$CADDY_ADMIN/config/" >/dev/null 2>&1; then
  log_error "Caddy admin API not accessible"
  exit 1
fi

# Get current routes
ROUTES=$(curl -s "$CADDY_ADMIN/config/apps/http/servers/srv0/routes" 2>/dev/null || echo "[]")

# Check if domain is in routes
if echo "$ROUTES" | grep -q "{domain}"; then
  log_success "Route found for {domain}"
  exit 0
else
  log_error "Route not found for {domain}"
  log "Current routes:"
  echo "$ROUTES" | grep -o '"host":\\["[^"]*"\\]' | head -5
  exit 1
fi
"""
            
            exec_cmd = "cat > /tmp/dtverifyroute.sh && chmod +x /tmp/dtverifyroute.sh && /tmp/dtverifyroute.sh && rm -f /tmp/dtverifyroute.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=script, timeout=15)
            
            if process.returncode == 0:
                log_success(f"Caddy route verified for {domain}")
                return True
            else:
                log_warning(f"Caddy route verification failed for {domain}")
                if stderr:
                    for line in stderr.splitlines():
                        if line.strip():
                            log_info(f"[VERIFY] {line}")
                return False
                
        except subprocess.TimeoutExpired:
            log_warning("Caddy route verification timed out")
            return False
        except Exception as e:
            log_warning(f"Failed to verify Caddy route: {e}")
            return False
    
    def _update_remote_env_file(self, username: str, server: str, worktree_path: str, 
                                branch_name: str, domain: str) -> bool:
        """Update remote env.dockertree file with domain settings.
        
        Args:
            username: SSH username
            server: Server hostname or IP
            worktree_path: Path to worktree on remote server
            branch_name: Branch name
            domain: Domain to configure
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            from ..core.dns_manager import get_base_domain
            from ..config.settings import build_allowed_hosts_with_container
            
            log_info(f"Updating remote environment file with domain {domain}...")
            
            # Build allowed hosts
            base_domain = get_base_domain(domain)
            allowed_hosts = build_allowed_hosts_with_container(branch_name, [domain, f"*.{base_domain}"])
            
            # Build Vite allowed hosts (domain, wildcard, and localhost variants)
            vite_allowed_hosts = f"{domain},*.{base_domain},localhost,127.0.0.1"
            
            # Script to update env.dockertree file
            script = f"""#!/bin/bash
set -euo pipefail

log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}}

log_success() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*" >&2
}}

log_error() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ $*" >&2
}}

ENV_FILE="{worktree_path}/.dockertree/env.dockertree"

if [ ! -f "$ENV_FILE" ]; then
  log_error "Environment file not found: $ENV_FILE"
  exit 1
fi

log "Updating environment file with domain configuration..."

# Update SITE_DOMAIN
sed -i 's|^SITE_DOMAIN=.*|SITE_DOMAIN={domain}|g' "$ENV_FILE"

# Update ALLOWED_HOSTS
sed -i 's|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS={allowed_hosts}|g' "$ENV_FILE"

# Update VITE_ALLOWED_HOSTS (for Vite dev server security)
# Include domain, base domain wildcard, and localhost variants
if grep -q "^VITE_ALLOWED_HOSTS=" "$ENV_FILE"; then
  sed -i 's|^VITE_ALLOWED_HOSTS=.*|VITE_ALLOWED_HOSTS={vite_allowed_hosts}|g' "$ENV_FILE"
else
  echo "VITE_ALLOWED_HOSTS={vite_allowed_hosts}" >> "$ENV_FILE"
fi

# Update CSRF_TRUSTED_ORIGINS
if grep -q "^CSRF_TRUSTED_ORIGINS=" "$ENV_FILE"; then
  sed -i 's|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://{domain},http://{domain}|g' "$ENV_FILE"
else
  echo "CSRF_TRUSTED_ORIGINS=https://{domain},http://{domain}" >> "$ENV_FILE"
fi

# Set DEBUG=False for production
sed -i 's|^DEBUG=.*|DEBUG=False|g' "$ENV_FILE"

log_success "Environment file updated successfully"
"""
            
            exec_cmd = "cat > /tmp/dtupdateenv.sh && chmod +x /tmp/dtupdateenv.sh && /tmp/dtupdateenv.sh && rm -f /tmp/dtupdateenv.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=script, timeout=30)
            
            if process.returncode == 0:
                log_success("Remote environment file updated successfully")
                return True
            else:
                log_warning("Environment file update returned non-zero exit code")
                if stderr:
                    for line in stderr.splitlines():
                        if line.strip():
                            log_warning(f"[ENV] {line}")
                return False
                
        except subprocess.TimeoutExpired:
            log_warning("Environment file update timed out")
            return False
        except Exception as e:
            log_warning(f"Failed to update remote environment file: {e}")
            return False

    def _compose_remote_script(self, remote_file: str, branch_name: str, domain: Optional[str],
                               ip: Optional[str], build: bool = False) -> str:
        """Compose a robust remote bash script for importing and starting services.

        The script sets strict mode, ensures git identity, resolves the dockertree binary,
        detects existing project vs standalone, runs import with proper flags and quoting,
        then starts proxy and brings up the branch. Includes comprehensive logging and verification.
        """
        # Build import flags with proper quoting
        import_flags_list = []
        if domain:
            import_flags_list.append("--domain")
            import_flags_list.append(domain)
        if ip:
            import_flags_list.append("--ip")
            import_flags_list.append(ip)
        
        # Convert to bash array syntax for proper argument handling
        if import_flags_list:
            import_flags_array = " ".join(f'"{flag}"' for flag in import_flags_list)
            import_flags_usage = import_flags_array
        else:
            import_flags_usage = ""

        build_section = ""
        if build:
            build_section = f"""
# Rebuild Docker images before bringing up services
log "Rebuilding Docker images for branch: {branch_name}"

# Clear BuildKit cache to avoid corruption issues
log "Clearing Docker BuildKit cache to prevent corruption..."
if docker builder prune -f --filter type=exec.cachemount >/dev/null 2>&1; then
  log_success "BuildKit cache cleared successfully"
elif docker builder prune -f >/dev/null 2>&1; then
  log_success "BuildKit cache cleared (fallback method)"
else
  log_warning "Failed to clear BuildKit cache, continuing with build anyway"
fi

# Attempt build with cache first, fallback to --no-cache if needed
log "Building Docker images..."
BUILD_SUCCESS=false
if "$DTBIN" "{branch_name}" build; then
  log_success "Images rebuilt successfully"
  BUILD_SUCCESS=true
else
  log_warning "Build failed, retrying with --no-cache flag..."
  if "$DTBIN" "{branch_name}" build --no-cache; then
    log_success "Images rebuilt successfully (without cache)"
    BUILD_SUCCESS=true
  else
    log_error "Failed to rebuild images even with --no-cache"
    BUILD_SUCCESS=false
  fi
fi

if [ "$BUILD_SUCCESS" != "true" ]; then
  exit 1
fi

log_success "Build process completed successfully"
"""
        
        # Build domain configuration section
        domain_config_section = ""
        if domain:
            from ..core.dns_manager import get_base_domain
            from ..config.settings import build_allowed_hosts_with_container
            
            base_domain = get_base_domain(domain)
            allowed_hosts = build_allowed_hosts_with_container(branch_name, [domain, f"*.{base_domain}"])
            vite_allowed_hosts = f"{domain},*.{base_domain},localhost,127.0.0.1"
            
            domain_config_section = f"""
# Domain configuration updates
log "=== Configuring domain: {domain} ==="

# Update environment file with domain settings
ENV_FILE="$ROOT2/worktrees/${{BRANCH_NAME}}/.dockertree/env.dockertree"
if [ -f "$ENV_FILE" ]; then
  log "Updating environment file with domain configuration..."
  
  # Update SITE_DOMAIN
  sed -i 's|^SITE_DOMAIN=.*|SITE_DOMAIN={domain}|g' "$ENV_FILE"
  
  # Update ALLOWED_HOSTS
  sed -i 's|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS={allowed_hosts}|g' "$ENV_FILE"
  
  # Update VITE_ALLOWED_HOSTS (for Vite dev server security)
  if grep -q "^VITE_ALLOWED_HOSTS=" "$ENV_FILE"; then
    sed -i 's|^VITE_ALLOWED_HOSTS=.*|VITE_ALLOWED_HOSTS={vite_allowed_hosts}|g' "$ENV_FILE"
  else
    echo "VITE_ALLOWED_HOSTS={vite_allowed_hosts}" >> "$ENV_FILE"
  fi
  
  # Update CSRF_TRUSTED_ORIGINS
  if grep -q "^CSRF_TRUSTED_ORIGINS=" "$ENV_FILE"; then
    sed -i 's|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://{domain},http://{domain}|g' "$ENV_FILE"
  else
    echo "CSRF_TRUSTED_ORIGINS=https://{domain},http://{domain}" >> "$ENV_FILE"
  fi
  
  # Set DEBUG=False for production
  sed -i 's|^DEBUG=.*|DEBUG=False|g' "$ENV_FILE"
  
  log_success "Environment file updated with domain configuration"
  
  # Restart containers to pick up new environment variables
  log "Restarting containers to apply domain configuration..."
  cd "$ROOT2"
  if [ "$IMPORT_MODE" = "standalone" ]; then
    WORKTREE_PATH="$ROOT2/worktrees/${{BRANCH_NAME}}"
    COMPOSE_FILE="$WORKTREE_PATH/docker-compose.yml"
    if [ ! -f "$COMPOSE_FILE" ]; then
      COMPOSE_FILE="$WORKTREE_PATH/.dockertree/docker-compose.worktree.yml"
    fi
    if [ -f "$COMPOSE_FILE" ]; then
      cd "$WORKTREE_PATH"
      COMPOSE_FILE_REL="$(basename "$COMPOSE_FILE")"
      if [ "$COMPOSE_FILE_REL" = "docker-compose.worktree.yml" ]; then
        COMPOSE_FILE_REL=".dockertree/docker-compose.worktree.yml"
      fi
      export COMPOSE_PROJECT_NAME="${{COMPOSE_PROJECT_NAME}}"
      export PROJECT_ROOT="$WORKTREE_PATH"
      docker compose -f "$COMPOSE_FILE_REL" --env-file .dockertree/env.dockertree -p "$COMPOSE_PROJECT_NAME" restart >/dev/null 2>&1 || true
      log_success "Containers restarted with new domain configuration"
    fi
  else
    if "$DTBIN" "${{BRANCH_NAME}}" restart >/dev/null 2>&1; then
      log_success "Containers restarted with new domain configuration"
    else
      log_warning "Failed to restart containers, but continuing..."
    fi
  fi
  
  # Refresh Caddy routes to ensure domain is properly routed
  log "Refreshing Caddy routes for domain {domain}..."
  sleep 2  # Brief pause for containers to register
  
  # Try to trigger Caddy route refresh via dynamic config
  PYTHON_SCRIPT="/opt/dockertree-venv/lib/python*/site-packages/dockertree/scripts/caddy-dynamic-config.py"
  if [ -f "$PYTHON_SCRIPT" ] || python3 -c "import dockertree.scripts.caddy_dynamic_config" 2>/dev/null; then
    if python3 -m dockertree.scripts.caddy_dynamic_config >/dev/null 2>&1 || python3 "$PYTHON_SCRIPT" >/dev/null 2>&1; then
      log_success "Caddy routes refreshed successfully"
    else
      log_warning "Caddy route refresh failed, but routes should update automatically"
    fi
  else
    # Fallback: restart proxy to refresh routes
    if "$DTBIN" start-proxy --non-interactive >/dev/null 2>&1; then
      log_success "Caddy proxy restarted to refresh routes"
    else
      log_warning "Could not refresh Caddy routes, but they should update automatically"
    fi
  fi
  
  # Verify route exists (non-blocking)
  log "Verifying Caddy route for {domain}..."
  sleep 3  # Give Caddy time to update
  # Temporarily disable set -e for this non-critical check
  set +e
  curl -s "http://localhost:2019/config/apps/http/servers/srv0/routes" 2>/dev/null | grep -q "{domain}"
  ROUTE_CHECK_RESULT=$?
  set -e
  if [ $ROUTE_CHECK_RESULT -eq 0 ]; then
    log_success "Caddy route verified for {domain}"
  else
    log_warning "Caddy route verification failed - route may still be updating"
    log "Routes should be automatically configured by the Caddy monitor"
  fi
else
  log_warning "Environment file not found: $ENV_FILE"
  log "Domain configuration may not be applied correctly"
fi
"""
        elif ip:
            domain_config_section = f"""
# IP configuration updates
log "=== Configuring IP: {ip} ==="

# Update environment file with IP settings
ENV_FILE="$ROOT2/worktrees/${{BRANCH_NAME}}/.dockertree/env.dockertree"
if [ -f "$ENV_FILE" ]; then
  log "Updating environment file with IP configuration..."
  
  # Update SITE_DOMAIN
  sed -i 's|^SITE_DOMAIN=.*|SITE_DOMAIN=http://{ip}|g' "$ENV_FILE"
  
  # Update ALLOWED_HOSTS to include IP
  if ! grep -q "{ip}" "$ENV_FILE"; then
    CURRENT_HOSTS=$(grep "^ALLOWED_HOSTS=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=${{CURRENT_HOSTS}},{ip}|g" "$ENV_FILE"
  fi
  
  log_success "Environment file updated with IP configuration"
  
  # Restart containers to pick up new environment variables
  log "Restarting containers to apply IP configuration..."
  cd "$ROOT2"
  if [ "$IMPORT_MODE" = "standalone" ]; then
    WORKTREE_PATH="$ROOT2/worktrees/${{BRANCH_NAME}}"
    COMPOSE_FILE="$WORKTREE_PATH/docker-compose.yml"
    if [ ! -f "$COMPOSE_FILE" ]; then
      COMPOSE_FILE="$WORKTREE_PATH/.dockertree/docker-compose.worktree.yml"
    fi
    if [ -f "$COMPOSE_FILE" ]; then
      cd "$WORKTREE_PATH"
      COMPOSE_FILE_REL="$(basename "$COMPOSE_FILE")"
      if [ "$COMPOSE_FILE_REL" = "docker-compose.worktree.yml" ]; then
        COMPOSE_FILE_REL=".dockertree/docker-compose.worktree.yml"
      fi
      export COMPOSE_PROJECT_NAME="${{COMPOSE_PROJECT_NAME}}"
      export PROJECT_ROOT="$WORKTREE_PATH"
      docker compose -f "$COMPOSE_FILE_REL" --env-file .dockertree/env.dockertree -p "$COMPOSE_PROJECT_NAME" restart >/dev/null 2>&1 || true
      log_success "Containers restarted with new IP configuration"
    fi
  else
    if "$DTBIN" "${{BRANCH_NAME}}" restart >/dev/null 2>&1; then
      log_success "Containers restarted with new IP configuration"
    else
      log_warning "Failed to restart containers, but continuing..."
    fi
  fi
fi
"""

        script = f"""
set -euo pipefail

# Logging helper function
log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}}

log_success() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*" >&2
}}

log_error() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ $*" >&2
}}

log_warning() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ $*" >&2
}}

log "=== Starting remote import process ==="
log "Package file: {remote_file}"
log "Branch name: {branch_name}"

# Ensure git identity exists to avoid commit failures on fresh servers
log "Configuring git identity..."
if ! git config --global user.email >/dev/null 2>&1; then 
  git config --global user.email 'dockertree@local'
  log "Set git user.email to dockertree@local"
fi
if ! git config --global user.name >/dev/null 2>&1; then 
  git config --global user.name 'Dockertree'
  log "Set git user.name to Dockertree"
fi

# Determine dockertree binary (prefer venv install)
log "Locating dockertree binary..."
if [ -x /opt/dockertree-venv/bin/dockertree ]; then
  DTBIN=/opt/dockertree-venv/bin/dockertree
  log "Using dockertree from /opt/dockertree-venv/bin/dockertree"
elif command -v dockertree >/dev/null 2>&1; then
  DTBIN="$(command -v dockertree)"
  log "Using dockertree from PATH: $DTBIN"
else
  DTBIN=dockertree
  log "Using dockertree from PATH (fallback)"
fi

# Verify dockertree works
if ! "$DTBIN" --version >/dev/null 2>&1; then
  log_error "dockertree binary not working: $DTBIN"
  exit 1
fi
log_success "dockertree binary verified: $($DTBIN --version 2>&1 | head -1)"

PKG_FILE='{remote_file}'
BRANCH_NAME='{branch_name}'

# Verify package file exists
log "Verifying package file exists..."
if [ ! -f "$PKG_FILE" ]; then
  log_error "Package file not found: $PKG_FILE"
  exit 1
fi
PKG_SIZE=$(du -h "$PKG_FILE" | cut -f1)
log_success "Package file found: $PKG_FILE ($PKG_SIZE)"

# Find an existing dockertree project by locating .dockertree/config.yml
log "Detecting existing dockertree project..."
HIT="$(find /root -maxdepth 3 -type f -path '*/.dockertree/config.yml' -print -quit 2>/dev/null || true)"
if [ -n "$HIT" ]; then
  ROOT="$(dirname "$(dirname "$HIT")")"
  log "Found existing project at: $ROOT"
  cd "$ROOT"
  
  # Clean up existing worktree if it exists (enables consecutive pushes)
  log "Checking for existing worktree for branch '$BRANCH_NAME'..."
  # Check if worktree directory exists (more reliable than parsing command output)
  set +e
  WORKTREE_DIR="$(find "$ROOT" -maxdepth 3 -type d -path "*/worktrees/$BRANCH_NAME" -print -quit 2>/dev/null || true)"
  set -e
  
  if [ -n "$WORKTREE_DIR" ] && [ -d "$WORKTREE_DIR" ]; then
    log "Worktree for branch '$BRANCH_NAME' already exists at: $WORKTREE_DIR"
    log "Cleaning up existing worktree and volumes before import..."
    # Remove worktree (keeps branch, removes volumes and containers)
    set +e
    if "$DTBIN" remove "$BRANCH_NAME" --force >/dev/null 2>&1; then
      log_success "Existing worktree and volumes removed"
    else
      log_warning "Failed to remove existing worktree via dockertree, attempting manual cleanup..."
    fi
    # Always ensure worktree directory is removed (critical for consecutive pushes)
    # Remove directory first, then clean up git references
    if [ -d "$WORKTREE_DIR" ]; then
      log "Removing worktree directory: $WORKTREE_DIR"
      # Stop any containers that might be using this directory
      cd "$ROOT" 2>/dev/null || true
      # Try to stop containers for this branch if they exist
      docker ps --filter "name=$BRANCH_NAME" --format "{{.Names}}" 2>/dev/null | while read -r container; do
        if [ -n "$container" ]; then
          docker stop "$container" >/dev/null 2>&1 || true
        fi
      done
      # Now remove the directory
      rm -rf "$WORKTREE_DIR" 2>/dev/null || true
      # Verify it's gone
      if [ -d "$WORKTREE_DIR" ]; then
        log_warning "Worktree directory still exists after removal attempt"
        # Try one more time with force
        rm -rf "$WORKTREE_DIR" 2>/dev/null || true
      else
        log "Worktree directory removed successfully"
      fi
    fi
    # Always clean up git worktree references to ensure no stale entries
    # This is critical for consecutive pushes to work correctly
    if command -v git >/dev/null 2>&1 && [ -d "$ROOT/.git" ]; then
      cd "$ROOT"
      # First, try to remove worktree by path if we know it
      if [ -n "$WORKTREE_DIR" ]; then
        git worktree remove "$WORKTREE_DIR" --force >/dev/null 2>&1 || true
      fi
      # Prune stale worktree references (removes entries where path doesn't exist)
      git worktree prune >/dev/null 2>&1 || true
      # Try to explicitly remove worktree by finding it in git's worktree list
      # Look for worktrees associated with this branch
      WT_INFO=$(git worktree list --porcelain 2>/dev/null | grep -B 2 "branch.*$BRANCH_NAME" | grep "^worktree" | head -1 | cut -d' ' -f2- || true)
      if [ -n "$WT_INFO" ]; then
        # Remove the worktree reference explicitly (even if directory is gone)
        git worktree remove "$WT_INFO" --force >/dev/null 2>&1 || true
      fi
      # Final prune to ensure everything is clean
      git worktree prune >/dev/null 2>&1 || true
      # Verify worktree is actually gone before proceeding
      if git worktree list 2>/dev/null | grep -q "\[$BRANCH_NAME\]"; then
        log_warning "Worktree reference still exists after cleanup, attempting final removal..."
        # Try to find and remove by iterating through worktree list
        git worktree list 2>/dev/null | while IFS= read -r line; do
          if echo "$line" | grep -q "\[$BRANCH_NAME\]"; then
            WT_PATH=$(echo "$line" | cut -d' ' -f1)
            if [ -n "$WT_PATH" ]; then
              git worktree remove "$WT_PATH" --force >/dev/null 2>&1 || true
            fi
          fi
        done
        git worktree prune >/dev/null 2>&1 || true
      fi
      log "Git worktree references cleaned up"
    fi
    set -e
    
    # Final verification: ensure worktree directory is completely gone before import
    # This is critical - if directory exists, import will fail
    if [ -d "$WORKTREE_DIR" ]; then
      log_error "CRITICAL: Worktree directory still exists: $WORKTREE_DIR"
      log_error "This will cause import to fail. Attempting final removal..."
      # Last attempt: stop all related containers and force remove
      cd "$ROOT" 2>/dev/null || true
      docker ps -a --filter "name=$BRANCH_NAME" --format "{{.Names}}" 2>/dev/null | xargs -r docker stop >/dev/null 2>&1 || true
      docker ps -a --filter "name=$BRANCH_NAME" --format "{{.Names}}" 2>/dev/null | xargs -r docker rm >/dev/null 2>&1 || true
      sleep 2  # Wait for containers to fully stop
      rm -rf "$WORKTREE_DIR" 2>/dev/null || true
      if [ -d "$WORKTREE_DIR" ]; then
        log_error "FATAL: Cannot remove worktree directory. Import will fail."
        log_error "Please manually remove: $WORKTREE_DIR"
        exit 1
      else
        log "Worktree directory finally removed"
      fi
    fi
  else
    log "No existing worktree found for branch '$BRANCH_NAME'"
  fi
  
  log "Running import in normal mode (existing project)..."
  # Final check: ensure worktree directory doesn't exist before import
  if [ -d "$ROOT/worktrees/$BRANCH_NAME" ]; then
    log_warning "Worktree directory still exists before import, removing..."
    rm -rf "$ROOT/worktrees/$BRANCH_NAME" 2>/dev/null || true
    # Clean up git references one more time
    if command -v git >/dev/null 2>&1 && [ -d "$ROOT/.git" ]; then
      cd "$ROOT" && git worktree prune >/dev/null 2>&1 || true
    fi
  fi
  "$DTBIN" packages import "$PKG_FILE" {import_flags_usage} --non-interactive
  IMPORT_MODE="normal"
else
  ROOT="/root"
  log "No existing project found, using standalone mode"
  cd "$ROOT"
  log "Running import in standalone mode (new project)..."
  "$DTBIN" packages import "$PKG_FILE" {import_flags_usage} --standalone --non-interactive
  IMPORT_MODE="standalone"
fi

# Verify import succeeded by checking for project directory
log "Verifying import completed successfully..."
HIT2="$(find /root -maxdepth 3 -type f -path '*/.dockertree/config.yml' -print -quit 2>/dev/null || true)"
if [ -z "$HIT2" ]; then
  log_error "Import failed: project directory not found after import"
  exit 1
fi
ROOT2="$(dirname "$(dirname "$HIT2")")"
log_success "Import completed, project located at: $ROOT2"
cd "$ROOT2"

# Domain/IP overrides are already applied to env files and Docker Compose labels during import
# The apply_domain_overrides function updates both .env, env.dockertree, and docker-compose.worktree.yml
# Verify Docker Compose file exists (labels should already be updated)
WORKTREE_PATH="$ROOT2/worktrees/${{BRANCH_NAME}}"
COMPOSE_FILE="$WORKTREE_PATH/.dockertree/docker-compose.worktree.yml"
if [ -f "$COMPOSE_FILE" ]; then
  log "Docker Compose file found, Caddy labels should be configured"
else
  log_warning "Docker Compose file not found: $COMPOSE_FILE"
fi

# Start Caddy proxy BEFORE containers start
# This ensures Caddy is ready to route when containers register
log "Starting global Caddy proxy..."
if "$DTBIN" start-proxy --non-interactive >/dev/null 2>&1; then
  log_success "Proxy started successfully"
elif "$DTBIN" start-proxy >/dev/null 2>&1; then
  log_success "Proxy started successfully (without --non-interactive)"
else
  log_error "Failed to start proxy, but continuing..."
fi

# Give Caddy a moment to initialize
sleep 2

# Verify volumes were restored
log "Verifying volumes were restored..."
log "Looking for volumes matching branch pattern: *${{BRANCH_NAME}}_*"

# Get project name from config if available
PROJECT_NAME=""
if [ -f "$ROOT2/.dockertree/config.yml" ]; then
  PROJECT_NAME=$(grep -E "^project_name:" "$ROOT2/.dockertree/config.yml" 2>/dev/null | sed 's/.*project_name:[[:space:]]*//' | tr -d '"' | tr -d "'" || echo "")
  if [ -n "$PROJECT_NAME" ]; then
    # Sanitize project name (replace underscores with hyphens, lowercase)
    PROJECT_NAME=$(echo "$PROJECT_NAME" | sed 's/_/-/g' | tr '[:upper:]' '[:lower:]')
    log "Detected project name: $PROJECT_NAME"
  fi
fi

# Try to find volumes using docker volume ls (more robust than guessing names)
VOLUMES_FOUND=0
VOLUMES_MISSING=0
NEED_VOLUME_RESTORE=false
EMPTY_VOLUMES=0

for vol_type in postgres_data redis_data media_files; do
  # Try exact match first if we have project name
  if [ -n "$PROJECT_NAME" ]; then
    VOL_NAME="${{PROJECT_NAME}}-${{BRANCH_NAME}}_${{vol_type}}"
    if docker volume inspect "$VOL_NAME" >/dev/null 2>&1; then
      VOL_SIZE=$(docker volume inspect "$VOL_NAME" --format '{{{{.Mountpoint}}}}' | xargs du -sh 2>/dev/null | cut -f1 || echo "unknown")
      VOL_SIZE_BYTES=$(docker volume inspect "$VOL_NAME" --format '{{{{.Mountpoint}}}}' | xargs du -sb 2>/dev/null | cut -f1 || echo "0")
      
      # Check if volume is empty (PostgreSQL should be > 1MB if restored)
      if [ "$vol_type" = "postgres_data" ]; then
        MIN_SIZE=1048576  # 1MB
      else
        MIN_SIZE=10000  # 10KB
      fi
      
      if [ "$VOL_SIZE_BYTES" -lt "$MIN_SIZE" ]; then
        log_error "Volume $VOL_NAME appears empty (size: $VOL_SIZE_BYTES bytes, expected > $MIN_SIZE)"
        NEED_VOLUME_RESTORE=true
        EMPTY_VOLUMES=$((EMPTY_VOLUMES + 1))
      else
        log_success "Volume found: $VOL_NAME (size: $VOL_SIZE)"
      fi
      VOLUMES_FOUND=$((VOLUMES_FOUND + 1))
      continue
    fi
  fi
  
  # Fallback: search for volumes matching pattern
  FOUND_VOL=$(docker volume ls --format "{{{{.Name}}}}" | grep -E ".*${{BRANCH_NAME}}_${{vol_type}}$" | head -1 || true)
  if [ -n "$FOUND_VOL" ]; then
    VOL_SIZE=$(docker volume inspect "$FOUND_VOL" --format '{{{{.Mountpoint}}}}' | xargs du -sh 2>/dev/null | cut -f1 || echo "unknown")
    VOL_SIZE_BYTES=$(docker volume inspect "$FOUND_VOL" --format '{{{{.Mountpoint}}}}' | xargs du -sb 2>/dev/null | cut -f1 || echo "0")
    
    # Check if this is the expected volume name
    if [ -n "$PROJECT_NAME" ]; then
      EXPECTED_VOL="${{PROJECT_NAME}}-${{BRANCH_NAME}}_${{vol_type}}"
      if [ "$FOUND_VOL" != "$EXPECTED_VOL" ]; then
        log_error "Volume name mismatch!"
        log_error "  Expected: $EXPECTED_VOL"
        log_error "  Found: $FOUND_VOL"
        log_error "  This may indicate volume restoration failed and a new empty volume was created"
      fi
    fi
    
    # Check if volume is suspiciously small (likely empty)
    if [ "$vol_type" = "postgres_data" ]; then
      MIN_SIZE=1048576  # 1MB
    else
      MIN_SIZE=10000  # 10KB
    fi
    
    if [ "$VOL_SIZE_BYTES" -lt "$MIN_SIZE" ]; then
      log_error "WARNING: Volume $FOUND_VOL appears empty (size: $VOL_SIZE, bytes: $VOL_SIZE_BYTES)"
      log_error "This likely indicates volume restoration failed - database will be empty"
      NEED_VOLUME_RESTORE=true
      EMPTY_VOLUMES=$((EMPTY_VOLUMES + 1))
    else
      log_success "Volume found: $FOUND_VOL (size: $VOL_SIZE)"
    fi
    VOLUMES_FOUND=$((VOLUMES_FOUND + 1))
  else
    log_error "Volume missing: pattern *${{BRANCH_NAME}}_${{vol_type}}*"
    VOLUMES_MISSING=$((VOLUMES_MISSING + 1))
  fi
done

if [ $VOLUMES_MISSING -gt 0 ]; then
  log_error "Warning: $VOLUMES_MISSING volume(s) missing after import"
  log "This may indicate volume restoration failed"
  log "Listing all volumes for debugging:"
  docker volume ls --format "table {{{{.Name}}}}\\t{{{{.Driver}}}}\\t{{{{.Scope}}}}" | grep -E "(NAME|${{BRANCH_NAME}})" || true
  NEED_VOLUME_RESTORE=true
elif [ "$NEED_VOLUME_RESTORE" = true ]; then
  log_error "Warning: $EMPTY_VOLUMES volume(s) appear empty after import"
  log "Volume restoration may have failed or not completed"
else
  log_success "All volumes verified: $VOLUMES_FOUND volume(s) found"
fi

# Restore volumes if needed
# restore_volumes() handles stopping containers safely before restore
if [ "$NEED_VOLUME_RESTORE" = true ]; then
  log "Volumes need restoration..."
  log "Restoring volumes from package..."
  
  # In standalone mode, use direct Docker commands to restore volumes (bypasses git requirement)
  if [ "$IMPORT_MODE" = "standalone" ]; then
    log "Using standalone volume restoration (direct Docker commands)..."
    
    # Create temporary directory for extraction
    RESTORE_TEMP_DIR=$(mktemp -d)
    trap "rm -rf $RESTORE_TEMP_DIR" EXIT
    
    # Extract package to find backup archive
    log "Extracting package to find volume backups..."
    if tar -xzf "$PKG_FILE" -C "$RESTORE_TEMP_DIR" 2>/dev/null; then
      # Find the nested backup tar file
      BACKUP_TAR=$(find "$RESTORE_TEMP_DIR" -name "backup_${{BRANCH_NAME}}.tar" -o -name "backup_*.tar" | head -1)
      
      if [ -n "$BACKUP_TAR" ] && [ -f "$BACKUP_TAR" ]; then
        log "Found backup archive: $BACKUP_TAR"
        # Extract the nested backup tar
        BACKUP_EXTRACT_DIR=$(mktemp -d)
        if tar -xzf "$BACKUP_TAR" -C "$BACKUP_EXTRACT_DIR" 2>/dev/null || tar -xf "$BACKUP_TAR" -C "$BACKUP_EXTRACT_DIR" 2>/dev/null; then
          log "Backup archive extracted successfully"
          
          # Restore each volume type
          RESTORED_COUNT=0
          for vol_type in postgres_data redis_data media_files; do
            if [ -n "$PROJECT_NAME" ]; then
              VOL_NAME="${{PROJECT_NAME}}-${{BRANCH_NAME}}_${{vol_type}}"
            else
              VOL_NAME="$(basename "$ROOT2" | tr '_' '-' | tr '[:upper:]' '[:lower:]')-${{BRANCH_NAME}}_${{vol_type}}"
            fi
            
            # Find matching backup file (look for .tar.gz files with volume name pattern)
            BACKUP_FILE=$(find "$BACKUP_EXTRACT_DIR" -name "*${{vol_type}}.tar.gz" | head -1)
            
            if [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ]; then
              log "Restoring volume: $VOL_NAME from $BACKUP_FILE"
              
              # Remove existing volume if it exists and is empty
              if docker volume inspect "$VOL_NAME" >/dev/null 2>&1; then
                log "Removing existing volume $VOL_NAME to allow restoration..."
                docker volume rm "$VOL_NAME" >/dev/null 2>&1 || true
              fi
              
              # Create new volume
              if docker volume create "$VOL_NAME" >/dev/null 2>&1; then
                # Restore using docker run with tar extraction
                if docker run --rm -v "$VOL_NAME:/data" -v "$BACKUP_FILE:/backup.tar.gz:ro" alpine sh -c "cd /data && tar -xzf /backup.tar.gz --strip-components=1 2>/dev/null || tar -xzf /backup.tar.gz" >/dev/null 2>&1; then
                  log_success "Volume $VOL_NAME restored successfully"
                  RESTORED_COUNT=$((RESTORED_COUNT + 1))
                else
                  log_error "Failed to restore volume $VOL_NAME"
                fi
              else
                log_error "Failed to create volume $VOL_NAME"
              fi
            else
              log_warning "Backup file for $VOL_NAME not found (expected pattern: *${{vol_type}}.tar.gz)"
            fi
          done
          
          rm -rf "$BACKUP_EXTRACT_DIR"
          
          if [ $RESTORED_COUNT -gt 0 ]; then
            log_success "Restored $RESTORED_COUNT volume(s) successfully"
            NEED_VOLUME_RESTORE=false
          else
            log_error "No volumes were restored"
          fi
        else
          log_error "Failed to extract backup archive"
        fi
      else
        log_error "Backup archive not found in package"
        log "Trying dockertree volumes restore as fallback..."
        if "$DTBIN" volumes restore "${{BRANCH_NAME}}" "$PKG_FILE" 2>/dev/null; then
          log_success "Volumes restored successfully (using dockertree command)"
          NEED_VOLUME_RESTORE=false
        else
          log_error "Volume restoration failed - containers will start with empty volumes"
        fi
      fi
      
      rm -rf "$RESTORE_TEMP_DIR"
    else
      log_error "Failed to extract package file"
      log "Trying dockertree volumes restore as fallback..."
      if "$DTBIN" volumes restore "${{BRANCH_NAME}}" "$PKG_FILE" 2>/dev/null; then
        log_success "Volumes restored successfully (using dockertree command)"
        NEED_VOLUME_RESTORE=false
      else
        log_error "Volume restoration failed - containers will start with empty volumes"
      fi
    fi
  else
    # Normal mode: use dockertree command (requires git repository)
    if "$DTBIN" volumes restore "${{BRANCH_NAME}}" "$PKG_FILE"; then
      log_success "Volumes restored successfully"
      NEED_VOLUME_RESTORE=false
    else
      log_error "Volume restoration failed - containers will start with empty volumes"
      log_error "Database will be empty - manual restoration may be required"
    fi
  fi
fi

{build_section}

# Bring up the environment for the branch
# (Caddy proxy is already started above)
log "Bringing up worktree environment for branch: $BRANCH_NAME"
log "This may take a few minutes if containers need to be pulled or built..."

# Run with timeout and capture output
TIMEOUT=600  # 10 minutes timeout (increased for slower networks/containers)
UP_OUTPUT=$(mktemp)
UP_ERROR=$(mktemp)

# Determine the command to use based on import mode
if [ "$IMPORT_MODE" = "standalone" ]; then
  # Standalone mode: use docker compose directly (no git repository required)
  WORKTREE_PATH="$ROOT2/worktrees/${{BRANCH_NAME}}"
  COMPOSE_FILE="$WORKTREE_PATH/docker-compose.yml"
  
  if [ ! -f "$COMPOSE_FILE" ]; then
    # Try alternative location
    COMPOSE_FILE="$WORKTREE_PATH/.dockertree/docker-compose.worktree.yml"
  fi
  
  if [ -f "$COMPOSE_FILE" ]; then
    log "Using docker compose directly (standalone mode)"
    cd "$WORKTREE_PATH"
    
    # Set and EXPORT project name for docker compose
    # CRITICAL: Both variables must be exported for docker-compose.yml interpolation
    if [ -n "$PROJECT_NAME" ]; then
      export COMPOSE_PROJECT_NAME="$PROJECT_NAME-${{BRANCH_NAME}}"
    else
      export COMPOSE_PROJECT_NAME="$(basename "$ROOT2" | tr '_' '-' | tr '[:upper:]' '[:lower:]')-${{BRANCH_NAME}}"
    fi
    
    # CRITICAL: Set PROJECT_ROOT to the worktree path, NOT the project root
    # The docker-compose.yml uses $PROJECT_ROOT to locate .env and .dockertree/env.dockertree
    # These files are in the worktree directory, not the parent project directory
    export PROJECT_ROOT="$WORKTREE_PATH"
    log "Set PROJECT_ROOT=$PROJECT_ROOT"
    log "Set COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME"
    
    # Get the compose file name relative to worktree path
    COMPOSE_FILE_REL="$(basename "$COMPOSE_FILE")"
    if [ "$COMPOSE_FILE_REL" = "docker-compose.worktree.yml" ]; then
      COMPOSE_FILE_REL=".dockertree/docker-compose.worktree.yml"
    fi
    
    # Check if timeout command is available
    if command -v timeout >/dev/null 2>&1; then
      log "Running with $TIMEOUT second timeout..."
      timeout $TIMEOUT docker compose -f "$COMPOSE_FILE_REL" --env-file .dockertree/env.dockertree -p "$COMPOSE_PROJECT_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR" &
      UP_PID=$!
      
      # Show progress every 30 seconds
      ELAPSED=0
      CONTAINERS_STARTED=false
      while kill -0 $UP_PID 2>/dev/null && [ $ELAPSED -lt $TIMEOUT ]; do
        sleep 30
        ELAPSED=$((ELAPSED + 30))
        # Show container status
        RUNNING=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
        TOTAL=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
        if [ "$TOTAL" -gt 0 ]; then
          log "Still starting containers... (${{ELAPSED}}s elapsed, $RUNNING/$TOTAL running)"
          # If all containers are running, show success early
          if [ "$RUNNING" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ] && [ "$CONTAINERS_STARTED" = false ]; then
            log_success "All containers are now running!"
            CONTAINERS_STARTED=true
          fi
        else
          log "Still starting containers... (${{ELAPSED}}s elapsed)"
        fi
      done
      
      wait $UP_PID
      UP_EXIT_CODE=$?
      
      if [ $UP_EXIT_CODE -eq 124 ]; then
        log_error "Command timed out after $TIMEOUT seconds"
        log "This may indicate containers are stuck or waiting for dependencies"
      elif [ $UP_EXIT_CODE -ne 0 ]; then
        log_error "Failed to start worktree environment (exit code: $UP_EXIT_CODE)"
      fi
      
      # Post-wait verification: check if containers are actually running
      # Even if the command timed out or failed, containers might have started successfully
      log "Verifying container status after command completion..."
      sleep 2  # Brief pause for containers to register
      RUNNING_AFTER=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      TOTAL_AFTER=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      
      if [ "$TOTAL_AFTER" -gt 0 ] && [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
        log_success "All $RUNNING_AFTER container(s) are running successfully"
        log "Container startup completed successfully despite command exit code"
        UP_EXIT_CODE=0  # Override exit code since containers are healthy
      elif [ "$RUNNING_AFTER" -gt 0 ]; then
        log "Container status: $RUNNING_AFTER/$TOTAL_AFTER running"
        if [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
          log_success "All containers are running - deployment successful"
          UP_EXIT_CODE=0  # Override exit code since all containers are running
        else
          log_warning "Some containers are not running - checking status..."
        fi
      fi
    else
      log "Timeout command not available, running without timeout..."
      if docker compose -f "$COMPOSE_FILE_REL" --env-file .dockertree/env.dockertree -p "$COMPOSE_PROJECT_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR"; then
        UP_EXIT_CODE=0
      else
        UP_EXIT_CODE=$?
        log_error "Failed to start worktree environment (exit code: $UP_EXIT_CODE)"
      fi
      
      # Post-command verification: check if containers are actually running
      # Even if the command failed, containers might have started successfully
      log "Verifying container status after command completion..."
      sleep 2  # Brief pause for containers to register
      RUNNING_AFTER=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      TOTAL_AFTER=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      
      if [ "$TOTAL_AFTER" -gt 0 ] && [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
        log_success "All $RUNNING_AFTER container(s) are running successfully"
        log "Container startup completed successfully despite command exit code"
        UP_EXIT_CODE=0  # Override exit code since containers are healthy
      elif [ "$RUNNING_AFTER" -gt 0 ]; then
        log "Container status: $RUNNING_AFTER/$TOTAL_AFTER running"
        if [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
          log_success "All containers are running - deployment successful"
          UP_EXIT_CODE=0  # Override exit code since all containers are running
        else
          log_warning "Some containers are not running - checking status..."
        fi
      fi
    fi
    
    cd "$ROOT2"
  else
    log_error "Docker Compose file not found: $COMPOSE_FILE"
    log_error "Cannot start containers in standalone mode"
    UP_EXIT_CODE=1
  fi
else
  # Normal mode: use dockertree command (requires git repository)
  if command -v timeout >/dev/null 2>&1; then
    log "Running with $TIMEOUT second timeout..."
    # Run command with timeout in background and monitor progress
    timeout $TIMEOUT "$DTBIN" "$BRANCH_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR" &
    UP_PID=$!
    
    # Show progress every 30 seconds
    ELAPSED=0
    CONTAINERS_STARTED=false
    while kill -0 $UP_PID 2>/dev/null && [ $ELAPSED -lt $TIMEOUT ]; do
      sleep 30
      ELAPSED=$((ELAPSED + 30))
      # Show container status
      RUNNING=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      TOTAL=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      if [ "$TOTAL" -gt 0 ]; then
        log "Still starting containers... (${{ELAPSED}}s elapsed, $RUNNING/$TOTAL running)"
        # If all containers are running, show success early
        if [ "$RUNNING" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ] && [ "$CONTAINERS_STARTED" = false ]; then
          log_success "All containers are now running!"
          CONTAINERS_STARTED=true
        fi
      else
        log "Still starting containers... (${{ELAPSED}}s elapsed)"
      fi
    done
    
    wait $UP_PID
    UP_EXIT_CODE=$?
    
    if [ $UP_EXIT_CODE -eq 124 ]; then
      log_error "Command timed out after $TIMEOUT seconds"
      log "This may indicate containers are stuck or waiting for dependencies"
    elif [ $UP_EXIT_CODE -ne 0 ]; then
      log_error "Failed to start worktree environment (exit code: $UP_EXIT_CODE)"
    fi
    
    # Post-wait verification: check if containers are actually running
    # Even if the command timed out or failed, containers might have started successfully
    log "Verifying container status after command completion..."
    sleep 2  # Brief pause for containers to register
    RUNNING_AFTER=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
    TOTAL_AFTER=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
    
    if [ "$TOTAL_AFTER" -gt 0 ] && [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
      log_success "All $RUNNING_AFTER container(s) are running successfully"
      log "Container startup completed successfully despite command exit code"
      UP_EXIT_CODE=0  # Override exit code since containers are healthy
    elif [ "$RUNNING_AFTER" -gt 0 ]; then
      log "Container status: $RUNNING_AFTER/$TOTAL_AFTER running"
      if [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
        log_success "All containers are running - deployment successful"
        UP_EXIT_CODE=0  # Override exit code since all containers are running
      else
        log_warning "Some containers are not running - checking status..."
      fi
    fi
  else
    log "Timeout command not available, running without timeout..."
    if "$DTBIN" "$BRANCH_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR"; then
      UP_EXIT_CODE=0
    else
      UP_EXIT_CODE=$?
      log_error "Failed to start worktree environment (exit code: $UP_EXIT_CODE)"
    fi
    
    # Post-command verification: check if containers are actually running
    # Even if the command failed, containers might have started successfully
    log "Verifying container status after command completion..."
    sleep 2  # Brief pause for containers to register
    RUNNING_AFTER=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
    TOTAL_AFTER=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
    
    if [ "$TOTAL_AFTER" -gt 0 ] && [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
      log_success "All $RUNNING_AFTER container(s) are running successfully"
      log "Container startup completed successfully despite command exit code"
      UP_EXIT_CODE=0  # Override exit code since containers are healthy
    elif [ "$RUNNING_AFTER" -gt 0 ]; then
      log "Container status: $RUNNING_AFTER/$TOTAL_AFTER running"
      if [ "$RUNNING_AFTER" -eq "$TOTAL_AFTER" ]; then
        log_success "All containers are running - deployment successful"
        UP_EXIT_CODE=0  # Override exit code since all containers are running
      else
        log_warning "Some containers are not running - checking status..."
      fi
    fi
  fi
fi

# Show output
if [ -s "$UP_OUTPUT" ]; then
  log "Command output:"
  while IFS= read -r line; do
    log "  $line"
  done < "$UP_OUTPUT"
fi

if [ -s "$UP_ERROR" ]; then
  log "Command errors:"
  while IFS= read -r line; do
    log_error "  $line"
  done < "$UP_ERROR"
fi

rm -f "$UP_OUTPUT" "$UP_ERROR"

if [ $UP_EXIT_CODE -eq 0 ]; then
  log_success "Worktree environment started successfully"
elif [ "$CONTAINERS_STARTED" = true ]; then
  log_success "Containers are running (command may have completed in background)"
else
  log_warning "Container startup command exited with code $UP_EXIT_CODE, but checking status..."
fi

# Wait a moment for containers to initialize
log "Waiting for containers to initialize..."
sleep 5

# Final verification: check if containers are running
log "Verifying containers are running..."
CONTAINERS_RUNNING=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
CONTAINERS_TOTAL=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)

log "Container status: $CONTAINERS_RUNNING running out of $CONTAINERS_TOTAL total"

if [ "$CONTAINERS_TOTAL" -gt 0 ]; then
  log "Container details:"
  docker ps -a --filter "name=${{BRANCH_NAME}}" --format "table {{{{.Names}}}}\\t{{{{.Status}}}}\\t{{{{.State}}}}" >&2
  
  # Check for unhealthy or exited containers
  UNHEALTHY=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --filter "status=exited" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
  if [ "$UNHEALTHY" -gt 0 ]; then
    log_error "Found $UNHEALTHY exited container(s), showing logs..."
    for container in $(docker ps -a --filter "name=${{BRANCH_NAME}}" --filter "status=exited" --format "{{{{.Names}}}}" 2>/dev/null); do
      log_error "Logs for $container:"
      docker logs --tail 50 "$container" 2>&1 | head -20 | while IFS= read -r line; do
        log_error "  $line"
      done
    done
  fi
  
  # Check for restarting containers
  RESTARTING=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --filter "status=restarting" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
  if [ "$RESTARTING" -gt 0 ]; then
    log_error "Found $RESTARTING container(s) in restart loop, showing recent logs..."
    for container in $(docker ps -a --filter "name=${{BRANCH_NAME}}" --filter "status=restarting" --format "{{{{.Names}}}}" 2>/dev/null); do
      log_error "Recent logs for $container:"
      docker logs --tail 30 "$container" 2>&1 | head -15 | while IFS= read -r line; do
        log_error "  $line"
      done
    done
  fi
else
  log_error "No containers found for branch $BRANCH_NAME"
  log "This may indicate the worktree was not created correctly"
fi

# Check volume sizes again to verify they have data
log "Re-checking volume sizes to verify data was restored..."
for vol_type in postgres_data redis_data media_files; do
  if [ -n "$PROJECT_NAME" ]; then
    VOL_NAME="${{PROJECT_NAME}}-${{BRANCH_NAME}}_${{vol_type}}"
    if docker volume inspect "$VOL_NAME" >/dev/null 2>&1; then
      VOL_SIZE=$(docker volume inspect "$VOL_NAME" --format '{{{{.Mountpoint}}}}' | xargs du -sh 2>/dev/null | cut -f1 || echo "unknown")
      VOL_SIZE_BYTES=$(docker volume inspect "$VOL_NAME" --format '{{{{.Mountpoint}}}}' | xargs du -sb 2>/dev/null | cut -f1 || echo "0")
      # 4KB = 4096 bytes, anything close to this is likely empty
      if [ "$VOL_SIZE_BYTES" -lt 10000 ] && [ "$VOL_SIZE_BYTES" -gt 0 ]; then
        log_error "WARNING: Volume $VOL_NAME appears empty (size: $VOL_SIZE, bytes: $VOL_SIZE_BYTES)"
        log "This may indicate volume restoration failed - database may not have data"
      else
        log "Volume $VOL_NAME size: $VOL_SIZE"
      fi
    fi
  fi
done

if [ "$CONTAINERS_RUNNING" -gt 0 ]; then
  log_success "$CONTAINERS_RUNNING container(s) running for branch $BRANCH_NAME"
else
  log_error "No containers are running - deployment may have failed"
  log "Check container logs above for details"
fi

# Domain configuration updates and Caddy route refresh
{domain_config_section}

log_success "=== Remote import process completed ==="
exit 0
"""
        return script
    
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
                log_error("DNS API token not found. Set DIGITALOCEAN_API_TOKEN environment variable, or use --dns-token")
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
        """Resolve server hostname to IP address.
        
        Args:
            server: Server hostname or IP address
            
        Returns:
            IP address string
        """
        # Check if it's already an IP address
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', server):
            return server
        
        # Try to resolve hostname
        try:
            ip = socket.gethostbyname(server)
            log_info(f"Resolved {server} to {ip}")
            return ip
        except socket.gaierror:
            log_warning(f"Could not resolve {server} to IP, using as-is")
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
                                 api_token: Optional[str] = None,
                                 vpc_uuid: Optional[str] = None):
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
                log_error("Digital Ocean API token not found. Set DIGITALOCEAN_API_TOKEN environment variable, or use --dns-token")
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
                tags=None,
                vpc_uuid=vpc_uuid
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
                add_ssh_host_key(droplet.ip_address)
                log_info("SSH host key added successfully")
            else:
                log_error("Droplet IP address not available. Cannot proceed with push.")
                return None
            
            log_info("Droplet creation process completed")
            return droplet
            
        except Exception as e:
            log_error(f"Error creating droplet: {e}")
            return None
    
    def _resolve_push_config(self, branch_name: Optional[str], scp_target: Optional[str],
                            domain: Optional[str], ip: Optional[str]) -> Dict[str, Optional[str]]:
        """Resolve push configuration by merging env.dockertree config with CLI arguments.
        
        CLI arguments override stored configuration. Validates required parameters.
        If branch_name is not provided, searches worktrees for one with push config.
        
        Args:
            branch_name: Branch name from CLI (optional)
            scp_target: SCP target from CLI (optional)
            domain: Domain from CLI (optional)
            ip: IP from CLI (optional)
            
        Returns:
            Dictionary with resolved configuration (scp_target, branch_name, domain, ip)
        """
        from ..core.environment_manager import EnvironmentManager
        from ..config.settings import get_worktree_paths
        
        env_manager = EnvironmentManager(project_root=self.project_root)
        
        # If branch_name not provided, try to find worktree with push config
        if not branch_name:
            log_info("Branch name not provided, searching worktrees for push configuration...")
            worktree_dir = self.project_root / "worktrees"
            if worktree_dir.exists():
                for worktree_path in worktree_dir.iterdir():
                    if worktree_path.is_dir():
                        potential_branch = worktree_path.name
                        config = env_manager.get_push_config(potential_branch)
                        if config.get('scp_target') and config.get('branch_name'):
                            branch_name = potential_branch
                            log_info(f"Found push config in worktree: {branch_name}")
                            break
        
        # Get stored config from env.dockertree
        stored_config = env_manager.get_push_config(branch_name or '')
        
        # Merge with CLI arguments (CLI overrides stored config)
        resolved = {
            'scp_target': scp_target or stored_config.get('scp_target'),
            'branch_name': branch_name or stored_config.get('branch_name'),
            'domain': domain if domain is not None else stored_config.get('domain'),
            'ip': ip if ip is not None else stored_config.get('ip')
        }
        
        # Validate required parameters
        if not resolved['scp_target']:
            log_error("scp_target is required. Provide via CLI argument or set PUSH_SCP_TARGET in env.dockertree")
            return {}
        
        if not resolved['branch_name']:
            log_error("branch_name is required. Provide via CLI argument or set PUSH_BRANCH_NAME in env.dockertree")
            return {}
        
        # Validate mutual exclusivity
        if resolved['domain'] and resolved['ip']:
            log_error("Options --domain and --ip are mutually exclusive")
            return {}
        
        return resolved
    
    def _detect_code_storage_method(self, branch_name: str) -> Tuple[str, Optional[list]]:
        """Detect whether code is stored in a Docker volume or bind mount.
        
        Checks docker-compose.yml and docker-compose.worktree.yml for volumes
        mounted to common code paths.
        
        Args:
            branch_name: Branch name for the worktree
            
        Returns:
            Tuple of (storage_method, code_volume_names)
            storage_method: 'volume' if code is in a named volume, 'bind_mount' otherwise
            code_volume_names: List of volume names containing code (None if bind mount)
        """
        try:
            import yaml
            from ..config.settings import get_worktree_paths, sanitize_project_name, get_project_name
            from ..utils.path_utils import get_compose_override_path
            
            worktree_path, _ = get_worktree_paths(branch_name)
            compose_file = get_compose_override_path(worktree_path)
            
            if not compose_file or not compose_file.exists():
                # Fall back to project root compose file
                compose_file = self.project_root / ".dockertree" / "docker-compose.worktree.yml"
            
            if not compose_file.exists():
                log_warning("Could not find docker-compose file for code storage detection, assuming bind mount")
                return ('bind_mount', None)
            
            with open(compose_file) as f:
                compose_data = yaml.safe_load(f)
            
            if not compose_data or 'services' not in compose_data:
                return ('bind_mount', None)
            
            # Common code paths (exact matches, not subdirectories)
            code_paths = ['/app', '/code', '/src', '/usr/src/app', '/var/www', '/srv/app']
            code_volumes = []
            has_bind_mount = False
            
            # Get project name for volume name resolution
            project_name = sanitize_project_name(get_project_name())
            compose_project_name = f"{project_name}-{branch_name}"
            
            # Check each service for volume mounts to code paths
            for service_name, service_config in compose_data['services'].items():
                volumes = service_config.get('volumes', [])
                if isinstance(volumes, list):
                    for volume in volumes:
                        if isinstance(volume, str):
                            # Check for named volume mount (format: volume_name:/path or volume_name:/path:ro)
                            parts = volume.split(':')
                            if len(parts) >= 2:
                                volume_name = parts[0]
                                mount_path = parts[1]
                                
                                # Check if mount path is exactly a code path (not a subdirectory)
                                if mount_path in code_paths:
                                    # Check if it's a bind mount (starts with / or . or relative path)
                                    if volume_name.startswith('/') or volume_name.startswith('.') or '/' in volume_name:
                                        has_bind_mount = True
                                        log_info(f"Detected code in bind mount: {volume_name} -> {mount_path}")
                                    # Check if it's a named volume (not a bind mount)
                                    elif not volume_name.startswith('$'):
                                        # Resolve volume name (may contain ${COMPOSE_PROJECT_NAME})
                                        resolved_volume_name = volume_name.replace('${COMPOSE_PROJECT_NAME}', compose_project_name)
                                        code_volumes.append(resolved_volume_name)
                                        log_info(f"Detected code in volume: {resolved_volume_name} mounted at {mount_path}")
            
            # Prefer bind mount if found (more common)
            if has_bind_mount:
                log_info("Code detected in bind mount, using archive-based update")
                return ('bind_mount', None)
            
            if code_volumes:
                return ('volume', code_volumes)
            
            # Default to bind mount if no code volumes found
            log_info("No code volumes detected, assuming bind mount")
            return ('bind_mount', None)
            
        except Exception as e:
            log_warning(f"Error detecting code storage method: {e}, assuming bind mount")
            return ('bind_mount', None)
    
    def _prepare_code_update(self, branch_name: str, storage_method: str, 
                            code_volumes: Optional[list], output_dir: Path) -> Optional[Path]:
        """Prepare code update file (volume backup or archive).
        
        Args:
            branch_name: Branch name for the worktree
            storage_method: 'volume' or 'bind_mount'
            code_volumes: List of code volume names (only used when storage_method is 'volume')
            output_dir: Directory to save the update file
            
        Returns:
            Path to the file to transfer, or None if preparation failed
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if storage_method == 'volume' and code_volumes:
            # Backup code volume(s) only
            log_info(f"Preparing code volume backup for volumes: {', '.join(code_volumes)}...")
            
            # Create temporary backup directory
            import tempfile
            import shutil
            import tarfile
            
            temp_backup_dir = output_dir / "temp_code_backup"
            temp_backup_dir.mkdir(exist_ok=True)
            
            try:
                # Backup each code volume
                for volume_name in code_volumes:
                    from ..utils.validation import validate_volume_exists
                    if not validate_volume_exists(volume_name):
                        log_warning(f"Code volume {volume_name} not found, skipping")
                        continue
                    
                    log_info(f"Backing up code volume: {volume_name}")
                    volume_backup = temp_backup_dir / f"{volume_name}.tar.gz"
                    
                    try:
                        subprocess.run([
                            "docker", "run", "--rm",
                            "-v", f"{volume_name}:/data:ro",
                            "-v", f"{temp_backup_dir.absolute()}:/backup",
                            "alpine", "tar", "czf", f"/backup/{volume_name}.tar.gz", "-C", "/data", "."
                        ], check=True, capture_output=True, text=True)
                        log_success(f"Code volume backup created: {volume_name}.tar.gz")
                    except subprocess.CalledProcessError as e:
                        log_error(f"Failed to backup code volume {volume_name}: {e}")
                        if e.stderr:
                            log_error(f"Error details: {e.stderr}")
                        continue
                
                # Create combined backup file
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_file = output_dir / f"{branch_name}_code_volumes_{timestamp}.tar.gz"
                
                with tarfile.open(backup_file, 'w:gz') as tar:
                    tar.add(temp_backup_dir, arcname='.')
                
                # Cleanup temp directory
                shutil.rmtree(temp_backup_dir)
                
                log_success(f"Code volume backup created: {backup_file}")
                return backup_file
                
            except Exception as e:
                log_error(f"Failed to create code volume backup: {e}")
                if temp_backup_dir.exists():
                    shutil.rmtree(temp_backup_dir)
                return None
        else:
            # Create code archive
            log_info("Creating code archive...")
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive_path = output_dir / f"{branch_name}_code_{timestamp}.tar.gz"
            
            from ..core.git_manager import GitManager
            git_manager = GitManager(project_root=self.project_root, validate=False)
            
            if git_manager.create_worktree_archive(branch_name, archive_path):
                log_success(f"Code archive created: {archive_path}")
                return archive_path
            else:
                log_error("Failed to create code archive")
                return None
    
    def _compose_code_update_script(self, branch_name: str, remote_file: str, 
                                    storage_method: str, code_volumes: Optional[list] = None, build: bool = False) -> str:
        """Compose unified remote script for code update.
        
        Args:
            branch_name: Branch name for the worktree
            remote_file: Path to update file on remote server
            storage_method: 'volume' or 'bind_mount'
            code_volumes: List of code volume names (for volume method)
            build: Whether to rebuild Docker images after code update
            
        Returns:
            Bash script string for remote execution
        """
        # Determine update command based on storage method
        if storage_method == 'volume' and code_volumes:
            # Volume restore - extract backup and restore each code volume
            # Note: Volume names on remote may differ due to project name resolution
            # We'll try exact match first, then search for matching volumes
            volume_restore_commands = []
            for vol_name in code_volumes:
                # Escape volume name for use in shell script
                vol_name_escaped = vol_name.replace('"', '\\"')
                # Extract base volume name (last part after underscore) for matching
                vol_base_name = vol_name.split('_')[-1] if '_' in vol_name else vol_name
                volume_restore_commands.append(f'''
# Restore code volume: {vol_name_escaped}
log "Restoring code volume: {vol_name_escaped}"
VOL_BACKUP="$TEMP_DIR/{vol_name_escaped}.tar.gz"

# Find actual volume name on remote (may have different project prefix)
# Try exact match first, then search by base name
ACTUAL_VOL="{vol_name_escaped}"
if ! docker volume inspect "$ACTUAL_VOL" >/dev/null 2>&1; then
  # Try to find volume by base name
  ACTUAL_VOL=$(docker volume ls --format "{{{{{{.Name}}}}}}" | grep -E "_{vol_base_name}$" | head -1 || echo "")
  if [ -z "$ACTUAL_VOL" ]; then
    log_error "Code volume not found on server. Expected: {vol_name_escaped} or *_{vol_base_name}"
    exit 1
  fi
  log "Volume name differs on server: $ACTUAL_VOL (expected: {vol_name_escaped})"
fi

if [ -f "$VOL_BACKUP" ]; then
  # Remove existing volume data and restore
  log "Clearing existing volume data..."
  docker run --rm -v "$ACTUAL_VOL:/data" alpine sh -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null || true"
  
  log "Restoring code to volume..."
  docker run --rm -v "$ACTUAL_VOL:/data" -v "$TEMP_DIR:/backup:ro" alpine tar -xzf "/backup/{vol_name_escaped}.tar.gz" -C /data
  if [ $? -eq 0 ]; then
    log_success "Code volume $ACTUAL_VOL restored successfully"
  else
    log_error "Failed to restore code volume $ACTUAL_VOL"
    exit 1
  fi
else
  log_error "Volume backup not found: $VOL_BACKUP"
  exit 1
fi
''')
            
            update_command = f'''
# Extract volume backup archive
log "Extracting volume backup archive..."
TEMP_DIR=$(mktemp -d)
tar -xzf "{remote_file}" -C "$TEMP_DIR"
if [ $? -ne 0 ]; then
  log_error "Failed to extract volume backup archive"
  exit 1
fi
log_success "Volume backup archive extracted"

{''.join(volume_restore_commands)}

# Cleanup temp directory
rm -rf "$TEMP_DIR"
'''
        else:
            # Archive extraction - need to find worktree path
            update_command = f'''
# Find worktree directory
WORKTREE_PATH="$(find /root -maxdepth 3 -type d -path "*/worktrees/{branch_name}" -print -quit 2>/dev/null || true)"
if [ -z "$WORKTREE_PATH" ]; then
  log_error "Worktree directory not found for branch: {branch_name}"
  exit 1
fi
log "Found worktree at: $WORKTREE_PATH"

# Extract archive
log "Extracting code archive to worktree..."
tar -xzf "{remote_file}" -C "$WORKTREE_PATH" --strip-components=0
if [ $? -ne 0 ]; then
  log_error "Failed to extract code archive"
  exit 1
fi
log_success "Code archive extracted successfully"
'''
        
        # Build section - only included if build is True
        if build:
            build_section = f'''
# Rebuild Docker images
log "Rebuilding Docker images for branch: {branch_name}"

# Clear BuildKit cache to avoid corruption issues after code extraction
log "Clearing Docker BuildKit cache to prevent corruption..."
if docker builder prune -f --filter type=exec.cachemount >/dev/null 2>&1; then
  log_success "BuildKit cache cleared successfully"
elif docker builder prune -f >/dev/null 2>&1; then
  log_success "BuildKit cache cleared (fallback method)"
else
  log_warning "Failed to clear BuildKit cache, continuing with build anyway"
fi

# Attempt build with cache first, fallback to --no-cache if needed
log "Building Docker images..."
BUILD_SUCCESS=false
if "$DTBIN" "{branch_name}" build; then
  log_success "Images rebuilt successfully"
  BUILD_SUCCESS=true
else
  log_warning "Build failed, retrying with --no-cache flag..."
  if "$DTBIN" "{branch_name}" build --no-cache; then
    log_success "Images rebuilt successfully (without cache)"
    BUILD_SUCCESS=true
  else
    log_error "Failed to rebuild images even with --no-cache"
    BUILD_SUCCESS=false
  fi
fi

if [ "$BUILD_SUCCESS" != "true" ]; then
  exit 1
fi

log_success "Build process completed successfully"
'''
        else:
            build_section = ''
        
        script = f"""
set -euo pipefail

# Logging helper functions (reuse from _compose_remote_script pattern)
log() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}}

log_success() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*" >&2
}}

log_error() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✗ $*" >&2
}}

log_warning() {{
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ $*" >&2
}}

log "=== Starting code update process ==="
log "Branch name: {branch_name}"
log "Storage method: {storage_method}"
log "Update file: {remote_file}"

# Determine dockertree binary (reuse from _compose_remote_script)
log "Locating dockertree binary..."
if [ -x /opt/dockertree-venv/bin/dockertree ]; then
  DTBIN=/opt/dockertree-venv/bin/dockertree
  log "Using dockertree from /opt/dockertree-venv/bin/dockertree"
elif command -v dockertree >/dev/null 2>&1; then
  DTBIN="$(command -v dockertree)"
  log "Using dockertree from PATH: $DTBIN"
else
  DTBIN=dockertree
  log "Using dockertree from PATH (fallback)"
fi

# Verify dockertree works
if ! "$DTBIN" --version >/dev/null 2>&1; then
  log_error "dockertree binary not working: $DTBIN"
  exit 1
fi
log_success "dockertree binary verified: $($DTBIN --version 2>&1 | head -1)"

# Find project root (reuse from _compose_remote_script)
log "Detecting existing dockertree project..."
HIT="$(find /root -maxdepth 3 -type f -path '*/.dockertree/config.yml' -print -quit 2>/dev/null || true)"
if [ -z "$HIT" ]; then
  log_error "No dockertree project found on server"
  exit 1
fi
ROOT="$(dirname "$(dirname "$HIT")")"
log "Found project at: $ROOT"
cd "$ROOT"

# Verify update file exists
log "Verifying update file exists..."
if [ ! -f "{remote_file}" ]; then
  log_error "Update file not found: {remote_file}"
  exit 1
fi
FILE_SIZE=$(du -h "{remote_file}" | cut -f1)
log_success "Update file found: {remote_file} ($FILE_SIZE)"

# Stop containers
log "Stopping containers for branch: {branch_name}"
if "$DTBIN" "{branch_name}" down; then
  log_success "Containers stopped successfully"
else
  log_warning "Failed to stop containers (may not be running)"
fi

# Update code
log "Updating code..."
{update_command}

{build_section}

# Restart containers
log "Restarting containers for branch: {branch_name}"
if "$DTBIN" "{branch_name}" up -d; then
  log_success "Containers restarted successfully"
else
  log_error "Failed to restart containers"
  exit 1
fi

# Verify containers are running
log "Verifying containers are running..."
sleep 2
CONTAINERS_RUNNING=$(docker ps --filter "name={branch_name}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
if [ "$CONTAINERS_RUNNING" -gt 0 ]; then
  log_success "$CONTAINERS_RUNNING container(s) running for branch {branch_name}"
else
  log_warning "No containers running - check logs with: dockertree {branch_name} logs"
fi

log_success "=== Code update process completed ==="
"""
        return script
    
    def _validate_code_update_prerequisites(self, config: Dict[str, Optional[str]], 
                                           branch_name: str, storage_method: str) -> bool:
        """Validate prerequisites for code update.
        
        Args:
            config: Resolved push configuration
            branch_name: Branch name for the worktree
            storage_method: 'volume' or 'bind_mount'
            
        Returns:
            True if all prerequisites are met, False otherwise
        """
        # Validate config
        if not config or not config.get('scp_target') or not config.get('branch_name'):
            return False
        
        # Parse SCP target to get server info
        username, server, _ = self._parse_scp_target(config['scp_target'])
        
        # Verify dockertree installed on server
        if not self._verify_dockertree_installed(username, server):
            log_error("dockertree not found on server. Run with --prepare-server first.")
            return False
        
        # For volumes, verify code volume exists
        if storage_method == 'volume':
            # This is a simplified check - in practice, we'd need to check on the server
            log_info("Code volume validation will be performed on server during update")
        
        return True
    
    def _push_code_only(self, branch_name: Optional[str], scp_target: Optional[str],
                       domain: Optional[str], ip: Optional[str], output_dir: Path, build: bool = False) -> bool:
        """Push code-only update to remote server.
        
        Args:
            branch_name: Branch name (optional, can be from config)
            scp_target: SCP target (optional, can be from config)
            domain: Domain override (optional)
            ip: IP override (optional)
            output_dir: Directory for temporary files
            build: Whether to rebuild Docker images after code update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            log_info("Starting code-only push operation...")
            
            # Resolve configuration (will auto-detect branch from worktrees if needed)
            config = self._resolve_push_config(branch_name, scp_target, domain, ip)
            if not config:
                return False
            
            resolved_branch = config['branch_name']
            resolved_scp = config['scp_target']
            
            # Detect code storage method
            storage_method, code_volumes = self._detect_code_storage_method(resolved_branch)
            log_info(f"Detected code storage method: {storage_method}")
            if code_volumes:
                log_info(f"Code volumes: {', '.join(code_volumes)}")
            
            # Validate prerequisites
            if not self._validate_code_update_prerequisites(config, resolved_branch, storage_method):
                return False
            
            # Prepare code update
            update_file = self._prepare_code_update(resolved_branch, storage_method, code_volumes, output_dir)
            if not update_file:
                return False
            
            # Parse SCP target
            username, server, remote_path = self._parse_scp_target(resolved_scp)
            
            # Ensure remote directory exists
            remote_dir = self._infer_remote_directory(remote_path)
            if remote_dir and remote_dir not in ['.', '']:
                self._ensure_remote_dir(username, server, remote_dir)
            
            # Transfer file
            remote_file_path = f"{remote_path}/{update_file.name}" if not remote_path.endswith('/') else f"{remote_path}{update_file.name}"
            remote_scp_target = f"{username}@{server}:{remote_file_path}"
            
            log_info(f"Transferring update file to {server}...")
            if not self._scp_transfer(update_file, f"{username}@{server}:{remote_path}"):
                log_error("Failed to transfer update file to remote server")
                return False
            
            log_success(f"Update file transferred successfully")
            
            # Compose and execute remote script
            script = self._compose_code_update_script(resolved_branch, remote_file_path, storage_method, code_volumes, build)
            
            exec_cmd = "cat > /tmp/dtcodeupdate.sh && chmod +x /tmp/dtcodeupdate.sh && /tmp/dtcodeupdate.sh && rm -f /tmp/dtcodeupdate.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            
            log_info("Executing remote code update script...")
            if build:
                log_info("This will: stop containers, update code, rebuild images, and restart containers")
            else:
                log_info("This will: stop containers, update code, and restart containers")
            
            # Use streaming execution (reuse pattern from _run_remote_import)
            from ..utils.streaming import execute_with_streaming
            success, stdout_lines, stderr_lines = execute_with_streaming(
                cmd,
                script=script,
                timeout=600,  # 10 minutes
                progress_interval=30,
                prefix="  ",
                filter_keywords=None
            )
            
            if not success:
                log_error("Remote code update failed")
                if stderr_lines:
                    log_error("Update errors:")
                    for line in stderr_lines:
                        log_error(f"  {line}")
                return False
            
            log_success("Code update completed successfully")
            
            # Save push configuration for future use
            from ..core.environment_manager import EnvironmentManager
            env_manager = EnvironmentManager(project_root=self.project_root)
            env_manager.save_push_config(
                resolved_branch,
                resolved_scp,
                config.get('domain'),
                config.get('ip')
            )
            
            return True
            
        except Exception as e:
            log_error(f"Error in code-only push: {e}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")
            return False

