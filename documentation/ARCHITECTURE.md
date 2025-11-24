# Dockertree CLI Architecture

This document provides a comprehensive overview of the dockertree CLI architecture, designed for agentic coders and system integrators.

## 🏗️ System Architecture

### High-Level Overview

Dockertree CLI creates isolated development environments by orchestrating three core systems:

1. **Git Worktrees** - Isolated working directories for each branch
2. **Docker Compose** - Containerized services with branch-specific volumes
3. **Caddy Proxy** - Dynamic routing based on branch names

### Project-Agnostic Design

Dockertree is designed to work with any Docker Compose project through:

- **Auto-detection**: Automatically detects existing `docker-compose.yml` files
- **Dynamic Configuration**: Uses `.dockertree/config.yml` for project-specific settings
- **Template Transformation**: Converts existing compose files to worktree-compatible versions
- **Flexible Setup**: `dockertree setup` command initializes any project

```
┌─────────────────────────────────────────────────────────────────┐
│                        Dockertree CLI                           │
├─────────────────────────────────────────────────────────────────┤
│  CLI Interface (Click)                                          │
│  ├── Command Routing                                            │
│  ├── Argument Validation                                        │
│  └── Error Handling                                             │
├─────────────────────────────────────────────────────────────────┤
│  Command Layer                                                  │
│  ├── CaddyManager      ├── WorktreeManager                     │
│  ├── VolumeManager     └── UtilityManager                      │
├─────────────────────────────────────────────────────────────────┤
│  Core Infrastructure                                           │
│  ├── DockerManager     ├── GitManager                         │
│  └── EnvironmentManager                                        │
├─────────────────────────────────────────────────────────────────┤
│  Utilities & Configuration                                     │
│  ├── Validation        ├── Logging                             │
│  ├── Path Utils        └── Settings                            │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow Architecture

#### CLI Interface Flow
```
User Command → CLI Interface → Command Manager → Core Infrastructure → External Systems
     ↓              ↓              ↓                    ↓                    ↓
  Input         Validation      Business Logic      Docker/Git Ops      Containers/Volumes
     ↓              ↓              ↓                    ↓                    ↓
  Output ←    Error Handling ←   Result Processing ←   Status Check ←    System Response
```

#### MCP Server Flow
```
AI Assistant → MCP Server → CLI Wrapper → WorktreeOrchestrator → Core Infrastructure → External Systems
     ↓              ↓              ↓              ↓                    ↓                    ↓
  Tool Call    JSON Parsing    CLI Command    Business Logic      Docker/Git Ops      Containers/Volumes
     ↓              ↓              ↓              ↓                    ↓                    ↓
  Response ←   JSON Output ←   CLI Output ←   Result Processing ←   Status Check ←    System Response
```

#### Unified Architecture
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   CLI Interface │    │   MCP Server    │    │  AI Assistants  │
│                 │    │                 │    │                 │
│  • Click CLI    │    │  • MCP Tools    │    │  • Claude       │
│  • Commands     │    │  • Resources    │    │  • Cursor       │
│  • Validation   │    │  • JSON Output  │    │  • Automation   │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    ┌─────────────▼─────────────┐
                    │   WorktreeOrchestrator    │
                    │                           │
                    │  • create_worktree()     │
                    │  • start_worktree()      │
                    │  • stop_worktree()       │
                    │  • remove_worktree()     │
                    │  • list_worktrees()      │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │    Core Infrastructure    │
                    │                           │
                    │  • DockerManager         │
                    │  • GitManager            │
                    │  • EnvironmentManager    │
                    └───────────────────────────┘
```

## 🔧 Setup and Configuration System

### Project Initialization Flow

```
User runs: dockertree setup
    ↓
1. Create .dockertree/ directory structure
    ↓
2. Detect existing docker-compose.yml
    ↓
3. Transform compose file → docker-compose.worktree.yml
    ↓
4. Generate config.yml with detected services
    ↓
5. Copy Caddyfile template
    ↓
Ready for worktree creation
    ↓
6. Detect Django settings and validate env-driven keys (optional monkey patch)
```

### Configuration Files

#### `.dockertree/config.yml` - Project Configuration
```yaml
project_name: myproject
caddy_network: dockertree_caddy_proxy
worktree_dir: worktrees
services:
  web:
    container_name_template: ${COMPOSE_PROJECT_NAME}-web
  db:
    container_name_template: ${COMPOSE_PROJECT_NAME}-db
volumes:
  - postgres_data
  - redis_data
environment:
  DEBUG: "True"
  ALLOWED_HOSTS: "localhost,127.0.0.1,*.localhost,web"
```

#### `.dockertree/docker-compose.worktree.yml` - Transformed Compose File
- Original `docker-compose.yml` with worktree-specific modifications
- Container names use `${COMPOSE_PROJECT_NAME}` variables
- Volumes are made branch-specific
- Ports converted to `expose` for internal networking (extracts container port only)
- Caddy labels added for web services (web, app, frontend, api)
- Web services automatically connected to `dockertree_caddy_proxy` network

