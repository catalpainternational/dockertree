<!-- aa1142c3-56a0-4fe8-9228-0f0cdb2072d6 371e839e-bdb9-4a06-b092-0a2cb39b303e -->
# Dockertree Environment Package Sharing

## Overview

Add comprehensive environment export/import functionality to enable sharing complete isolated development environments between team members and machines. This includes code snapshots, Docker volumes, environment configuration, and metadata.

## Architecture

### Package Format

A Dockertree package (`.dockertree-package.tar.gz`) will contain:

```
{branch_name}_{timestamp}.dockertree-package/
├── metadata.json              # Package manifest
├── environment/
│   ├── .env                   # Environment variables
│   ├── .dockertree/
│   │   ├── env.dockertree     # Dockertree-specific env
│   │   └── config.yml         # Configuration (if exists)
│   └── docker-compose.dockertree.yml
├── volumes/
│   ├── postgres_data.tar.gz   # Database dump
│   ├── redis_data.tar.gz      # Cache data  
│   └── media_files.tar.gz     # Media files
└── code/ (optional)
    └── {branch_name}/         # Git worktree snapshot
```

### Metadata Format

```json
{
  "package_version": "1.0",
  "dockertree_version": "0.9.1",
  "created_at": "2024-01-15T14:30:00Z",
  "branch_name": "feature-auth",
  "project_name": "myapp",
  "git_commit": "abc123...",
  "include_code": true,
  "volumes": ["postgres_data", "redis_data", "media_files"],
  "checksums": {
    "postgres_data.tar.gz": "sha256:...",
    "redis_data.tar.gz": "sha256:...",
    "media_files.tar.gz": "sha256:..."
  }
}
```

## Implementation

### 1. Core Package Manager (`dockertree/core/package_manager.py`)

New module handling all package operations:

```python
class PackageManager:
    def export_package(self, branch_name: str, options: ExportOptions) -> Dict[str, Any]
    def import_package(self, package_path: Path, target_branch: str, options: ImportOptions) -> Dict[str, Any]
    def validate_package(self, package_path: Path) -> Dict[str, Any]
    def list_packages(self, package_dir: Path) -> List[Dict[str, Any]]
```

Key methods:

- `_create_package_structure()` - Initialize package directory
- `_export_environment()` - Copy environment files
- `_export_volumes()` - Backup Docker volumes
- `_export_code()` - Create git archive of worktree
- `_generate_metadata()` - Create manifest with checksums
- `_compress_package()` - Create .tar.gz archive
- `_extract_package()` - Unpack and verify
- `_import_environment()` - Restore environment files
- `_import_volumes()` - Restore Docker volumes
- `_import_code()` - Extract code to worktree

### 2. CLI Commands (`dockertree/commands/packages.py`)

New command module:

```python
class PackageManager:
    def export(self, branch_name: str, output_dir: Path, include_code: bool, compressed: bool) -> bool
    def import_package(self, package_file: Path, target_branch: str, restore_data: bool) -> bool
    def list_packages(self, package_dir: Path) -> List[Dict]
    def validate(self, package_file: Path) -> bool
```

### 3. CLI Integration (`dockertree/cli.py`)

Add new command group:

```python
@cli.group()
def packages():
    """Manage environment packages."""
    pass

@packages.command('export')
@click.argument('branch_name')
@click.option('--output-dir', type=Path, default='./packages')
@click.option('--include-code/--no-code', default=False)
@click.option('--compressed/--no-compress', default=True)
@add_json_option
def export_package(branch_name, output_dir, include_code, compressed, json):
    """Export worktree environment to shareable package."""
    pass

@packages.command('import')
@click.argument('package_file', type=Path)
@click.option('--target-branch', default=None)
@click.option('--restore-data/--no-data', default=True)
@add_json_option
def import_package(package_file, target_branch, restore_data, json):
    """Import environment from package."""
    pass

@packages.command('list')
@click.option('--package-dir', type=Path, default='./packages')
@add_json_option
def list_packages(package_dir, json):
    """List available packages."""
    pass

@packages.command('validate')
@click.argument('package_file', type=Path)
@add_json_option  
def validate_package(package_file, json):
    """Validate package integrity."""
    pass
```

### 4. MCP Integration

Add to `dockertree_mcp/tools/package_tools.py`:

