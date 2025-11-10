# Dockertree - Git Worktrees with Isolated Docker Environments

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-green.svg)](tests/)
[![Status](https://img.shields.io/badge/status-production%20ready-brightgreen.svg)]()

A comprehensive Python CLI tool that creates isolated development environments using Git worktrees, Docker Compose, and Caddy reverse proxy. Each feature branch gets its own complete environment with isolated databases, Redis, and media storage.

## 🚀 Quick Start

### Installation

```bash
# Install via pip
pip install dockertree

# Install with MCP server support
pip install dockertree[mcp]

# Or install from source
git clone https://github.com/catalpainternational/dockertree.git
cd dockertree
pip install -e .

# Or install from source with MCP support
pip install -e .[mcp]
```

### Basic Usage

```bash
# Initialize dockertree in your project
dockertree setup

# Start global Caddy proxy
dockertree start-proxy

# Create and start a worktree
dockertree create feature-auth
dockertree feature-auth up -d

# Access your isolated environment (note: domain includes project name)
# If your project is named "myapp", the URL will be:
open http://myapp-feature-auth.localhost

# Export environment as shareable package (includes code by default)
dockertree packages export feature-auth

# Import environment from package
dockertree packages import myapp-feature-auth-2024-01-15.dockertree-package.tar.gz

# Stop and clean up
dockertree feature-auth down
dockertree remove feature-auth
```

## 🏗️ Architecture Overview

Dockertree CLI provides complete environment isolation through:

- **Git Worktrees**: Isolated working directories for each branch
- **Docker Compose**: Isolated containers with branch-specific volumes
- **Caddy Proxy**: Dynamic routing based on branch names
- **Volume Isolation**: Branch-specific databases, Redis, and media storage
- **Package Management**: Export/import complete environments as shareable packages

### System Architecture

```text
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Global Caddy  │    │  Worktree A      │    │  Worktree B     │
│   (Port 80)     │    │  feature-auth    │    │  feature-pay    │
│                 │    │                  │    │                 │
│  Routes to:     │───▶│  • PostgreSQL    │    │  • PostgreSQL   │
│  • *.localhost  │    │  • Redis         │    │  • Redis        │
│                 │    │  • Web App       │    │  • Web App      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 📋 Command Reference

**Important**: Dockertree uses a **worktree-name-first pattern**. For `up` and `down` commands, the syntax is `dockertree <worktree_name> up` and `dockertree <worktree_name> down`, not `dockertree up <worktree_name>`.

### Setup Commands

| Command | Description | Example |
|---------|-------------|---------|
| `setup` | Initialize dockertree for this project | `dockertree setup [--monkey-patch]` |

### Global Caddy Management

| Command | Description | Example |
|---------|-------------|---------|
| `start-proxy` | Start global Caddy proxy container | `dockertree start-proxy` |
| `stop-proxy` | Stop global Caddy proxy container | `dockertree stop-proxy` |
| `start` | Alias for start-proxy | `dockertree start` |
| `stop` | Alias for stop-proxy | `dockertree stop` |

### Command Aliases

| Alias | Full Command | Description |
|-------|--------------|-------------|
| `-D` | `delete` | Delete worktree and branch completely |
| `-r` | `remove` | Remove worktree but keep git branch |

### Worktree Lifecycle

| Command | Description | Example |
|---------|-------------|---------|
| `create <branch>` | Create worktree | `dockertree create feature-auth` |
| `<branch> up -d` | Start worktree environment | `dockertree feature-auth up -d` |
| `<branch> down` | Stop worktree environment | `dockertree feature-auth down` |
| `remove <branch>` | Remove worktree (keep branch) | `dockertree remove feature-auth` |
| `delete <branch>` | Delete worktree and branch | `dockertree delete feature-auth` |

**Important**: Branch names must match exactly. The `delete` and `remove` commands check worktrees, branches, and docker volumes for exact matches only. If no exact match is found, an error message will show what was checked.

### Docker Compose Passthrough

Dockertree supports direct passthrough to Docker Compose commands using the pattern: `dockertree <worktree_name> <compose-command>`

| Command Pattern | Description | Example |
|-----------------|-------------|---------|
| `<branch> exec <service> <cmd>` | Execute command in container | `dockertree feature-auth exec web python manage.py migrate` |
| `<branch> logs <service>` | View container logs | `dockertree feature-auth logs web` |
| `<branch> ps` | List containers | `dockertree feature-auth ps` |
| `<branch> run <service> <cmd>` | Run one-off command | `dockertree feature-auth run --rm web python manage.py test` |
| `<branch> build` | Build services | `dockertree feature-auth build` |
| `<branch> restart <service>` | Restart service | `dockertree feature-auth restart web` |
| `<branch> <compose-cmd>` | Any docker compose command | `dockertree feature-auth pull`, `dockertree feature-auth config` |

**Supported Docker Compose Commands:**
- `exec`, `logs`, `ps`, `run`, `build`, `pull`, `push`, `restart`
- `start`, `stop`, `up`, `down`, `config`, `images`, `port`
- `top`, `events`, `kill`, `pause`, `unpause`, `scale`

### Wildcard Operations

| Command | Description | Example |
|---------|-------------|---------|
| `remove <pattern>` | Remove worktrees matching pattern | `dockertree remove test-*` |
| `delete <pattern>` | Delete worktrees and branches matching pattern | `dockertree delete feature-*` |

**Wildcard Patterns:**
- `*` - Matches any characters (e.g., `test-*` matches `test-feature`, `test-bugfix`)
- `?` - Matches single character (e.g., `test-?` matches `test-1`, `test-a`)
- `[abc]` - Matches any character in brackets (e.g., `test-[abc]` matches `test-a`, `test-b`, `test-c`)
- Case-insensitive matching (e.g., `test-*` matches `Test-Feature`, `TEST-FEATURE`)

### Bulk Operations
| Command | Description | Example |
|---------|-------------|---------|
| `remove-all` | Remove all worktrees (keep branches) | `dockertree remove-all` |
| `delete-all` | Delete all worktrees and branches | `dockertree delete-all --force` |

### Utility Commands
| Command | Description | Example |
|---------|-------------|---------|
| `list` | List active worktrees | `dockertree list` |
| `prune` | Remove prunable worktrees | `dockertree prune` |
| `help` | Show help information | `dockertree help` |
| `clean-legacy` | Clean legacy dockertree elements | `dockertree clean-legacy` |

### Volume Management
| Command | Description | Example |
|---------|-------------|---------|
| `volumes list` | List all worktree volumes | `dockertree volumes list` |
| `volumes size` | Show volume sizes | `dockertree volumes size` |
| `volumes backup <branch>` | Backup worktree volumes | `dockertree volumes backup feature-auth` |
| `volumes restore <branch> <file>` | Restore from backup | `dockertree volumes restore feature-auth backup.tar` |
| `volumes clean <branch>` | Clean up volumes | `dockertree volumes clean feature-auth` |

### Droplet Management
| Command | Description | Example |
|---------|-------------|---------|
| `droplets create <name>` | Create a new Digital Ocean droplet | `dockertree droplets create myapp-prod` |
| `droplets list` | List all droplets (formatted table) | `dockertree droplets list` |
| `droplets list --as-json` | List droplets as JSON | `dockertree droplets list --as-json` |
| `droplets list --as-csv` | List droplets as CSV | `dockertree droplets list --as-csv` |
| `droplets info <id>` | Get droplet information | `dockertree droplets info 12345678` |
| `droplets destroy <id>` | Destroy a droplet | `dockertree droplets destroy 12345678` |

**Droplet Creation Options:**
- `--region <region>` - Droplet region (defaults from env or nyc1)
- `--size <size>` - Droplet size (defaults from env or s-1vcpu-1gb)
- `--image <image>` - Droplet image (defaults from env or ubuntu-22-04-x64)
- `--ssh-keys <key>` - SSH key IDs or fingerprints (can be specified multiple times)
- `--tags <tag>` - Tags for the droplet (can be specified multiple times)
- `--wait` - Wait for droplet to be ready
- `--api-token <token>` - Digital Ocean API token (or use DIGITALOCEAN_API_TOKEN/DNS_API_TOKEN env var)

**Droplet List Options:**
- `--as-json` or `--json` - Output as JSON format
- `--as-csv` - Output as CSV format
- `--api-token <token>` - Digital Ocean API token (or use DIGITALOCEAN_API_TOKEN/DNS_API_TOKEN env var)

**Droplet Destroy Options:**
- `--force` - Skip confirmation (destroys without typing droplet name)
- `--only-droplet` - Only destroy droplet, skip DNS deletion
- `--only-domain` - Only destroy DNS records, skip droplet deletion
- `--domain <domain>` - Domain name for DNS deletion (optional, auto-detects if not provided)
- `--api-token <token>` - Digital Ocean API token (or use DIGITALOCEAN_API_TOKEN/DNS_API_TOKEN env var)
- `--dns-token <token>` - DNS API token (if different from droplet token)
- `--json` - Output as JSON format

**Droplet Destroy Behavior:**
- **Default**: Destroys droplet only (backward compatible)
- **Confirmation**: Requires typing the exact droplet name to confirm (unless `--force`)
- **DNS Auto-detection**: When destroying droplet, automatically finds and deletes DNS records pointing to droplet IP
- **DNS-only mode**: Use `--only-domain` to delete DNS records without destroying the droplet
- **Domain confirmation**: When deleting DNS records, requires typing the full domain name (e.g., "app.example.com") unless `--force`
- **Domain override**: Use `--domain <domain>` to limit DNS search to specific domain

### Package Management
| Command | Description | Example |
|---------|-------------|---------|
| `packages export <branch>` | Export worktree as shareable package (includes code by default) | `dockertree packages export feature-auth` |
| `packages import <file>` | Import environment from package (auto-detects standalone mode) | `dockertree packages import my-package.tar.gz` |
| `packages import <file> --domain <sub.domain.tld>` | Import with domain override (HTTPS via Caddy) | `dockertree packages import pkg.tar.gz --domain myapp.example.com` |
| `packages import <file> --ip <x.x.x.x>` | Import with IP override (HTTP-only) | `dockertree packages import pkg.tar.gz --ip 203.0.113.10` |
| `packages import <file> --standalone` | Force standalone import (create new project) | `dockertree packages import my-package.tar.gz --standalone --target-dir ./myproject` |
| `packages list` | List available packages | `dockertree packages list` |
| `packages validate <file>` | Validate package integrity | `dockertree packages validate my-package.tar.gz` |

#### Standalone Package Import

Dockertree intelligently detects whether you're in an existing project and automatically switches between normal and standalone import modes.

**Automatic Detection (Default)**:
```bash
# In an empty directory - automatically creates new project
cd /path/to/new-location
dockertree packages import my-package.tar.gz
# Auto-detects: No git repo → standalone mode
# Creates: ./myproject-standalone/

# In existing dockertree project - automatically imports as worktree
cd /path/to/existing-project
dockertree packages import my-package.tar.gz
# Auto-detects: Existing .dockertree → normal mode
# Creates: new worktree in project
```

**Explicit Standalone Mode**:
```bash
# Force standalone import with custom directory
dockertree packages import my-package.tar.gz --standalone --target-dir ./my-new-project

# Force standalone even if in existing project
dockertree packages import my-package.tar.gz --standalone
```

**Requirements**:
- Standalone imports require packages exported with code (`--include-code`, which is the default)
- Normal imports work with or without code

**What Gets Created in Standalone Mode**:
1. New git repository initialized
2. Complete codebase from package
3. Dockertree configuration (`.dockertree/`)
4. Environment files
5. Docker volumes (if `--restore-data`)
6. Ready-to-use isolated environment

### Shell Completion Management
| Command | Description | Example |
|---------|-------------|---------|
| `completion install [shell]` | Install shell completion | `dockertree completion install` |
| `completion uninstall` | Remove shell completion | `dockertree completion uninstall` |
| `completion status` | Show completion status | `dockertree completion status` |

## 🔧 Configuration
### Django Compatibility Checks

During `dockertree setup`, if a Django project is detected (`manage.py` present and a `settings.py` found), Dockertree validates your settings are environment-driven for reverse proxy use:

- ALLOWED_HOSTS (comma-separated)
- CSRF_TRUSTED_ORIGINS (space-separated)
- USE_X_FORWARDED_HOST (boolean)
- SECURE_PROXY_SSL_HEADER (tuple as `HTTP_X_FORWARDED_PROTO,https`)

If any are missing, Dockertree prints a nicely formatted guidance block and, when `--monkey-patch` is supplied, appends a safe snippet to `settings.py` to read these values from environment variables.

Suggested snippet (auto-added with `--monkey-patch`):
```python
import os
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "").split()
USE_X_FORWARDED_HOST = os.getenv("USE_X_FORWARDED_HOST", "False") == "True"
_hdr = os.getenv("SECURE_PROXY_SSL_HEADER")
if _hdr:
    SECURE_PROXY_SSL_HEADER = tuple(_hdr.split(",", 1))
```

### SQLite persistence (recommended pattern)

When using SQLite in Docker, store the database file on a named Docker volume so Dockertree export/import captures it (just like Postgres/Redis volumes):

- In Django settings, point SQLite to a path under a data mount, e.g. `/data/db.sqlite3` (or use an env var like `SQLITE_PATH=/data/db.sqlite3`).
- In your compose, mount a named volume for the web service:

```yaml
services:
  web:
    volumes:
      - sqlite_data:/data

volumes:
  sqlite_data: {}
```

Dockertree will back up and restore `sqlite_data` with other volumes, preserving DB state across export/import. If you keep the DB at `/app/db.sqlite3` (bind-mounted source tree), it is not part of any Docker volume snapshot and will not be included.

### Project Setup

When you run `dockertree setup`, it creates a `.dockertree/` directory with:

- `config.yml` - Project configuration
- `docker-compose.worktree.yml` - Transformed compose file (generated from existing docker-compose.yml)
- `Caddyfile.dockertree` - Caddy configuration
- `README.md` - User guide optimized for coding agents
- `worktrees/` - Worktree directories

### Droplet Configuration

Droplet defaults can be configured in `.env` or `.dockertree/env.dockertree`:

```bash
# .env or .dockertree/env.dockertree
DROPLET_DEFAULT_REGION=nyc1
DROPLET_DEFAULT_SIZE=s-1vcpu-1gb
DROPLET_DEFAULT_IMAGE=ubuntu-22-04-x64
# SSH key names (comma-separated, e.g., anders,peter)
# Only key names are supported, not numeric IDs or fingerprints
DROPLET_DEFAULT_SSH_KEYS=anders,peter
DIGITALOCEAN_API_TOKEN=your_token_here
```

### Configuration File

The `.dockertree/config.yml` file contains:

```yaml
project_name: myproject
caddy_network: dockertree_caddy_proxy
worktree_dir: worktrees
services:
  web:
    container_name_template: ${COMPOSE_PROJECT_NAME}-web
  db:
    container_name_template: ${COMPOSE_PROJECT_NAME}-db
  redis:
    container_name_template: ${COMPOSE_PROJECT_NAME}-redis
volumes:
  - postgres_data
  - redis_data
  - media_files
environment:
  DEBUG: "True"
  ALLOWED_HOSTS: "localhost,127.0.0.1,*.localhost,web"
```

### Volume Naming Convention
Worktree-specific volumes follow the pattern: `{branch_name}_{volume_type}`

- `feature-auth_postgres_data` - Database data
- `feature-auth_redis_data` - Cache data  
- `feature-auth_media_files` - User uploads

### Network Configuration
- **Global Network**: `dockertree_caddy_proxy` (external)
- **Worktree Networks**: `{branch_name}_internal`, `{branch_name}_web`

## 🛠️ Development Workflows

### Feature Development
```bash
# 1. Initialize dockertree in your project
dockertree setup

# 2. Start global infrastructure
dockertree start-proxy

# 3. Create feature branch environment
dockertree create feature-new-auth
dockertree feature-new-auth up -d

# 4. Develop and test
open http://feature-new-auth.localhost
# Make changes, test database migrations, etc.

# 5. Clean up when done
dockertree feature-new-auth down
dockertree remove feature-new-auth
```

### Multiple Feature Branches
```bash
# Work on multiple features simultaneously
dockertree create feature-auth
dockertree create feature-payments
dockertree create feature-notifications

# Start all environments
dockertree feature-auth up -d
dockertree feature-payments up -d
dockertree feature-notifications up -d

# Access each independently
open http://feature-auth.localhost
open http://feature-payments.localhost
open http://feature-notifications.localhost
```

### Database Testing
```bash
# Test database migrations in isolation
dockertree create test-migration
dockertree test-migration up -d

# Run migrations, test data changes
# Each worktree has its own database

# Clean up test environment
dockertree delete test-migration
```

### Docker Compose Integration
```bash
# Execute Django management commands
dockertree feature-auth exec web python manage.py migrate
dockertree feature-auth exec web python manage.py collectstatic

# View application logs
dockertree feature-auth logs web
dockertree feature-auth logs -f web  # Follow logs

# Run one-off commands
dockertree feature-auth run --rm web python manage.py test
dockertree feature-auth run --rm web bash

# Check container status
dockertree feature-auth ps

# Restart services
dockertree feature-auth restart web
```

## 🔍 Troubleshooting

### Common Issues

**Docker not running**
```bash
Error: Docker is not running. Please start Docker and try again.
```
**Solution**: Start Docker Desktop or Docker daemon

**PostgreSQL Database Corruption**
```bash
Error: invalid primary checkpoint record
Error: could not locate a valid checkpoint record
```
**Solution**: This has been fixed! Dockertree now uses safe database snapshots with `pg_dump` when the source database is running, preventing corruption. The system automatically detects if your source database is running and uses the appropriate backup method.

**Worktree already exists**
```bash
Error: Worktree for branch 'feature-auth' already exists
```
**Solution**: Use `dockertree list` to see existing worktrees, or remove the existing one

**Port conflicts**
```bash
Error: Port 80 is already in use
```
**Solution**: Stop other services using port 80, or check if global Caddy is already running

**Volume creation fails**
```bash
Error: Failed to create volume
```
**Solution**: Check Docker disk space, ensure Docker has sufficient permissions

**Branch not found during deletion**
```bash
Error: No exact match found for 'feature-auth'. Checked: worktrees, branches, and docker volumes.
```
**Solution**: Use `dockertree list` to see exact branch names. Branch names are case-sensitive and must match exactly.

### Debug Commands

```bash
# Check Docker status
docker ps

# Check worktree status
dockertree list

# Check volume status
dockertree volumes list

# Check network status
docker network ls | grep dockertree_caddy_proxy
```

### Logs and Debugging

```bash
# View container logs
docker logs dockertree_caddy_proxy
docker logs {branch-name}-web

# Check worktree directory
ls -la worktrees/{branch-name}/

# Verify environment files
cat worktrees/{branch-name}/.dockertree/env.dockertree
```

## ⌨️ Shell Completion

Dockertree CLI provides intelligent tab completion for Bash and Zsh shells, making it faster and easier to use.

### Features

- **Command Completion**: Tab complete all dockertree commands and subcommands
- **Worktree Names**: Auto-complete worktree branch names for commands that need them
- **Volume Operations**: Complete worktree names for volume backup/restore/clean operations
- **Flag Completion**: Auto-complete command flags like `--force`, `-d`, `--detach`

### Installation

#### Automatic Installation (Recommended)

Shell completion is automatically offered during project setup:

```bash
dockertree setup
# After successful setup, you'll be prompted:
# "Would you like to install bash completion? [Y/n]"
```

#### Manual Installation

```bash
# Install for current shell (auto-detected)
dockertree completion install

# Install for specific shell
dockertree completion install bash
dockertree completion install zsh

# Check installation status
dockertree completion status

# Uninstall completion
dockertree completion uninstall
```

### Usage Examples

```bash
# Tab complete commands
dockertree <TAB>
# Shows: create delete down help list prune remove remove-all setup start-proxy stop-proxy start stop up volumes

# Tab complete worktree names
dockertree feature-auth <TAB>
# Shows: up down exec logs ps run build restart

# Tab complete volume operations
dockertree volumes backup <TAB>
# Shows: feature-auth feature-payments feature-notifications

# Tab complete flags
dockertree delete <TAB>
# Shows: feature-auth --force
```

### Troubleshooting

**Completion not working after installation:**
```bash
# Restart your shell or source the configuration
source ~/.bashrc  # For Bash
source ~/.zshrc   # For Zsh
```

**Check completion status:**
```bash
dockertree completion status
```

**Reinstall completion:**
```bash
dockertree completion uninstall
dockertree completion install
```

## 🤖 MCP Server Integration

Dockertree includes a Model Context Protocol (MCP) server that enables AI assistants like Claude and Cursor to manage isolated development environments programmatically.

### Installation with MCP Support

```bash
# Install with MCP dependencies
pip install dockertree[mcp]

# Or install from source with MCP support
git clone https://github.com/catalpainternational/dockertree.git
cd dockertree
pip install -e .[mcp]
```

### Basic Usage

```bash
# Run the MCP server
dockertree-mcp

# Or run directly
python -m dockertree_mcp.server
```

### AI Assistant Integration

The MCP server enables AI assistants to:

- **Create and manage worktrees**: `create_worktree`, `start_worktree`, `stop_worktree`
- **Manage volumes**: `backup_volumes`, `restore_volumes`, `clean_volumes`
- **Control proxy**: `start_proxy`, `stop_proxy`, `get_proxy_status`
- **Get information**: `list_worktrees`, `get_worktree_info`, `list_volumes`

### Example with Claude Desktop

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "dockertree": {
      "command": "dockertree-mcp",
      "args": [],
      "env": {
        "DOCKERTREE_WORKING_DIR": "/path/to/your/project"
      }
    }
  }
}
```

### Working Directory Configuration

**Critical**: Always provide the `working_directory` parameter when using MCP tools. This tells dockertree which project to operate on.

```python
# ✅ CORRECT: Always specify working_directory
create_worktree({
    "branch_name": "feature-auth",
    "working_directory": "/Users/ders/kenali/blank"  # Target project directory
})

# ❌ INCORRECT: Missing working_directory
create_worktree({"branch_name": "feature-auth"})  # Will use MCP server's directory
```

### Documentation

For detailed MCP server documentation, see [mcp/README.md](mcp/README.md).

## 🚀 Advanced Usage

### Custom Configuration
Create custom environment files for specific worktrees:

```bash
# Create worktree with custom settings
dockertree create feature-auth

# Edit environment file
vim worktrees/feature-auth/.dockertree/env.dockertree

# Start with custom configuration
dockertree feature-auth up -d
```

### Volume Management
```bash
# Backup before major changes
dockertree volumes backup feature-auth

# Check volume sizes
dockertree volumes size

# Clean up old volumes
dockertree volumes clean feature-auth
```

### Package Management

**Auto-Detection** (recommended):
```bash
# Automatically chooses correct mode based on current directory
dockertree packages import myapp-feature-auth.tar.gz
```

**Standalone Import** (create new project):
```bash
# Create new project from package
mkdir ~/new-project && cd ~/new-project
dockertree packages import myapp-feature-auth.tar.gz --standalone

# Or specify target directory
dockertree packages import myapp-feature-auth.tar.gz --standalone --target-dir ./myproject
```

**Normal Import** (add to existing project):
```bash
# Import to existing project as new worktree
cd /path/to/existing-project
dockertree packages import myapp-feature-auth.tar.gz
```

**Import Options**:
```bash
# Import without data (configuration and code only)
dockertree packages import myapp-feature-auth.tar.gz --no-data

# Import to specific branch name
dockertree packages import myapp-feature-auth.tar.gz --target-branch new-branch-name

# Domain/IP overrides for deployment
dockertree packages import myapp-feature-auth.tar.gz --standalone --domain myapp.example.com  # HTTPS via Caddy
dockertree packages import myapp-feature-auth.tar.gz --standalone --ip 203.0.113.10           # HTTP-only (no TLS)
```

**Export Options**:
```bash
# Export complete environment as shareable package (includes code by default)
dockertree packages export feature-auth

# Export environment without code (smaller package)
dockertree packages export feature-auth --no-code

# Export to specific directory
dockertree packages export feature-auth --output-dir ./exports
```

**Package Management**:
```bash
# List available packages
dockertree packages list

# Validate package integrity
dockertree packages validate myapp-feature-auth.tar.gz
```

### Bulk Operations
```bash
# Remove all worktrees (keeps git branches)
dockertree remove-all

# Delete all worktrees and branches (destructive)
dockertree delete-all --force

# Clean up prunable worktrees
dockertree prune
```

### Wildcard Operations
```bash
# Remove all test branches (keeps git branches)
dockertree remove test-*

# Delete all feature branches and their worktrees
dockertree delete feature-*

# Remove branches matching pattern with confirmation
dockertree remove bugfix-*
# Output: Found 3 matching branch(es): bugfix-auth, bugfix-payment, bugfix-ui
# Remove 3 worktree(s) (keep branches)? [Y/n]: 

# Delete with force flag (skips confirmation)
dockertree delete temp-* --force
```

## 📚 Additional Documentation

- **[📖 Full Documentation Site](https://catalpainternational.github.io/dockertree)** - Complete documentation with search and navigation
- **[Architecture Guide](documentation/ARCHITECTURE.md)** - Detailed system architecture and component relationships
- **[Design Documents](design_documents/)** - Original design and implementation plans
- **[Test Documentation](tests/)** - Comprehensive test suite and coverage
- **[Configuration Reference](config/)** - All configuration files and options

## 🤝 Contributing

The dockertree CLI follows a modular architecture designed for easy extension:

- **Core Infrastructure**: `core/` - Docker, Git, and environment management
- **Command Layer**: `commands/` - Business logic for each command
- **Utilities**: `utils/` - Shared functionality and validation
- **Configuration**: `config/` - Settings and Docker Compose files

### Adding New Commands

1. Create command class in `commands/`
2. Add CLI interface in `cli.py`
3. Add tests in `tests/unit/`
4. Update documentation

### Extending Functionality

- **New Volume Types**: Modify `EnvironmentManager.get_volume_names()`
- **Custom Networks**: Update `DockerManager.create_network()`
- **Additional Validation**: Extend `utils/validation.py`

## 📊 Performance

- **Worktree Creation**: ~30 seconds
- **Volume Copying**: ~60 seconds (depending on data size)
- **Container Startup**: ~45 seconds
- **Memory Usage**: ~1GB per worktree
- **Disk Usage**: ~5GB per worktree (varies with data)

## ✅ Status

**Production Ready**: All tests passing, 100% functional compatibility with original bash script.

**Key Features**:
- ✅ Complete environment isolation
- ✅ Dynamic routing with Caddy
- ✅ Volume management and backup
- ✅ Git worktree integration
- ✅ Docker Compose passthrough commands
- ✅ Comprehensive error handling
- ✅ Rich console output
- ✅ Type safety throughout
- ✅ Project-agnostic setup
- ✅ User guide in each .dockertree directory
- ✅ MCP server for AI assistant integration
- ✅ JSON output mode for programmatic access
 - ✅ Push command for SCP-based deployment with optional auto-import

## 🚀 Deployment (Push)

### Basic Push
```bash
# Export and transfer a package to a remote server via SCP
dockertree push feature-auth user@server:/var/dockertree/packages
```

### Create Droplet and Push
```bash
# Create a new Digital Ocean droplet and push to it
# scp_target is optional when using --create-droplet (defaults to root@<droplet-ip>:/root)
dockertree push feature-auth --create-droplet \
  --prepare-server --auto-import \
  --domain app.example.com

# With custom username and path (server part is ignored, replaced with droplet IP)
dockertree push feature-auth ubuntu@dummy:/home/ubuntu --create-droplet \
  --prepare-server --auto-import

# With custom droplet configuration
dockertree push feature-auth --create-droplet \
  --droplet-name myapp-prod \
  --droplet-region sfo3 --droplet-size s-2vcpu-4gb \
  --prepare-server --auto-import
```

### Auto-Import on Remote with Domain and HTTPS
```bash
# Push with automatic DNS management and HTTPS deployment
dockertree push feature-auth user@server:/var/dockertree/packages \
  --auto-import --prepare-server \
  --domain app.example.com \
  --dns-token $DIGITALOCEAN_API_TOKEN

# Or use environment variable for token
export DIGITALOCEAN_API_TOKEN=your_token_here
dockertree push feature-auth user@server:/var/dockertree/packages \
  --auto-import --domain app.example.com

# Or add to .env file in project root (no export needed)
# .env file:
# DIGITALOCEAN_API_TOKEN=your_token_here
dockertree push feature-auth user@server:/var/dockertree/packages \
  --auto-import --domain app.example.com

# Options:
#   --domain myapp.example.com        # Domain for HTTPS deployment
#   --dns-token <token>                 # Digital Ocean API token (or use DIGITALOCEAN_API_TOKEN/DNS_API_TOKEN env var)
#   --skip-dns-check                    # Skip DNS validation
#   --ip 203.0.113.10                   # IP-only HTTP mode (no Let's Encrypt for IPs)
#   --create-droplet                    # Create new droplet before pushing (scp_target optional, defaults to root@<droplet-ip>:/root)
#   --droplet-name <name>                # Droplet name (defaults to branch name)
#   --droplet-region <region>            # Droplet region (defaults from env or nyc1)
#   --droplet-size <size>                # Droplet size (defaults from env or s-1vcpu-1gb)
#   --droplet-image <image>              # Droplet image (defaults from env or ubuntu-22-04-x64)
#   --droplet-ssh-keys <key>             # SSH key names (comma-separated, e.g., anders,peter)
# Note: When using --create-droplet, the droplet is always waited for until ready before pushing
```

### DNS Management
Dockertree can automatically manage DNS records via Digital Ocean DNS API:

- **Automatic Domain Creation**: If a subdomain doesn't exist, dockertree will automatically create it when `--domain` is provided
- **Domain Validation**: Checks if DNS records already exist and point to the correct server
- **Supported Provider**: Digital Ocean DNS
- **API Token Configuration**: Multiple options supported (priority order):
  1. CLI flag: `--dns-token <token>`
  2. Shell environment: `export DIGITALOCEAN_API_TOKEN=token` or `export DNS_API_TOKEN=token`
  3. `.env` file: Add `DIGITALOCEAN_API_TOKEN=token` or `DNS_API_TOKEN=token` to project root `.env` file
  4. Global config: Add `DIGITALOCEAN_API_TOKEN=token` or `DNS_API_TOKEN=token` to `~/.dockertree/env.dockertree` file

### DNS Provider Setup

#### Digital Ocean
1. Generate a personal access token from https://cloud.digitalocean.com/account/api/tokens
2. Configure token using one of these methods:
   - **Shell environment** (recommended for CI/CD): `export DIGITALOCEAN_API_TOKEN=your_token`
   - **Project `.env` file** (recommended for project-specific tokens): Add `DIGITALOCEAN_API_TOKEN=your_token` to your project root `.env` file
   - **Global config** (recommended for personal tokens): Add `DIGITALOCEAN_API_TOKEN=your_token` to `~/.dockertree/env.dockertree` file
   - **CLI flag**: Use `--dns-token <token>` when pushing

### DNS Propagation

When dockertree creates a DNS record, it is immediately available on Digital Ocean's authoritative nameservers, but it takes time to propagate to all DNS resolvers worldwide.

**What is DNS Propagation?**
DNS propagation is the time it takes for DNS record changes to spread across all DNS servers on the internet. When you create a new DNS record, it's immediately available on the authoritative nameservers (Digital Ocean's in this case), but other DNS resolvers (like Google's 8.8.8.8 or Cloudflare's 1.1.1.1) cache DNS records and may take time to update.

**Expected Propagation Times:**
- **Authoritative nameservers**: Immediate (Digital Ocean nameservers)
- **Public resolvers**: 5-60 minutes typically
- **Global propagation**: Up to 48 hours in rare cases

**Verifying DNS Records:**

You can verify DNS records in several ways:

1. **Check on Digital Ocean nameservers** (immediate):
   ```bash
   dig your-domain.com A @ns1.digitalocean.com
   dig your-domain.com A @ns2.digitalocean.com
   dig your-domain.com A @ns3.digitalocean.com
   ```

2. **Check on public resolvers** (may take time):
   ```bash
   dig your-domain.com A @8.8.8.8      # Google DNS
   dig your-domain.com A @1.1.1.1      # Cloudflare DNS
   ```

3. **Check from your local machine**:
   ```bash
   dig your-domain.com A
   nslookup your-domain.com
   ```

**Troubleshooting:**
- If the record exists on Digital Ocean nameservers but not on public resolvers, wait a few more minutes
- If the record doesn't exist on any nameserver, check that the DNS record was created successfully
- Browser DNS caches may need to be cleared or wait for TTL expiration

### Notes
- When using `--domain`, dockertree automatically enables HTTPS via Caddy's Let's Encrypt integration
- When using `--ip`, deployments are HTTP-only. Certificate authorities do not issue certificates for IP addresses; use a domain for HTTPS.
- DNS records are automatically created when `--domain` is provided (use `--skip-dns-check` to skip DNS management)
- You can add defaults in `.dockertree/config.yml` (optional):
```yaml
deployment:
  default_server: user@server:/var/dockertree/packages
  default_domain: myapp.example.com
  default_ip: 203.0.113.10
  ssh_key: ~/.ssh/deploy_key
```

---

*For detailed architecture information, see [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md)*

Additional Push Details:
- Auto-import uses a robust remote script with strict mode and consistent quoting to avoid empty variables and broken chains.
- The remote script resolves the dockertree binary (prefers `/opt/dockertree-venv/bin/dockertree`, falls back to `dockertree`).
- Import runs with `--non-interactive`; older dockertree versions safely ignore unknown flags.
- If an existing dockertree project is detected on the server, a normal import is used; otherwise standalone import is performed.
