"""
Remote script management for dockertree push operations.

This module provides remote bash scripts with versioning and caching
to avoid redundant transfers.
"""

from typing import Optional

# Script versions for cache invalidation
SERVER_PREP_SCRIPT_VERSION = "1.0"
REMOTE_IMPORT_SCRIPT_VERSION = "1.1"  # Updated for standalone mode fixes


SERVER_PREP_SCRIPT = r'''
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


def get_server_prep_script() -> str:
    """Get server preparation script."""
    return SERVER_PREP_SCRIPT


def compose_remote_import_script(remote_file: str, branch_name: str, 
                                 domain: Optional[str] = None, 
                                 ip: Optional[str] = None) -> str:
    """Compose remote import script with parameters.
    
    Args:
        remote_file: Path to package file on remote server
        branch_name: Branch name
        domain: Optional domain override
        ip: Optional IP override
        
    Returns:
        Script content as string
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
  log "Running import in normal mode (existing project)..."
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

# Restore volumes if needed (before starting containers)
if [ "$NEED_VOLUME_RESTORE" = true ]; then
  log "Volumes need restoration - ensuring containers are stopped first..."
  
  # Stop any running containers for this branch
  COMPOSE_FILE="$ROOT2/worktrees/${{BRANCH_NAME}}/.dockertree/docker-compose.worktree.yml"
  if [ -f "$COMPOSE_FILE" ]; then
    log "Stopping any running containers before volume restoration..."
    cd "$ROOT2/worktrees/${{BRANCH_NAME}}/.dockertree"
    # Use the same project name format as dockertree uses (project-name-branch-name)
    if [ -n "$PROJECT_NAME" ]; then
      COMPOSE_PROJECT_NAME="$PROJECT_NAME-${{BRANCH_NAME}}"
    else
      COMPOSE_PROJECT_NAME="$(basename "$ROOT2" | tr '_' '-' | tr '[:upper:]' '[:lower:]')-${{BRANCH_NAME}}"
    fi
    docker compose -f docker-compose.worktree.yml -p "$COMPOSE_PROJECT_NAME" down >/dev/null 2>&1 || true
    cd "$ROOT2"
  fi
  
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

# Start proxy (ignore non-interactive flag if unsupported)
log "Starting global Caddy proxy..."
if "$DTBIN" start-proxy --non-interactive >/dev/null 2>&1; then
  log_success "Proxy started successfully"
elif "$DTBIN" start-proxy >/dev/null 2>&1; then
  log_success "Proxy started successfully (without --non-interactive)"
else
  log_error "Failed to start proxy, but continuing..."
fi

# Bring up the environment for the branch
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
    
    # Set project name for docker compose
    if [ -n "$PROJECT_NAME" ]; then
      COMPOSE_PROJECT_NAME="$PROJECT_NAME-${{BRANCH_NAME}}"
    else
      COMPOSE_PROJECT_NAME="$(basename "$ROOT2" | tr '_' '-' | tr '[:upper:]' '[:lower:]')-${{BRANCH_NAME}}"
    fi
    
    # Get relative path to compose file from worktree directory
    COMPOSE_FILE_REL="${COMPOSE_FILE#$WORKTREE_PATH/}"
    
    # Load PROJECT_ROOT from env.dockertree (reuses existing env file loading pattern)
    if [ -f ".dockertree/env.dockertree" ]; then
      export $(grep "^PROJECT_ROOT=" .dockertree/env.dockertree | xargs)
      log "Loaded PROJECT_ROOT from env.dockertree: $PROJECT_ROOT"
    fi
    
    # Check if timeout command is available
    if command -v timeout >/dev/null 2>&1; then
      log "Running with $TIMEOUT second timeout..."
      timeout $TIMEOUT docker compose -f "$COMPOSE_FILE_REL" --env-file .dockertree/env.dockertree -p "$COMPOSE_PROJECT_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR" &
      UP_PID=$!
      
      # Show progress every 30 seconds
      ELAPSED=0
      while kill -0 $UP_PID 2>/dev/null && [ $ELAPSED -lt $TIMEOUT ]; do
        sleep 30
        ELAPSED=$((ELAPSED + 30))
        log "Still starting containers... (${{ELAPSED}}s elapsed)"
        # Show container status
        RUNNING=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
        TOTAL=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
        if [ "$TOTAL" -gt 0 ]; then
          log "  Containers: $RUNNING/$TOTAL running"
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
    else
      log "Timeout command not available, running without timeout..."
      if docker compose -f "$COMPOSE_FILE_REL" --env-file .dockertree/env.dockertree -p "$COMPOSE_PROJECT_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR"; then
        UP_EXIT_CODE=0
      else
        UP_EXIT_CODE=$?
        log_error "Failed to start worktree environment (exit code: $UP_EXIT_CODE)"
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
    while kill -0 $UP_PID 2>/dev/null && [ $ELAPSED -lt $TIMEOUT ]; do
      sleep 30
      ELAPSED=$((ELAPSED + 30))
      log "Still starting containers... (${{ELAPSED}}s elapsed)"
      # Show container status
      RUNNING=$(docker ps --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      TOTAL=$(docker ps -a --filter "name=${{BRANCH_NAME}}" --format "{{{{.Names}}}}" 2>/dev/null | wc -l)
      if [ "$TOTAL" -gt 0 ]; then
        log "  Containers: $RUNNING/$TOTAL running"
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
  else
    log "Timeout command not available, running without timeout..."
    if "$DTBIN" "$BRANCH_NAME" up -d > "$UP_OUTPUT" 2> "$UP_ERROR"; then
      UP_EXIT_CODE=0
    else
      UP_EXIT_CODE=$?
      log_error "Failed to start worktree environment (exit code: $UP_EXIT_CODE)"
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

log_success "=== Remote import process completed ==="
"""
    return script


def check_script_cached(username: str, server: str, script_name: str, 
                       version: str, ssh_manager) -> bool:
    """Check if script is cached on remote server with correct version.
    
    Args:
        username: SSH username
        server: Server hostname or IP
        script_name: Name of script file
        version: Script version
        ssh_manager: SSHConnectionManager instance
        
    Returns:
        True if cached with correct version, False otherwise
    """
    try:
        # Check for version marker file
        version_file = f"/tmp/{script_name}.version"
        result = ssh_manager.execute_remote(
            username, server,
            f"test -f {version_file} && cat {version_file} || echo ''",
            timeout=5,
            check=False
        )
        cached_version = result.stdout.strip()
        return cached_version == version
    except Exception:
        return False


def mark_script_cached(username: str, server: str, script_name: str,
                      version: str, ssh_manager):
    """Mark script as cached on remote server.
    
    Args:
        username: SSH username
        server: Server hostname or IP
        script_name: Name of script file
        version: Script version
        ssh_manager: SSHConnectionManager instance
    """
    try:
        version_file = f"/tmp/{script_name}.version"
        ssh_manager.execute_remote(
            username, server,
            f"echo '{version}' > {version_file}",
            timeout=5,
            check=False
        )
    except Exception:
        pass