### Dynamic Configuration Loading
### Django Compatibility Validation
- Detection: presence of `manage.py` and a `settings.py` module in the project
- Validated keys: `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `USE_X_FORWARDED_HOST`, `SECURE_PROXY_SSL_HEADER`
- Behavior:
  - If missing/incomplete, print console guidance with a safe copy/paste snippet
  - If `--monkey-patch` was passed to `dockertree setup`, append a guarded block to `settings.py` that reads the values from environment variables

### SQLite Persistence Guidance

Export/import captures Docker volumes by design. For SQLite-backed projects, ensure the database file is stored on a named volume mounted into the web container (e.g., mount `sqlite_data` at `/data` and configure Django `NAME` to `/data/db.sqlite3`).

- Rationale: files under bind mounts like `/app/db.sqlite3` are not part of any Docker named volume and won’t be included in Dockertree volume backups.
- Outcome: with a named volume (e.g., `sqlite_data`), SQLite state is preserved alongside other volumes during export/import.

The system uses a fallback hierarchy:
1. **Project Config**: `.dockertree/config.yml` (if exists)
2. **Default Config**: Built-in defaults for new projects
3. **Legacy Mode**: Hardcoded values for backward compatibility

## 🧩 Component Architecture

### Core Infrastructure Layer

#### DockerManager (`core/docker_manager.py`)
**Responsibility**: All Docker operations and container lifecycle management

**Key Methods**:
- `create_network()` - Create external `dockertree_caddy_proxy` network
- `copy_volume()` - Copy data between volumes using file-level copy
- `_copy_volume_files()` - Generic file copy method for all volume types
- `create_worktree_volumes()` - Create branch-specific volumes
- `run_compose_command()` - Execute Docker Compose commands
- `backup_volumes()` / `restore_volumes()` - Volume management

**Key Features**:
- **Multi-project Support**: Accepts `project_root` parameter for operation on different projects
- **MCP Compatibility**: Supports structured output for programmatic access
- **Safe Database Copying**: Prevents PostgreSQL corruption by stopping containers before file operations
- **Shared Container Management**: Common methods for stopping/starting containers before volume operations

**Dependencies**: Docker daemon, Docker Compose, PostgreSQL tools
**External Interactions**: Docker API, volume operations, network management, PostgreSQL backup/restore

#### GitManager (`core/git_manager.py`)
**Responsibility**: Git worktree operations and branch management

**Key Methods**:
- `create_worktree()` - Create Git worktree
- `remove_worktree()` - Remove worktree safely
- `list_worktrees()` - List active worktrees
- `delete_branch_safely()` - Safe branch deletion with protection
- `validate_worktree_exists()` - Worktree validation

**Key Features**:
- **Multi-project Support**: Accepts `project_root` parameter for operation on different projects
- **MCP Compatibility**: Supports structured output for programmatic access

**Dependencies**: Git repository, worktree support
**External Interactions**: Git commands, file system operations

#### EnvironmentManager (`core/environment_manager.py`)
**Responsibility**: Environment configuration and volume naming

**Key Methods**:
- `create_worktree_env()` - Generate environment files
- `get_worktree_volume_names()` - Volume naming convention
- `get_environment_variables()` - Environment variable management
- `get_domain_name()` - Domain name generation

**Key Features**:
- **Multi-project Support**: Accepts `project_root` parameter for operation on different projects
- **MCP Compatibility**: Supports structured output for programmatic access

**Dependencies**: Path utilities, configuration settings
**External Interactions**: File system, environment variables

#### WorktreeOrchestrator (`core/worktree_orchestrator.py`)
**Responsibility**: Core worktree orchestration used by both CLI and MCP interfaces

**Key Methods**:
- `create_worktree()` - Create new worktree with complete orchestration
- `start_worktree()` - Start worktree environment with orchestration
- `stop_worktree()` - Stop worktree environment
- `remove_worktree()` - Remove worktree completely
- `delete_worktree()` - Delete worktree and branch completely
- `list_worktrees()` - List all worktrees with status
- `get_worktree_info()` - Get detailed worktree information

**Key Features**:
- **Multi-project Support**: Accepts `project_root` parameter for operation on different projects
- **MCP Mode**: Supports `mcp_mode` parameter to suppress stdout logging for programmatic use
- **Fractal Design**: Implements `_copy_dockertree_to_worktree()` for recursive configuration copying
- **Unified Interface**: Provides business logic for both CLI and MCP server interfaces

**Dependencies**: DockerManager, GitManager, EnvironmentManager
**External Interactions**: Docker operations, Git operations, file system operations

### Command Layer

#### CaddyManager (`commands/caddy.py`)
**Responsibility**: Global Caddy proxy management

**Key Methods**:
- `start_global_caddy()` - Start global Caddy container
- `stop_global_caddy()` - Stop global Caddy container
- `is_caddy_running()` - Check Caddy status

**Dependencies**: DockerManager, network configuration
**External Interactions**: Caddy container, Docker network

#### WorktreeManager (`commands/worktree.py`)
**Responsibility**: Complete worktree lifecycle management

**Key Methods**:
- `create_worktree()` - Create new worktree with volumes
- `start_worktree()` - Start worktree environment
- `stop_worktree()` - Stop worktree environment
- `remove_worktree()` - Remove worktree (keep branch)
- `remove_all_worktrees()` - Bulk worktree operations

**Dependencies**: DockerManager, GitManager, EnvironmentManager
**External Interactions**: Docker Compose, Git operations, volume management

#### VolumeManager (`commands/volumes.py`)
**Responsibility**: Volume operations and data management

**Key Methods**:
- `list_volumes()` - List worktree volumes
- `backup_volumes()` - Backup volume data
- `restore_volumes()` - Restore from backup
- `clean_volumes()` - Clean up volumes

**Dependencies**: DockerManager, EnvironmentManager
**External Interactions**: Docker volumes, file system

#### UtilityManager (`commands/utility.py`)
**Responsibility**: Utility operations and system information

**Key Methods**:
- `list_worktrees()` - List active worktrees
- `prune_worktrees()` - Clean up prunable worktrees
- `get_system_info()` - System status information

**Dependencies**: GitManager
**External Interactions**: Git operations, system queries

#### DropletCommands (`commands/droplets.py`)
**Responsibility**: Digital Ocean droplet management operations

**Key Methods**:
- `create_droplet()` - Create new droplet with configurable options (default: creates and pushes environment)
- `list_droplets()` - List all droplets with status information (supports table, JSON, CSV output)
- `destroy_droplet()` - Destroy droplet and/or DNS records with confirmation
- `get_droplet_info()` - Get detailed droplet information
- `_destroy_dns_only()` - Destroy DNS records only (internal helper)
- `_destroy_dns_for_ip()` - Destroy DNS records pointing to specific IP (internal helper)

**Key Features**:
- **Selective Destruction**: `--only-droplet` and `--only-domain` flags for granular control
- **DNS Auto-detection**: Automatically finds DNS records pointing to droplet IP
- **Domain Confirmation**: Requires typing domain name for DNS deletion (unless `--force`)
- **Multiple Output Formats**: Table (default), JSON (`--as-json`), CSV (`--as-csv`)
- **Domain Display**: Lists associated domains for each droplet in list output

**Dependencies**: DropletManager, DNSManager
**External Interactions**: Digital Ocean API, droplet lifecycle management, DNS record management

### CLI Interface Layer

#### DockertreeCLI (`cli.py`)
**Responsibility**: Command-line interface and argument handling

**Key Features**:
- Click-based command routing
- Argument validation and parsing
- Error handling and user feedback
- Command aliases (`-D` for delete, `-r` for remove, `start` for start-proxy, `stop` for stop-proxy)

**Command Structure**:
```python
@cli.command('start-proxy')
def start_proxy():
    """Start global Caddy proxy container."""
    # Implementation

