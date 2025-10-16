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

```
User Command → CLI Interface → Command Manager → Core Infrastructure → External Systems
     ↓              ↓              ↓                    ↓                    ↓
  Input         Validation      Business Logic      Docker/Git Ops      Containers/Volumes
     ↓              ↓              ↓                    ↓                    ↓
  Output ←    Error Handling ←   Result Processing ←   Status Check ←    System Response
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
- `copy_volume()` - Copy data between volumes
- `create_worktree_volumes()` - Create branch-specific volumes
- `run_compose_command()` - Execute Docker Compose commands
- `backup_volumes()` / `restore_volumes()` - Volume management

**Dependencies**: Docker daemon, Docker Compose
**External Interactions**: Docker API, volume operations, network management

#### GitManager (`core/git_manager.py`)
**Responsibility**: Git worktree operations and branch management

**Key Methods**:
- `create_worktree()` - Create Git worktree
- `remove_worktree()` - Remove worktree safely
- `list_worktrees()` - List active worktrees
- `delete_branch_safely()` - Safe branch deletion with protection
- `validate_worktree_exists()` - Worktree validation

**Dependencies**: Git repository, worktree support
**External Interactions**: Git commands, file system operations

#### EnvironmentManager (`core/environment_manager.py`)
**Responsibility**: Environment configuration and volume naming

**Key Methods**:
- `create_worktree_env()` - Generate environment files
- `get_worktree_volume_names()` - Volume naming convention
- `get_environment_variables()` - Environment variable management
- `get_domain_name()` - Domain name generation

**Dependencies**: Path utilities, configuration settings
**External Interactions**: File system, environment variables

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

```python
# Pattern: {branch_name}_{volume_type}
feature-auth_postgres_data    # Database data
feature-auth_redis_data       # Cache data
feature-auth_media_files      # User uploads
```

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

## 🔌 Extension Architecture

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