```python
class PackageTools:
    async def export_package(self, arguments: Dict[str, Any]) -> Dict[str, Any]
    async def import_package(self, arguments: Dict[str, Any]) -> Dict[str, Any]
    async def list_packages(self, arguments: Dict[str, Any]) -> Dict[str, Any]
    async def validate_package(self, arguments: Dict[str, Any]) -> Dict[str, Any]
```

Register in `dockertree_mcp/server.py`:

```python
{
    "name": "export_package",
    "description": "Export a worktree environment to shareable package",
    "inputSchema": {...}
},
{
    "name": "import_package", 
    "description": "Import environment from package",
    "inputSchema": {...}
}
```

### 5. Utilities

Add helper functions to `dockertree/utils/package_utils.py`:

- `calculate_checksum()` - SHA256 hash calculation
- `verify_checksum()` - Checksum validation
- `create_git_archive()` - Git archive of worktree
- `estimate_package_size()` - Size estimation
- `sanitize_package_name()` - Filename sanitization

## Files to Create

1. `dockertree/core/package_manager.py` - Core package operations
2. `dockertree/commands/packages.py` - CLI command implementations
3. `dockertree/utils/package_utils.py` - Package utility functions
4. `dockertree_mcp/tools/package_tools.py` - MCP tool wrappers
5. `docs/commands/packages.md` - Documentation
6. `tests/unit/test_package_manager.py` - Unit tests
7. `tests/integration/test_package_workflow.py` - Integration tests

## Files to Modify

1. `dockertree/cli.py` - Add packages command group and route
2. `dockertree_mcp/server.py` - Register package tools
3. `dockertree/commands/__init__.py` - Export PackageManager
4. `docs/index.md` - Add package management to feature list
5. `README.md` - Add package management examples

## Export Workflow

1. Validate worktree exists
2. Stop worktree containers (if running)
3. Create temporary package directory
4. Export environment files (.env, .dockertree/)
5. Backup volumes using existing `DockerManager.backup_volumes()`
6. Optionally create git archive of code
7. Generate metadata.json with checksums
8. Compress to .tar.gz
9. Cleanup temporary files
10. Restart containers if they were running

## Import Workflow

1. Validate package file exists and is readable
2. Extract package to temporary directory
3. Verify metadata and checksums
4. Check if target branch already exists (prompt for confirmation)
5. Create new worktree with target branch name
6. Import environment files to worktree
7. Restore volumes using existing `DockerManager.restore_volumes()`
8. Optionally restore code from archive
9. Generate worktree-specific config
10. Cleanup temporary files
11. Return worktree info (path, URL, status)

## Error Handling

- Package corruption detection (checksum mismatch)
- Insufficient disk space warnings
- Version compatibility checks
- Existing branch/worktree conflicts
- Volume restore failures with rollback
- Partial import recovery

## Usage Examples

```bash
# Export complete environment with code
dockertree packages export feature-auth --include-code

# Export only data (no code)
dockertree packages export feature-payments --no-code

# List available packages
dockertree packages list

# Validate package
dockertree packages validate myapp-feature-auth-2024-01-15.dockertree-package.tar.gz

# Import to same branch name
dockertree packages import myapp-feature-auth-2024-01-15.dockertree-package.tar.gz

# Import to different branch
dockertree packages import myapp-feature-auth.dockertree-package.tar.gz --target-branch feature-auth-copy

# Import environment only (create empty volumes)
dockertree packages import package.tar.gz --no-data
```

## Testing Strategy

1. Unit tests for PackageManager methods
2. Integration tests for full export/import cycle
3. Test package validation and corruption detection
4. Test import to existing/new branches
5. Test code inclusion/exclusion options
6. Test cross-machine compatibility (mock different paths)
7. Test error recovery and rollback scenarios

### To-dos

- [ ] Create dockertree/core/package_manager.py with PackageManager class implementing export/import logic
- [ ] Create dockertree/utils/package_utils.py with checksum, archive, and validation utilities
- [ ] Create dockertree/commands/packages.py with CLI command implementations
- [ ] Modify dockertree/cli.py to add packages command group with export, import, list, validate subcommands
- [ ] Create dockertree_mcp/tools/package_tools.py with MCP tool wrappers
- [ ] Modify dockertree_mcp/server.py to register package tools
- [ ] Create tests/unit/test_package_manager.py with unit tests for package operations
- [ ] Create tests/integration/test_package_workflow.py with end-to-end workflow tests
- [ ] Create docs/commands/packages.md with comprehensive package management documentation
- [ ] Update README.md and docs/index.md with package management feature and examples