@cli.command('start')
def start():
    """Start global Caddy proxy container (alias for start-proxy)."""
    # Implementation
```

### Utilities Layer

#### Validation (`utils/validation.py`)
**Responsibility**: Input validation and system checks

**Key Functions**:
- `validate_branch_name()` - Branch name format validation
- `validate_docker_running()` - Docker daemon check
- `validate_git_repository()` - Git repository validation
- `check_prerequisites()` - System prerequisite validation

#### Logging (`utils/logging.py`)
**Responsibility**: Colored output and progress indication

**Key Functions**:
- `log_info()`, `log_success()`, `log_warning()`, `log_error()` - Colored logging
- `show_progress()` - Progress indicators
- `show_version()`, `show_help()` - Information display

#### Path Utils (`utils/path_utils.py`)
**Responsibility**: Path resolution and file system operations

**Key Functions**:
- `get_compose_override_path()` - Compose file resolution
- `get_worktree_branch_name()` - Branch name extraction
- `ensure_main_repo()` - Repository validation

#### JSON Output (`utils/json_output.py`)
**Responsibility**: Standardized JSON output formatting for CLI commands and MCP integration

**Key Classes**:
- `JSONOutput` - Main formatter class for structured output

**Key Methods**:
- `success()` - Format successful operation results
- `error()` - Format error results with error codes and details
- `worktree_info()` - Format worktree information
- `volume_info()` - Format volume information
- `container_info()` - Format container information
- `print_json()` - Print data as JSON to stdout
- `print_success()`, `print_error()`, `print_info()`, `print_warning()` - Conditional JSON/human output

**Key Features**:
- **CLI Integration**: `--json` flag support for all CLI commands
- **MCP Compatibility**: Structured output for programmatic access
- **Error Handling**: Standardized error codes and details
- **Timestamping**: Automatic timestamp inclusion
- **Type Safety**: Structured data types for all output formats

**Dependencies**: Standard library (json, sys, datetime)
**External Interactions**: stdout, CLI framework integration

## ⚙️ Configuration Architecture

### Settings Hierarchy

```
config/settings.py (Central Configuration)
├── Version Information
├── Project Configuration
├── File Paths
├── Volume Naming
├── Protected Branches
├── Environment Variables
└── Utility Functions
```

### Configuration Files

#### Docker Compose Files
- **`docker-compose.global-caddy.yml`** - Global Caddy proxy
- **`.dockertree/docker-compose.worktree.yml`** - Generated worktree environments (created by setup)
- **`Caddyfile.dockertree`** - Caddy configuration

#### Environment Files
- **`.env`** - Base environment variables
- **`.dockertree/env.dockertree`** - Worktree-specific variables

### Volume Naming Convention

Dockertree automatically transforms volume names to ensure isolation between worktrees:

```python
# Pattern: {COMPOSE_PROJECT_NAME}_{volume_type}
# Where COMPOSE_PROJECT_NAME = {project_name}-{branch_name}
feature-auth_postgres_data    # Database data
feature-auth_redis_data       # Cache data
feature-auth_media_files      # User uploads
```

#### Automatic Volume Transformation

During `dockertree setup`, the system automatically transforms volume definitions in the source `docker-compose.yml`:

**Source compose file**:
```yaml
volumes:
  postgres_data:
    name: business_intelligence_postgres_data
  redis_data:
    name: business_intelligence_redis_data
```

**Transformed worktree compose**:
```yaml
volumes:
  postgres_data:
    name: ${COMPOSE_PROJECT_NAME}_postgres_data
  redis_data:
    name: ${COMPOSE_PROJECT_NAME}_redis_data
```

This ensures each worktree gets isolated volumes:
- `myproject-feature-auth_postgres_data`
- `myproject-feature-auth_redis_data`
- `myproject-feature-branch_postgres_data`
- `myproject-feature-branch_redis_data`

### Safe Volume Copying Architecture

Dockertree implements safe volume copying to prevent database corruption:

#### PostgreSQL Volume Safety

**Problem**: Copying PostgreSQL data files while the database is running causes corruption due to inconsistent WAL logs and checkpoint records.

**Solution**: Stop containers before file operations, then restart them:

1. **Container Management**: `_ensure_containers_stopped_for_volume_operation()` stops containers using volumes before operations
2. **File Copy Strategy**: Uses generic `_copy_volume_files()` method for all volume types (PostgreSQL, Redis, media)
3. **Container Restart**: `_restart_container()` restarts containers after operations complete

#### Implementation Flow

```
Volume Copy Request (create_worktree_volumes)
    ↓
