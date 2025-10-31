"""
Push command for deploying dockertree packages to remote servers.

This module provides functionality to export dockertree packages and transfer
them to remote servers via SCP for deployment.
"""

import subprocess
import re
from pathlib import Path
from typing import Optional, Tuple

from ..core.package_manager import PackageManager
from ..utils.logging import log_info, log_success, log_warning, log_error, print_plain
from ..utils.path_utils import detect_execution_context, get_worktree_branch_name


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
                    ip: Optional[str] = None, prepare_server: bool = False) -> bool:
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
            # Auto-detect branch name if not provided
            if not branch_name:
                branch_name = self._detect_current_branch()
                if not branch_name:
                    log_error("Could not detect branch name. Please specify branch_name.")
                    return False
                log_info(f"Auto-detected branch: {branch_name}")
            
            # Validate SCP target format
            if not self._validate_scp_target(scp_target):
                log_error(f"Invalid SCP target format: {scp_target}")
                log_info("Expected format: username@server:path")
                return False
            
            # Parse SCP target
            username, server, remote_path = self._parse_scp_target(scp_target)
            
            # Export package with --include-code (required for production deployments)
            if output_dir is None:
                output_dir = self.project_root / "packages"
            
            log_info(f"Exporting package for branch: {branch_name}")
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
            if not package_path.exists():
                log_error(f"Package file not found: {package_path}")
                return False
            
            # Ensure remote directory exists
            remote_dir = self._infer_remote_directory(remote_path)
            if remote_dir and remote_dir not in ['.', '']:
                self._ensure_remote_dir(username, server, remote_dir)

            # Prepare server dependencies if requested (before upload/import)
            if prepare_server:
                ok = self._prepare_server(username, server)
                if not ok:
                    log_error("Server preparation failed. Aborting push.")
                    return False

            # Transfer package via SCP
            log_info(f"Transferring package to {server}...")
            if not self._scp_transfer(package_path, scp_target):
                log_error("Failed to transfer package to remote server")
                return False
            
            log_success(f"Package pushed successfully to {scp_target}")
            
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
                self._check_server_requirements(username, server)

            # Optional: auto import on server
            if auto_import:
                self._run_remote_import(username, server, f"{remote_path}/{package_path.name}", branch_name, domain, ip)

            # Clean up package unless keep_package is True
            if not keep_package and package_path.exists():
                try:
                    package_path.unlink()
                    log_info(f"Cleaned up local package: {package_path.name}")
                except Exception as e:
                    log_warning(f"Failed to clean up package: {e}")
            
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
            remote_file_path = f"{scp_target}/{package_path.name}" if not scp_target.endswith('/') else f"{scp_target}{package_path.name}"
            
            # Run SCP command
            cmd = ["scp", str(package_path), remote_file_path]
            log_info(f"Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown SCP error"
                log_error(f"SCP transfer failed: {error_msg}")
                
                # Provide helpful error messages for common issues
                if "Connection refused" in error_msg or "Could not resolve" in error_msg:
                    log_info("Tip: Check that the server is accessible and SSH is running")
                elif "Permission denied" in error_msg or "Authentication failed" in error_msg:
                    log_info("Tip: Ensure SSH keys are set up or password authentication is enabled")
                elif "No space left" in error_msg or "disk full" in error_msg.lower():
                    log_info("Tip: Free up disk space on the remote server")
                
                return False
            
            log_success(f"Package transferred successfully")
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

    def _prepare_server(self, username: str, server: str) -> bool:
        """Install required dependencies on the remote server non-interactively.

        Installs: curl, git, python3, python3-pip, Docker (Engine + Compose v2),
        and dockertree from GitHub via pip.
        """
        try:
            remote_script = r'''
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
echo "[PREP] Detecting distribution..."
if [ -f /etc/os-release ]; then . /etc/os-release; else ID=unknown; fi

# Choose package manager commands
if command -v apt-get >/dev/null 2>&1; then
  PKG_UPDATE='apt-get -y -qq update'
  PKG_INSTALL='apt-get -y -qq install'
elif command -v dnf >/dev/null 2>&1; then
  PKG_UPDATE='dnf -y makecache'
  PKG_INSTALL='dnf install -y -q'
elif command -v yum >/dev/null 2>&1; then
  PKG_UPDATE='yum -y makecache'
  PKG_INSTALL='yum install -y -q'
else
  echo "[PREP] Unsupported distro: cannot find apt/dnf/yum" >&2
  exit 1
fi

echo "[PREP] Installing base tools (curl git python3 python3-venv python3-pip)..."
sh -lc "$PKG_UPDATE"
sh -lc "$PKG_INSTALL curl git python3 python3-venv python3-pip || true"

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
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip wheel
"$VENV_DIR/bin/pip" install --upgrade git+https://github.com/catalpainternational/dockertree.git || {
  echo "[PREP] venv install failed, trying pipx/system pip as fallback" >&2
  if command -v pipx >/dev/null 2>&1; then
    pipx install --force git+https://github.com/catalpainternational/dockertree.git || true
  else
    python3 -m pip install --break-system-packages --upgrade git+https://github.com/catalpainternational/dockertree.git || true
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
            log_info("Preparing server (installing dependencies)...")
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
                    log_info(result.stdout)
                if result.stderr:
                    log_error(result.stderr)
                return False
            # Optional echo of stdout for visibility
            if result.stdout:
                for line in result.stdout.splitlines():
                    log_info(line)
            return True
        except Exception as e:
            log_error(f"Error preparing server: {e}")
            return False

    def _run_remote_import(self, username: str, server: str, remote_file: str, branch_name: str,
                           domain: Optional[str], ip: Optional[str]) -> None:
        """Run remote import and start services via SSH using a robust here-doc script."""
        try:
            script = self._compose_remote_script(
                remote_file=remote_file,
                branch_name=branch_name,
                domain=domain,
                ip=ip,
            )
            exec_cmd = "cat > /tmp/dtrun.sh && chmod +x /tmp/dtrun.sh && /tmp/dtrun.sh && rm -f /tmp/dtrun.sh"
            cmd = ["ssh", f"{username}@{server}", "bash", "-lc", exec_cmd]
            log_info("Running remote import and start commands...")
            subprocess.run(cmd, input=script, text=True, check=False)
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

