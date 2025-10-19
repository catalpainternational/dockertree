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
| `setup` | Initialize dockertree for this project | `dockertree setup` |

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

### Shell Completion Management
| Command | Description | Example |
|---------|-------------|---------|
| `completion install [shell]` | Install shell completion | `dockertree completion install` |
| `completion uninstall` | Remove shell completion | `dockertree completion uninstall` |
| `completion status` | Show completion status | `dockertree completion status` |

## 🔧 Configuration

### Project Setup

When you run `dockertree setup`, it creates a `.dockertree/` directory with:

- `config.yml` - Project configuration
- `docker-compose.worktree.yml` - Transformed compose file (generated from existing docker-compose.yml)
- `Caddyfile.dockertree` - Caddy configuration
- `README.md` - User guide optimized for coding agents
- `worktrees/` - Worktree directories

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

---

*For detailed architecture information, see [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md)*