For PostgreSQL volumes:
    ↓
_ensure_containers_stopped_for_volume_operation()
    ↓
Stop original container (if running)
    ↓
copy_volume() → _copy_volume_files()
    ↓
Copy files using Alpine container
    ↓
_restart_container()
    ↓
Restart original container
    ↓
Complete
```

#### Benefits

- **Eliminates Corruption**: No more "invalid checkpoint record" errors
- **Consistent Approach**: Same file copy method for all volume types
- **DRY Principle**: Shared container management methods between copy and archive operations
- **Simple and Reliable**: Single code path, easier to maintain

### Network Architecture

```
Global Network (dockertree_caddy_proxy)
├── dockertree_caddy_proxy (Global Caddy)
├── caddy_monitor (Docker monitor)
└── Worktree Networks
    ├── {branch}_internal (Database, Redis)
    ├── {branch}_web (Web application)
    └── dockertree_caddy_proxy (Routing)
```

## 🧩 Fractal Design Pattern

### Recursive Configuration Architecture

Dockertree implements a fractal design pattern where each worktree receives its own complete `.dockertree` configuration directory. This creates a recursive, self-contained structure that mirrors the main project's configuration.

#### Fractal Structure

```
Project Root/
├── .dockertree/                    # Main configuration
│   ├── config.yml
│   ├── docker-compose.worktree.yml
│   ├── Caddyfile.dockertree
│   └── README.md
└── worktrees/                      # Worktree directories (configurable in config.yml)
    └── {branch_name}/
        └── .dockertree/            # Worktree configuration (fractal copy)
            ├── config.yml          # Identical to main
            ├── docker-compose.worktree.yml
            ├── Caddyfile.dockertree
            └── README.md           # User guide
```

#### Implementation Details

**Worktree Directory Location**: Worktree directories are stored in `{project_root}/worktrees/` as configured in `.dockertree/config.yml` (the `worktree_dir` setting, which defaults to `"worktrees"`).

**Method**: `WorktreeOrchestrator._copy_dockertree_to_worktree()`

1. **Source Detection**: Finds the true project root containing `.dockertree/config.yml`
2. **Selective Copying**: Copies entire `.dockertree` directory excluding the `worktrees/` subdirectory
3. **Recursive Structure**: Each worktree becomes a self-contained dockertree project
4. **Configuration Preservation**: Maintains identical configuration across all levels

**Fractal Execution**: `get_project_root()` and `detect_execution_context()`

1. **Local-First Detection**: Checks current directory for `.dockertree/config.yml` before searching upward
2. **Context Awareness**: Detects when running from within a worktree vs main project root
3. **Self-Contained Operation**: Worktrees can run dockertree commands using their own configuration
4. **Backwards Compatibility**: Still works from main project root with centralized configuration

#### Benefits

- **Isolation**: Each worktree has complete configuration independence
- **Consistency**: Identical configuration structure at all levels
- **Self-Documentation**: Each worktree includes its own README.md
- **Scalability**: Supports nested or complex project structures
- **Maintenance**: Configuration changes propagate through fractal structure
- **Fractal Execution**: Worktrees can run dockertree commands from within their own directory
- **No Path Dependencies**: Eliminates "getcwd: cannot access parent directories" errors

#### Use Cases

- **Multi-tenant Development**: Each worktree can have project-specific configurations
- **Environment Variations**: Different worktrees can have different settings
- **Documentation**: Each worktree includes its own user guide
- **Debugging**: Isolated configuration for troubleshooting

## 🔌 MCP Server Architecture

### Model Context Protocol Integration

The dockertree MCP server provides programmatic access to dockertree functionality through the Model Context Protocol, enabling AI assistants to manage isolated development environments.

#### MCP Server Structure

```
dockertree_mcp/
├── server.py              # Main MCP server implementation
├── config.py              # MCP configuration management
├── tools/                 # MCP tool implementations
│   ├── worktree_tools.py  # Worktree management tools
│   ├── volume_tools.py    # Volume management tools
│   └── caddy_tools.py     # Caddy proxy tools
├── resources/             # MCP resource implementations
│   ├── worktree_resources.py
│   └── documentation.py
└── utils/                 # MCP utilities
    ├── cli_wrapper.py     # CLI command wrapper
    └── response_enrichment.py
```

#### MCP Tools

**Worktree Management Tools**:
- `create_worktree` - Create isolated development environment
- `start_worktree` - Start worktree containers
- `stop_worktree` - Stop worktree containers
- `remove_worktree` - Remove worktree (keep branch)
- `delete_worktree` - Delete worktree and branch
- `list_worktrees` - List active worktrees
- `get_worktree_info` - Get detailed worktree information

**Volume Management Tools**:
- `list_volumes` - List worktree volumes
- `get_volume_sizes` - Get volume size information
- `backup_volumes` - Backup worktree volumes
- `restore_volumes` - Restore from backup
- `clean_volumes` - Clean up volumes

**Caddy Proxy Tools**:
- `start_proxy` - Start global Caddy proxy
- `stop_proxy` - Stop global Caddy proxy
- `get_proxy_status` - Get proxy status

#### MCP Resources

**Static Documentation Resources**:
- `dockertree://concept` - Dockertree concept explanation
- `dockertree://architecture` - Technical architecture
- `dockertree://workflows` - Usage patterns
- `dockertree://terminology` - Glossary of terms
- `dockertree://url-patterns` - URL construction patterns
- `dockertree://best-practices` - Best practices guide

