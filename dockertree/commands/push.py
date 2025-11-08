"""
Push command for deploying dockertree packages to remote servers.

This module provides functionality to export dockertree packages and transfer
them to remote servers via SCP for deployment.
"""

import subprocess
import re
import socket
from pathlib import Path
from typing import Optional, Tuple

from ..core.package_manager import PackageManager
from ..core.dns_manager import DNSManager, parse_domain, is_domain
from ..core.droplet_manager import DropletManager
# Import DNS providers to trigger registration
from ..core import dns_providers  # noqa: F401
from ..utils.logging import log_info, log_success, log_warning, log_error, print_plain
from ..utils.path_utils import detect_execution_context, get_worktree_branch_name
from ..utils.confirmation import confirm_action
from ..utils.ssh_utils import add_ssh_host_key


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
    
    def push_package(self, branch_name: Optional[str], scp_target: str, 
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
                    wait_for_droplet: bool = False) -> bool:
        """Export and push package to remote server via SCP.
        
        Args:
            branch_name: Branch/worktree name (optional, auto-detects if not provided)
            scp_target: SCP target in format username@server:path
            output_dir: Temporary package location (default: ./packages)
            keep_package: Don't delete package after successful push
            
        Returns:
            True if successful, False otherwise
        """
        try:
            log_info("Starting push operation...")
            
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
            
            # Validate SCP target format
            log_info(f"Validating SCP target format: {scp_target}")
            if not self._validate_scp_target(scp_target):
                log_error(f"Invalid SCP target format: {scp_target}")
                log_info("Expected format: username@server:path")
                return False
            log_info("SCP target format is valid")
            
            # Parse SCP target (may be updated if droplet is created)
            username, server, remote_path = self._parse_scp_target(scp_target)
            log_info(f"Parsed SCP target - Username: {username}, Server: {server}, Remote Path: {remote_path}")
            
            # Create droplet if requested
            if create_droplet:
                log_info("Droplet creation requested, creating new droplet...")
                droplet_info = self._create_droplet_for_push(
                    droplet_name=droplet_name or branch_name,
                    droplet_region=droplet_region,
                    droplet_size=droplet_size,
                    droplet_image=droplet_image,
                    droplet_ssh_keys=droplet_ssh_keys,
                    wait_for_droplet=wait_for_droplet,
                    api_token=dns_token
                )
                if not droplet_info:
                    log_error("Failed to create droplet. Aborting push.")
                    return False
                
                # Update server to use droplet IP
                if droplet_info.ip_address:
                    server = droplet_info.ip_address
                    scp_target = f"{username}@{server}:{remote_path}"
                    log_info(f"Updated SCP target to use droplet IP address: {server}")
                else:
                    log_warning("Droplet created but IP address not available yet. Continuing with original server...")
            else:
                log_info("No droplet creation requested, using provided server")
            
            # Handle DNS management if domain is provided
            if domain and not skip_dns_check:
                log_info(f"Domain provided: {domain}, managing DNS records...")
                dns_success = self._handle_dns_management(domain, server, dns_token)
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
            export_result = self.package_manager.export_package(
                branch_name=branch_name,
                output_dir=output_dir,
                include_code=True,  # Always include code for deployments
                compressed=True     # Always compress for faster transfer
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
            log_info(f"Package size: {package_size_mb:.2f} MB")
            
            # Ensure remote directory exists
            remote_dir = self._infer_remote_directory(remote_path)
            log_info(f"Inferred remote directory: {remote_dir}")
            if remote_dir and remote_dir not in ['.', '']:
                log_info(f"Ensuring remote directory exists: {remote_dir}")
                self._ensure_remote_dir(username, server, remote_dir)
            else:
                log_info("Remote directory is current directory, skipping directory creation")

            # Auto-import requires server preparation
            if auto_import and not prepare_server:
                log_info("Auto-import requires server preparation. Enabling --prepare-server...")
                prepare_server = True

            # Prepare server dependencies if requested (before upload/import)
            if prepare_server:
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
            else:
                log_info("Server preparation skipped (--prepare-server not specified)")

            # Transfer package via SCP
            log_info(f"Starting SCP transfer to {server}...")
            log_info(f"Source: {package_path}")
            log_info(f"Destination: {scp_target}")
            if not self._scp_transfer(package_path, scp_target):
                log_error("Failed to transfer package to remote server")
                return False
            
            log_success(f"Package pushed successfully to {scp_target}")
            log_info("SCP transfer completed")
            
            # Display package info and next steps
            package_size_mb = package_path.stat().st_size / 1024 / 1024
            print_plain(f"\n📦 Package: {package_path.name}")
            print_plain(f"📁 Remote Location: {scp_target}")
            print_plain(f"💾 Size: {package_size_mb:.1f} MB")
            print_plain(f"\n📋 Next Steps:")
            print_plain(f"   1. SSH to the server:")
            print_plain(f"      ssh {username}@{server}")
            print_plain(f"   ")
            print_plain(f"   2. Import the package:")
            print_plain(f"      dockertree packages import {remote_path}/{package_path.name} --standalone")
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
                log_info(f"Remote package path: {remote_path}/{package_path.name}")
                log_info(f"Branch name: {branch_name}")
                if domain:
                    log_info(f"Domain override: {domain}")
                if ip:
                    log_info(f"IP override: {ip}")
                self._run_remote_import(username, server, f"{remote_path}/{package_path.name}", branch_name, domain, ip)
                log_info("Remote import process initiated")
            else:
                log_info("Auto-import disabled, manual import required")

            # Clean up package unless keep_package is True
            if not keep_package and package_path.exists():
                log_info("Cleaning up local package file...")
                try:
                    package_path.unlink()
                    log_info(f"Cleaned up local package: {package_path.name}")
                except Exception as e:
                    log_warning(f"Failed to clean up package: {e}")
            else:
                log_info(f"Keeping local package (--keep-package flag or file not found)")
            
            log_info("Push operation completed successfully")
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
        """Transfer package to remote server via SCP.
        
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
            
            # Run SCP command
            cmd = ["scp", str(package_path), remote_file_path]
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
            
        except FileNotFoundError:
            log_error("SCP command not found. Please ensure OpenSSH is installed.")
            return False
        except Exception as e:
            log_error(f"Unexpected error during SCP transfer: {e}")
            return False

    def _ensure_remote_dir(self, username: str, server: str, remote_dir: str) -> None:
        """Create the remote directory with mkdir -p (best effort)."""
        try:
            # Add SSH host key before connection
            add_ssh_host_key(server)
            
            cmd = [
                "ssh", f"{username}@{server}",
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

# Retry function for apt operations with exponential backoff
apt_retry() {
  local cmd="$1"
  local max_attempts=5
  local attempt=1
  local wait_times=(5 10 20 40 60)
  
  while [ $attempt -le $max_attempts ]; do
    # Check for apt lock (only for apt-based systems)
    if [ "$USE_APT" = "true" ]; then
      if lsof /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || [ -f /var/lib/apt/lists/lock ]; then
        if [ $attempt -lt $max_attempts ]; then
          local wait_time=${wait_times[$((attempt-1))]}
          echo "[PREP] Apt lock detected, waiting ${wait_time}s before retry (attempt ${attempt}/${max_attempts})..." >&2
          sleep $wait_time
          attempt=$((attempt+1))
          continue
        fi
      fi
    fi
    
    # Try to run the command
    if sh -lc "$cmd"; then
      return 0
    else
      if [ $attempt -lt $max_attempts ]; then
        local wait_time=${wait_times[$((attempt-1))]}
        echo "[PREP] Command failed, waiting ${wait_time}s before retry (attempt ${attempt}/${max_attempts})..." >&2
        sleep $wait_time
        attempt=$((attempt+1))
      else
        echo "[PREP] Command failed after ${max_attempts} attempts" >&2
        return 1
      fi
    fi
  done
}

# Wait for droplet initialization (allow system updates to complete)
if [ "$USE_APT" = "true" ]; then
  echo "[PREP] Waiting 30s for droplet initialization to complete..."
  sleep 30
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
  echo "[PREP] Installing Python 3.11 from deadsnakes PPA..."
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
$PYTHON_CMD -m venv "$VENV_DIR"
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
            result = subprocess.run(
                ssh_cmd,
                input=remote_script,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                log_error("Remote preparation failed")
                if result.stdout:
                    log_info("Server preparation output:")
                    for line in result.stdout.splitlines():
                        log_info(f"  {line}")
                if result.stderr:
                    log_error("Server preparation errors:")
                    for line in result.stderr.splitlines():
                        log_error(f"  {line}")
                return False
            # Echo stdout for visibility in verbose mode
            if result.stdout:
                log_info("Server preparation output:")
                for line in result.stdout.splitlines():
                    log_info(f"  {line}")
            log_info("Server preparation script completed successfully")
            return True
        except Exception as e:
            log_error(f"Error preparing server: {e}")
            return False

    def _run_remote_import(self, username: str, server: str, remote_file: str, branch_name: str,
                           domain: Optional[str], ip: Optional[str]) -> None:
        """Run remote import and start services via SSH using a robust here-doc script."""
        try:
            log_info("Composing remote import script...")
            script = self._compose_remote_script(
                remote_file=remote_file,
                branch_name=branch_name,
                domain=domain,
                ip=ip,
            )
            exec_cmd = "cat > /tmp/dtrun.sh && chmod +x /tmp/dtrun.sh && /tmp/dtrun.sh && rm -f /tmp/dtrun.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            log_info("Executing remote import and startup script...")
            log_info("This will: import package, start proxy, and bring up the worktree environment")
            result = subprocess.run(cmd, input=script, text=True, capture_output=True, check=False)
            
            if result.returncode != 0:
                log_warning("Remote import script returned non-zero exit code")
                if result.stdout:
                    log_info("Remote import output:")
                    for line in result.stdout.splitlines():
                        log_info(f"  {line}")
                if result.stderr:
                    log_warning("Remote import errors:")
                    for line in result.stderr.splitlines():
                        log_warning(f"  {line}")
            else:
                log_info("Remote import script completed")
                if result.stdout:
                    for line in result.stdout.splitlines():
                        log_info(f"  {line}")
        except Exception as e:
            log_warning(f"Remote import failed: {e}")

    def _compose_remote_script(self, remote_file: str, branch_name: str, domain: Optional[str], ip: Optional[str]) -> str:
        """Compose a robust remote bash script for importing and starting services.

        The script sets strict mode, ensures git identity, resolves the dockertree binary,
        detects existing project vs standalone, runs import with proper flags and quoting,
        then starts proxy and brings up the branch.
        """
        import_flags_parts = []
        if domain:
            import_flags_parts.append(f"--domain '{domain}'")
        if ip:
            import_flags_parts.append(f"--ip '{ip}'")
        import_flags = " ".join(import_flags_parts)

        script = f"""
set -euo pipefail

# Ensure git identity exists to avoid commit failures on fresh servers
if ! git config --global user.email >/dev/null 2>&1; then git config --global user.email 'dockertree@local'; fi
if ! git config --global user.name >/dev/null 2>&1; then git config --global user.name 'Dockertree'; fi

# Determine dockertree binary (prefer venv install)
if [ -x /opt/dockertree-venv/bin/dockertree ]; then
  DTBIN=/opt/dockertree-venv/bin/dockertree
elif command -v dockertree >/dev/null 2>&1; then
  DTBIN="$(command -v dockertree)"
else
  DTBIN=dockertree
fi

PKG_FILE='{remote_file}'
BRANCH_NAME='{branch_name}'
IMPORT_FLAGS="{import_flags}"

# Find an existing dockertree project by locating .dockertree/config.yml
HIT="$(find /root -maxdepth 3 -type f -path '*/.dockertree/config.yml' -print -quit || true)"
if [ -n "$HIT" ]; then
  ROOT="$(dirname "$(dirname "$HIT")")"
  cd "$ROOT"
  "$DTBIN" packages import "$PKG_FILE" $IMPORT_FLAGS --non-interactive
else
  ROOT="/root"
  cd "$ROOT"
  "$DTBIN" packages import "$PKG_FILE" $IMPORT_FLAGS --standalone --non-interactive
fi

# Determine ROOT again after import in case project was created
HIT2="$(find /root -maxdepth 3 -type f -path '*/.dockertree/config.yml' -print -quit || true)"
if [ -n "$HIT2" ]; then
  ROOT2="$(dirname "$(dirname "$HIT2")")"
else
  ROOT2="/root"
fi
cd "$ROOT2"

# Start proxy (ignore non-interactive flag if unsupported)
"$DTBIN" start-proxy --non-interactive >/dev/null 2>&1 || "$DTBIN" start-proxy || true

# Bring up the environment for the branch
"$DTBIN" "$BRANCH_NAME" up -d
"""
        return script
    
    def _handle_dns_management(self, domain: str, server: str, 
                               dns_token: Optional[str] = None) -> bool:
        """Handle DNS management for domain deployment using Digital Ocean DNS.
        
        Args:
            domain: Full domain name (e.g., 'app.example.com')
            server: Server hostname or IP
            dns_token: Digital Ocean API token
            
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
                    if confirm_action(f"Update DNS record to point to {server_ip}?"):
                        # For now, we'll just warn - updating existing records requires delete+create
                        log_warning("DNS record update not yet implemented. Please update manually.")
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
                                 wait_for_droplet: bool = False,
                                 api_token: Optional[str] = None):
        """Create a droplet for push deployment.
        
        Args:
            droplet_name: Name for the droplet
            droplet_region: Droplet region
            droplet_size: Droplet size
            droplet_image: Droplet image
            droplet_ssh_keys: List of SSH key IDs or fingerprints
            wait_for_droplet: Wait for droplet to be ready
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
            
            # Wait for droplet to be ready if requested
            if wait_for_droplet:
                log_info("Waiting for droplet to be ready (this may take 1-2 minutes)...")
                log_info("Checking droplet status and SSH availability...")
                if not provider.wait_for_droplet_ready(droplet.id, check_ssh=True):
                    log_warning("Droplet created but not ready within timeout")
                    # Still return droplet info since it was created
                else:
                    log_info("Droplet is ready and SSH is accessible")
            else:
                log_info("Skipping droplet readiness wait (--wait-for-droplet not specified)")
            
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
                log_warning("Droplet IP address not available yet. It may take a few minutes to be assigned.")
            
            log_info("Droplet creation process completed")
            return droplet
            
        except Exception as e:
            log_error(f"Error creating droplet: {e}")
            return None