**Dynamic Project Resources**:
- `dockertree://project` - Current project context
- `dockertree://worktrees` - Active worktrees with status
- `dockertree://volumes` - Worktree volumes
- `dockertree://proxy` - Caddy proxy status
- `dockertree://state` - Complete system state

#### Working Directory Configuration

**Critical Design**: The MCP server can run from any location but requires a `working_directory` parameter to specify which project to operate on.

**Key Concepts**:
- **MCP Server Location**: Where the server is installed (e.g., `/Users/ders/projects/dockertree`)
- **Target Project Directory**: The project to manage (e.g., `/Users/ders/kenali/blank`)
- **Working Directory Parameter**: Tells the server which project to operate on

**Implementation**:
- All MCP tools require `working_directory` parameter
- Server validates project directory contains `.dockertree/config.yml`
- Supports operation on multiple projects simultaneously
- Environment variable fallback: `DOCKERTREE_WORKING_DIR`

#### CLI Integration

**CLI Wrapper Pattern**:
- MCP tools invoke dockertree CLI commands with `--json` flag
- Structured output enables programmatic access
- Error handling and validation through CLI layer
- Consistent behavior between CLI and MCP interfaces

**Benefits**:
- **AI Assistant Integration**: Enables Claude, Cursor, and other AI tools
- **Programmatic Access**: Structured API for automation
- **Multi-project Support**: Manage multiple projects from single MCP server
- **Consistent Interface**: Same functionality as CLI with structured output

## 📦 Package Management Architecture

### Import Modes and Auto-Detection

Dockertree package import supports two modes with automatic detection:

#### Mode Detection Logic

```python
def _is_in_existing_project(self) -> bool:
    """Check if we're in an existing dockertree project."""
    # Requires both .dockertree/config.yml AND git repository
    dockertree_config = self.project_root / ".dockertree" / "config.yml"
    if not dockertree_config.exists():
        return False
    if not validate_git_repository(self.project_root):
        return False
    return True
```

#### Normal Mode (Existing Project)

**When**: Directory contains `.dockertree/config.yml` and is a git repository

**Process**:
1. Validate package integrity
2. Extract metadata and determine branch name
3. Create new worktree using WorktreeOrchestrator
4. Restore environment files to worktree
5. Restore volumes to branch-specific volumes
6. Extract code archive (if included in package)

**Result**: New worktree added to existing project

#### Standalone Mode (New Project)

**When**: Directory does NOT contain `.dockertree/config.yml` OR not a git repository

**Process**:
1. Validate package integrity
2. Check package includes code (required for standalone)
3. Determine target directory (from flag or auto-generate)
4. Initialize new git repository
5. Extract code archive from package
6. Commit initial code
7. Run `dockertree setup` to initialize configuration
8. Restore environment files
9. Restore volumes (if requested)

**Result**: Complete new dockertree project ready to use

### Import Flow Diagram

```
Package Import Request
    ↓
Standalone explicitly set?
    ↓ NO                          ↓ YES
Auto-detect mode                Use explicit value
    ↓                               ↓
_is_in_existing_project()?      Standalone = True/False
    ↓ YES            ↓ NO            ↓
Normal Mode     Standalone Mode   As specified
    ↓                ↓                ↓
Import to        Create new       Execute
existing         project          accordingly
worktree
```

### DRY Architecture

All logic centralized in `PackageManager` class:

```
                    PackageManager (core)
                         ├── _is_in_existing_project()
                         ├── import_package()
                         │   ├── _normal_import()
                         │   ├── _standalone_import()
                         │   └── _extract_and_validate_package()
                         ↑
                    Used by both:
                         │
        ┌────────────────┴────────────────┐
        │                                  │
    CLI Layer                          MCP Layer
    PackageCommands                    PackageTools
    (thin wrapper)                     (thin wrapper)
```

### CLI and MCP Integration

Both interfaces use identical parameters and logic:

**CLI**:
```bash
dockertree packages import package.tar.gz --standalone --target-dir ./project
```

**MCP**:
```json
{
  "package_file": "package.tar.gz",
  "standalone": true,
  "target_directory": "./project"
}
```

### VPC Deployment Architecture

Dockertree supports VPC deployments for secure private networking between droplets:

**VPC Metadata in Packages**:
- Packages can include `vpc_deployment` metadata when VPC information is available or `--exclude-deps` is used
- Metadata includes: `is_worker`, `excluded_services`, `central_server_private_ip`, `vpc_uuid`, `private_ip_address`
- Used for automatic worker environment configuration during import

**Automatic Port Binding**:
- Configurable via `.dockertree/config.yml`: `vpc.auto_bind_ports: true`
- Only activates when `--containers` flag is used and service has `expose` ports but no `ports` mapping
- When `vpc.bind_to_private_ip: true` (default), binds to private IP address instead of `0.0.0.0`
- This prevents public internet exposure while maintaining VPC accessibility
- Falls back to `0.0.0.0` if private IP is not available (with warning)

**Security Configuration**:
- **Private IP Binding**: By default, Redis and database ports bind to private IP only (not `0.0.0.0`)
- **Firewall Rules**: Optional automatic UFW configuration via `vpc.auto_configure_firewall: true`
- When enabled, automatically allows VPC network (10.0.0.0/8) access to Redis (6379) and PostgreSQL (5432) ports
- Firewall configuration runs automatically after package import when droplet has private IP

**Worker Environment Configuration**:
- Automatically configures environment variables when package metadata indicates worker deployment
- Pattern-based detection: finds env vars referencing excluded services (e.g., `DB_HOST`, `REDIS_URL`)
- Replaces service names with central server's VPC private IP
- Only activates when `vpc_deployment.is_worker=true` in package metadata

**VPC UUID Tracking**:
- `--central-droplet-name` flag enables explicit VPC UUID reuse from central droplet
- Conservative approach: no auto-detection, requires explicit flag
- VPC UUID stored in `DropletInfo` and package metadata for reference

### Standalone Requirements

For standalone import to succeed:

1. **Package must include code**: Export with `--include-code` (default)
2. **Target directory must not exist**: Prevents accidental overwrites
3. **Git must be available**: For repository initialization
4. **Docker must be running**: For volume restoration

### Use Cases

**Team Onboarding**:
```bash
# New developer, no repo cloned
dockertree packages import team-dev-env.tar.gz
# → Complete project ready instantly
```

**Environment Migration**:
```bash
# Move project to new machine
dockertree packages import myproject.tar.gz --standalone --target-dir ~/projects/myapp
```

**Testing/Demo**:
```bash
# Spin up temporary environment
dockertree packages import demo-package.tar.gz --standalone
```

**Backup/Restore**:
```bash
# Restore from backup
dockertree packages import backup-20240115.tar.gz --standalone
```

## 🔌 Extension Architecture
## 🌐 Deployment Architecture (Push & Import)

### Domain vs IP Deployments

- Domain (`--domain sub.domain.tld`):
  - Automatic DNS management via Digital Ocean DNS API
  - DNS record creation with user confirmation if subdomain doesn't exist
  - Caddy routes traffic using the provided domain
  - HTTPS available via automatic certificate management (Let's Encrypt)
  - Environment overrides set `SITE_DOMAIN=https://{domain}` and include domain in `ALLOWED_HOSTS`
  - Dynamic HTTPS configuration via Caddy admin API

- IP (`--ip x.x.x.x`):
  - HTTP-only (no TLS); certificate authorities do not issue certificates for IPs
  - Caddy can route using the IP value, but remains HTTP unless manually configured
  - Environment overrides set `SITE_DOMAIN=http://{ip}` and include IP in `ALLOWED_HOSTS`

### DNS Provider Abstraction Layer

Dockertree includes a DNS provider abstraction layer for automatic DNS management:

#### DNSManager (`core/dns_manager.py`)
**Responsibility**: Unified interface for DNS provider operations

**Key Components**:
- `DNSProvider` abstract base class with interface methods
- Provider registry for auto-detection and factory creation
- Shared utilities: `parse_domain()`, `is_domain()`, token resolution

**Key Methods**:
- `check_domain_exists()` - Check if subdomain exists and return current IP
- `create_subdomain()` - Create A record for subdomain
- `list_subdomains()` - List all subdomains for a domain
- `delete_subdomain()` - Delete A record for subdomain

**Provider Implementations**:
- `DigitalOceanProvider` (`core/dns_providers/digitalocean.py`) - Digital Ocean DNS API v2

**Provider-Specific Methods** (DigitalOceanProvider):
- `find_dns_records_by_ip()` - Find DNS A records pointing to a specific IP address
  - Supports domain-specific or account-wide search
  - Returns list of (subdomain, domain, record_id) tuples

**Features**:
- Automatic domain existence checking
- Automatic domain creation when `--domain` is provided (no confirmation prompt)
- DNS record deletion with domain name confirmation
- Server IP resolution (hostname to IP)
- IP-to-domain reverse lookup for finding associated DNS records
- Token management via CLI flags, shell environment variables, or `.env` files

**Token Resolution Priority** (highest to lowest):
1. Explicit `--dns-token` CLI flag
2. Shell environment variable (`DIGITALOCEAN_API_TOKEN`)
3. `.env` file in current directory (worktree or project root)
4. `.dockertree/env.dockertree` in current directory (worktree or project root)
5. `.env` file in parent project root (if in worktree)
6. `.dockertree/env.dockertree` in parent project root (if in worktree)
7. `~/.dockertree/env.dockertree` file (global)

**Fractal Token Resolution**: When running dockertree commands from within a worktree, if the token is not found in the worktree's `.env` or `.dockertree/env.dockertree` files, dockertree automatically falls back to checking the parent project root's files. This enables worktrees to inherit API tokens from the main project while still allowing worktree-specific overrides.

### Droplet Provider Abstraction Layer

Dockertree includes a droplet provider abstraction layer for cloud server management:

#### DropletManager (`core/droplet_manager.py`)
**Responsibility**: Unified interface for droplet provider operations

**Key Components**:
- `DropletProvider` abstract base class with interface methods
- Provider registry for auto-detection and factory creation
- `DropletInfo` dataclass for structured droplet information
- Shared utilities: token resolution, default configuration loading

**Key Methods**:
- `create_droplet()` - Create a new droplet
- `list_droplets()` - List all droplets
- `get_droplet()` - Get droplet information by ID
- `destroy_droplet()` - Destroy a droplet
- `wait_for_droplet_ready()` - Wait for droplet to be ready

**Provider Implementations**:
- `DigitalOceanProvider` (`core/dns_providers/digitalocean.py`) - Digital Ocean Droplets API v2

**Features**:
- Automatic droplet creation with configurable defaults
- Droplet status polling and readiness detection
- IP address extraction from droplet networks (public and private VPC IPs)
- VPC UUID tracking and reuse for worker deployments
- Token management via CLI flags, shell environment variables, or `.env` files
- Default configuration from `.env` or `.dockertree/env.dockertree`
- Integration with DNS deletion for cleanup operations
- Domain association display in list output

**VPC Networking Support**:
- `DropletInfo` includes `private_ip_address` and `vpc_uuid` fields
- `_extract_network_info()` helper method extracts both public and private IPs from API responses
- `--central-droplet-name` flag enables VPC UUID reuse for worker deployments
- Automatic VPC detection and configuration for multi-droplet setups

**Token Resolution**: Reuses `DNSManager.resolve_dns_token()` since both use the same Digital Ocean API token. Supports fractal token resolution with fallback to parent project root when running from worktrees.

**Default Configuration** (from `.env` or `.dockertree/env.dockertree`):
- `DROPLET_DEFAULT_REGION` (default: `nyc1`)
- `DROPLET_DEFAULT_SIZE` (default: `s-1vcpu-1gb`)
- `DROPLET_DEFAULT_IMAGE` (default: `ubuntu-22-04-x64`)
- `DROPLET_DEFAULT_SSH_KEYS` (comma-separated SSH key names, e.g., `anders,peter` - only names are supported, not numeric IDs or fingerprints)

### Push Command Flow

```
Export → (optional) DNS Management → Compress → SCP Transfer → (optional) Server Preparation → (optional) Remote Import → Start Proxy → Up
```

- DNS management (optional): checks/creates DNS records via Digital Ocean DNS API when `--domain` provided
- Server preparation (optional): checks presence of git, docker, docker compose, dockertree
- Remote import (optional): runs `dockertree packages import` with `--domain` or `--ip`, then starts services

### Droplet Create Command Flow

```
Create Droplet → Wait for Ready → (default) Push Environment → (optional) DNS Management → Compress → SCP Transfer → (optional) Server Preparation → (optional) Remote Import → Start Proxy → Up
```

- Droplet creation: creates new Digital Ocean droplet with configurable options
- Default behavior: automatically pushes environment after droplet creation
- `--create-only` flag: only creates droplet, skips push
- When pushing: droplet is always waited for until ready, SCP target defaults to `root@<droplet-ip>:/root`

### HTTPS Configuration Architecture

#### Dynamic HTTPS Detection
- `caddy-dynamic-config.py` detects domains vs IPs/localhost using `_is_domain()` helper
- When domains are detected, automatically configures:
  - HTTPS listener on port 443
  - TLS automation with Let's Encrypt (ACME)
  - Certificate management via Caddy's built-in automation

#### Caddyfile Configuration
- Base `Caddyfile.dockertree` has `auto_https on` to enable automatic HTTPS
- Dynamic configuration via admin API overrides base settings
- TLS automation configured per-domain when domains are detected

#### Certificate Management
- Automatic certificate issuance via Let's Encrypt
- Email from `CADDY_EMAIL` environment variable (defaults to `admin@example.com`)
- Certificates stored in `dockertree_caddy_data` volume
- Automatic renewal handled by Caddy

### Configuration Defaults

The following optional keys in `.dockertree/config.yml` influence push/import behavior:

```yaml
deployment:
  default_server: username@server:/path/to/packages
  default_domain: myapp.example.com
  default_ip: 203.0.113.10
  ssh_key: ~/.ssh/deploy_key

dns:
  provider: digitalocean
  api_token: ${DIGITALOCEAN_API_TOKEN}
  default_domain: example.com
```

**Token Resolution**:
DNS API tokens can be provided via:
- CLI flag: `--dns-token <token>`
- Shell environment: `export DIGITALOCEAN_API_TOKEN=token`
- Project `.env` file: Add `DIGITALOCEAN_API_TOKEN=token` to project root `.env` file
- Worktree `.env` file: Add `DIGITALOCEAN_API_TOKEN=token` to worktree `.env` file (overrides project root)
- Project `.dockertree/env.dockertree`: Add `DIGITALOCEAN_API_TOKEN=token` to project root `.dockertree/env.dockertree` file
- Worktree `.dockertree/env.dockertree`: Add `DIGITALOCEAN_API_TOKEN=token` to worktree `.dockertree/env.dockertree` file (overrides project root)
- Global config: Add `DIGITALOCEAN_API_TOKEN=token` to `~/.dockertree/env.dockertree` file

Priority order: CLI flag > shell environment > current directory (worktree or project root) `.env` > current directory `.dockertree/env.dockertree` > parent project root `.env` (if in worktree) > parent project root `.dockertree/env.dockertree` (if in worktree) > global config file

**Fractal Token Resolution**: When running from a worktree, dockertree first checks the worktree's configuration files, then falls back to the parent project root's files if the token is not found. This allows worktrees to inherit tokens from the main project while supporting worktree-specific overrides.

These are read via helper functions in `config/settings.py` and are entirely optional to preserve Phase 1 behavior.

### Droplet Management Integration

Droplet management is integrated into the create workflow:

**Droplet Create Command Integration**:
- Default behavior: creates droplet and automatically pushes environment
- `--create-only` flag: only creates droplet, skips push
- When pushing (default): `scp_target` is optional (defaults to `root@<droplet-ip>:/root`)
- If `scp_target` is provided, only username and path are used (server replaced with droplet IP)
- Droplet is always waited for until ready before pushing (no option to skip - required for push to work)
- Droplet IP address automatically updates SCP target
- Droplet defaults loaded from `.env` or `.dockertree/env.dockertree`

**Workflow**:
1. Create droplet with specified configuration
2. Always wait for droplet ready (required - push needs IP address and SSH access)
3. Extract droplet IP address
4. If not `--create-only`, update SCP target to use droplet IP (or construct from defaults if scp_target not provided)
5. Continue with standard push flow (export, transfer, import)

**Droplet Push Command**:
- Separate command for pushing to existing servers
- No droplet creation logic (moved to `droplet create`)
- Requires `scp_target` to be provided

### Adding New Commands

1. **Create Command Class** in `commands/`
```python
class NewCommandManager:
    def __init__(self):
        self.docker_manager = DockerManager()
        # Other dependencies
    
    def execute_command(self, args):
        # Implementation
```

2. **Add CLI Interface** in `cli.py`
```python
@cli.command()
@click.argument('param')
def new_command(param: str):
    """Description of new command."""
    try:
        manager = NewCommandManager()
        success = manager.execute_command(param)
        # Handle result
    except Exception as e:
        error_exit(f"Error: {e}")
```

3. **Add Tests** in `tests/unit/`
```python
def test_new_command():
    # Test implementation
```

### Extending Core Infrastructure

#### Custom Volume Types
```python
# In EnvironmentManager
def get_custom_volume_names(self, branch_name: str) -> dict:
    return {
        "custom": f"{branch_name}_custom_data",
        # Add new volume types
    }
```

#### Custom Network Configuration
```python
# In DockerManager
def create_custom_network(self, network_name: str) -> bool:
    # Custom network creation logic
```

### Configuration Extensions

#### Custom Environment Variables
```python
# In settings.py
CUSTOM_ENV_VARS = {
    "CUSTOM_SETTING": "default_value",
    # Add custom variables
}
```

#### Custom Validation
```python
# In utils/validation.py
def validate_custom_input(value: str) -> bool:
    # Custom validation logic
```

## 🔄 Integration Patterns

### Docker Integration

```python
# DockerManager integration pattern
class DockerManager:
    def __init__(self):
        self.compose_cmd = get_compose_command()
        self._validate_docker()
    
    def run_compose_command(self, compose_file, command, **kwargs):
        # Execute Docker Compose with proper environment
```

### Git Integration

```python
# GitManager integration pattern
class GitManager:
    def __init__(self):
        self.project_root = get_project_root()
        self._validate_git_repo()
    
    def create_worktree(self, branch_name: str, worktree_path: Path):
        # Create Git worktree with validation
```

### Environment Integration

```python
# EnvironmentManager integration pattern
class EnvironmentManager:
    def create_worktree_env(self, branch_name: str, worktree_path: Path):
        # Generate environment files with proper configuration
```

## 🧪 Testing Architecture

### Test Structure

```
tests/
├── unit/                    # Unit tests (57 tests)
│   ├── test_docker_manager.py
│   ├── test_git_manager.py
│   ├── test_worktree_manager.py
│   └── ...
├── integration/             # Integration tests
│   ├── test_docker_integration.py
│   ├── test_git_integration.py
│   └── test_simple_integration.py
├── e2e/                     # End-to-end tests
│   └── test_comprehensive_workflow.py
└── conftest.py              # Test configuration
```

### Test Categories

1. **Unit Tests** - Individual component testing
2. **Integration Tests** - Component interaction testing
3. **E2E Tests** - Complete workflow testing
4. **Error Scenario Tests** - Failure condition testing

### Test Coverage

- **57 Unit Tests** - 100% passing
- **Integration Tests** - Docker and Git operations
- **E2E Tests** - Complete worktree lifecycle
- **Error Tests** - Failure scenarios and recovery

## 📊 Performance Architecture

### Resource Management

- **Memory Usage**: ~1GB per worktree
- **Disk Usage**: ~5GB per worktree
- **Startup Time**: ~45 seconds per worktree
- **Volume Copy Time**: ~60 seconds (data dependent)

### Optimization Strategies

1. **Volume Copying**: Efficient Docker volume operations
2. **Container Reuse**: Shared base images
3. **Network Optimization**: External network reuse
4. **Parallel Operations**: Concurrent volume operations where safe

## 🔒 Security Architecture

### Isolation Principles

1. **Volume Isolation**: Each worktree has separate volumes
2. **Network Isolation**: Worktree-specific networks
3. **Container Isolation**: Separate container instances
4. **Environment Isolation**: Branch-specific environment variables

### Security Features

- **Branch Protection**: Protected branches cannot be deleted
- **Volume Access Control**: Worktree-specific volume access
- **Network Segmentation**: Isolated network communication
- **Environment Validation**: Input validation and sanitization

## 🚀 Deployment Architecture

### Production Considerations

1. **Resource Limits**: Memory and disk usage monitoring
2. **Network Security**: Firewall and access control
3. **Backup Strategy**: Volume backup and restore
4. **Monitoring**: Container and volume monitoring

### Scalability

- **Horizontal Scaling**: Multiple worktrees per system
- **Resource Management**: Dynamic resource allocation
- **Volume Management**: Efficient volume operations
- **Network Management**: Optimized network configuration

## 📚 Documentation Architecture

### Documentation Structure

```
dockertree/
├── README.md                 # User guide and quick start
├── ARCHITECTURE.md           # This document
├── design_documents/        # Design and implementation docs
├── documentation/            # Additional documentation
└── tests/                   # Test documentation
```

### Documentation Types

1. **User Documentation** - README.md, usage guides
2. **Architecture Documentation** - This document
3. **Design Documentation** - Implementation plans
4. **Test Documentation** - Test coverage and procedures

## 🔧 Maintenance Architecture

### Code Organization

- **Modular Design** - Clear separation of concerns
- **Dependency Injection** - Loose coupling between components
- **Error Handling** - Comprehensive error management
- **Type Safety** - Full type hints throughout codebase

### Maintenance Patterns

1. **Configuration Management** - Centralized settings
2. **Error Handling** - Graceful degradation
3. **Logging** - Comprehensive logging system
4. **Testing** - Comprehensive test coverage

---

*This architecture document provides the foundation for understanding, extending, and maintaining the dockertree CLI system. For implementation details, see the source code and test files.*

