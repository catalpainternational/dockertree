"""
Package management for dockertree.

This module provides comprehensive environment export/import functionality
to enable sharing complete isolated development environments between team members.
"""

import json
import shutil
import subprocess
import tarfile
import tempfile
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import get_project_root, get_project_name
from ..core.docker_manager import DockerManager
from ..core.git_manager import GitManager
from ..core.environment_manager import EnvironmentManager
from ..core.worktree_orchestrator import WorktreeOrchestrator
from ..utils.logging import log_info, log_success, log_warning, log_error
from ..utils.checksum import calculate_file_checksum, verify_file_checksum
from ..utils.confirmation import confirm_use_existing_worktree
from ..utils.container_selector import resolve_service_dependencies


class PackageManager:
    """Manages environment package export/import operations."""
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialize package manager.
        
        Args:
            project_root: Project root directory. If None, uses get_project_root().
        """
        self.project_root = project_root or get_project_root()
        self.docker_manager = DockerManager(project_root=self.project_root)
        self.git_manager = GitManager(project_root=self.project_root, validate=False)
        self.env_manager = EnvironmentManager(project_root=self.project_root)
        self.orchestrator = WorktreeOrchestrator(project_root=self.project_root)
    
    def _is_in_existing_project(self) -> bool:
        """Check if we're in an existing dockertree project.
        
        Returns:
            True if in existing dockertree project with git repo, False otherwise
        """
        from ..utils.validation import validate_git_repository
        
        # Check for .dockertree directory with config
        dockertree_config = self.project_root / ".dockertree" / "config.yml"
        if not dockertree_config.exists():
            return False
        
        # Check for git repository
        if not validate_git_repository(self.project_root):
            return False
        
        return True
    
    def export_package(self, branch_name: str, output_dir: Path, 
                      include_code: bool = False, compressed: bool = True, skip_volumes: bool = False,
                      container_filter: Optional[List[Dict[str, str]]] = None,
                      exclude_deps: Optional[List[str]] = None) -> Dict[str, Any]:
        """Export worktree to package - orchestrates existing managers.
        
        Args:
            branch_name: Name of the branch to export
            output_dir: Directory to save the package
            include_code: Whether to include git archive of code
            compressed: Whether to compress the final package
            skip_volumes: Whether to skip volume backup (fallback option)
            container_filter: Optional list of dicts with 'worktree' and 'container' keys
                             to filter which containers/volumes to export
            exclude_deps: Optional list of service names to exclude from dependency resolution
            
        Returns:
            Dictionary with success status, package path, and metadata
        """
        try:
            # 1. Validate worktree exists
            if not self.git_manager.validate_worktree_exists(branch_name):
                return {
                    "success": False,
                    "error": f"Worktree for branch '{branch_name}' does not exist"
                }
            
            worktree_path = self.git_manager.find_worktree_path(branch_name)
            if not worktree_path:
                return {
                    "success": False,
                    "error": f"Could not find worktree directory for branch '{branch_name}'"
                }
            
            # 2. Create output directory
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 3. Create temporary package directory
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            package_name = f"{branch_name}_{timestamp}.dockertree-package"
            temp_package_dir = output_dir / package_name
            temp_package_dir.mkdir(exist_ok=True)
            
            # 4. Copy environment files
            env_success = self._copy_environment_files(worktree_path, temp_package_dir, container_filter, exclude_deps)
            if not env_success:
                return {
                    "success": False,
                    "error": "Failed to copy environment files"
                }
            
            # 5. Backup volumes using existing DockerManager (unless skipped)
            backup_file = None
            if not skip_volumes:
                volumes_backup_path = temp_package_dir / "volumes" / f"backup_{branch_name}.tar"
                volumes_backup_path.parent.mkdir(exist_ok=True)
                
                # If container_filter is provided, only backup volumes for selected containers
                if container_filter:
                    log_info(f"Backing up volumes for selected containers in {branch_name}...")
                    # Collect volumes for all selected containers
                    selected_volumes = set()
                    for selection in container_filter:
                        if selection.get('worktree') == branch_name:
                            container_name = selection.get('container')
                            volumes = self.docker_manager.get_volumes_for_service(branch_name, container_name)
                            selected_volumes.update(volumes)
                            log_info(f"  Container '{container_name}': {len(volumes)} volume(s)")
                    
                    if selected_volumes:
                        log_info(f"Backing up {len(selected_volumes)} selected volume(s)...")
                        backup_file = self._backup_selected_volumes(
                            branch_name, 
                            list(selected_volumes), 
                            temp_package_dir / "volumes"
                        )
                    else:
                        log_warning("No volumes found for selected containers")
                        backup_file = None
                else:
                    log_info(f"Backing up all volumes for {branch_name}...")
                    backup_file = self.docker_manager.backup_volumes(branch_name, temp_package_dir / "volumes")
                
                if container_filter and not backup_file:
                    return {
                        "success": False,
                        "error": "Failed to backup selected volumes"
                    }
                elif not container_filter and not backup_file:
                    return {
                        "success": False,
                        "error": "Failed to backup volumes"
                    }
            else:
                log_warning("Skipping volume backup as requested")
            
            # 6. Create git archive if requested
            code_archive_path = None
            if include_code:
                code_archive_path = temp_package_dir / "code" / f"{branch_name}.tar.gz"
                code_archive_path.parent.mkdir(exist_ok=True)
                
                log_info(f"Creating git archive for {branch_name}...")
                if not self.git_manager.create_worktree_archive(branch_name, code_archive_path):
                    return {
                        "success": False,
                        "error": "Failed to create git archive"
                    }
            
            # 7. Generate metadata with checksums
            metadata = self._generate_metadata(
                branch_name, temp_package_dir, include_code, skip_volumes, container_filter
            )
            
            # 8. Compress package if requested
            final_package_path = temp_package_dir
            if compressed:
                final_package_path = output_dir / f"{package_name}.tar.gz"
                log_info(f"Compressing package to {final_package_path}...")
                if not self._compress_package(temp_package_dir, final_package_path):
                    return {
                        "success": False,
                        "error": "Failed to compress package"
                    }
                # Clean up temp directory
                shutil.rmtree(temp_package_dir)
            
            log_success(f"Package exported successfully: {final_package_path}")
            return {
                "success": True,
                "package_path": str(final_package_path),
                "metadata": metadata
            }
            
        except Exception as e:
            log_error(f"Error exporting package: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
    
    def import_package(self, package_path: Path, target_branch: str = None,
                      restore_data: bool = True, standalone: bool = None,
                      target_directory: Path = None, domain: Optional[str] = None,
                      ip: Optional[str] = None, non_interactive: bool = False) -> Dict[str, Any]:
        """Import package with automatic standalone detection.
        
        Args:
            package_path: Path to the package file
            target_branch: Target branch name (for normal mode, defaults to package branch)
            restore_data: Whether to restore volume data
            standalone: Force standalone mode (None = auto-detect)
            target_directory: Target directory for standalone import
            domain: Optional domain override (subdomain.domain.tld) for production/staging
            
        Returns:
            Dictionary with success status and import info
        """
        try:
            # Auto-detect standalone mode if not explicitly set
            if standalone is None:
                standalone = not self._is_in_existing_project()
                if standalone:
                    log_info("No existing dockertree project detected - using standalone mode")
            
            # Validate mutually exclusive domain/ip
            if domain and ip:
                return {
                    "success": False,
                    "error": "Options --domain and --ip are mutually exclusive"
                }

            # Route to appropriate import method
            if standalone:
                return self._standalone_import(package_path, target_directory, restore_data, domain, ip, non_interactive)
            else:
                return self._normal_import(package_path, target_branch, restore_data, domain, ip)
                
        except Exception as e:
            log_error(f"Error importing package: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
    
    def _extract_and_validate_package(self, package_path: Path) -> Tuple[Path, Path, Dict[str, Any]]:
        """Extract package and validate integrity.
        
        Args:
            package_path: Path to the package file
            
        Returns:
            Tuple of (temp_extract_dir, package_dir, metadata)
            
        Raises:
            Exception: If validation fails
        """
        # Validate package file
        if not package_path.exists():
            raise FileNotFoundError(f"Package file not found: {package_path}")
        
        # Create temporary extraction directory
        temp_extract_dir = Path(tempfile.mkdtemp())
        
        # Check if it's a compressed tar.gz file
        is_compressed = package_path.name.endswith('.tar.gz')
        
        if is_compressed:
            # Extract compressed package
            log_info("Extracting compressed package...")
            with tarfile.open(package_path, 'r:gz') as tar:
                tar.extractall(temp_extract_dir)
        else:
            # Copy uncompressed package
            log_info("Copying uncompressed package...")
            shutil.copytree(package_path, temp_extract_dir / package_path.name)
            temp_extract_dir = temp_extract_dir / package_path.name
        
        # Verify package integrity - look for the package directory
        package_dirs = [d for d in temp_extract_dir.iterdir() if d.is_dir() and d.name.endswith('.dockertree-package')]
        if not package_dirs:
            raise ValueError("Invalid package: package directory not found")
        
        package_dir = package_dirs[0]
        metadata_path = package_dir / "metadata.json"
        if not metadata_path.exists():
            raise ValueError("Invalid package: metadata.json not found")
        
        with open(metadata_path) as f:
            metadata = json.load(f)
        
        # Verify checksums
        if not self._verify_package_checksums(package_dir, metadata):
            raise ValueError("Package integrity check failed")
        
        return (temp_extract_dir, package_dir, metadata)
    
    def _normal_import(self, package_path: Path, target_branch: str = None,
                      restore_data: bool = True, domain: Optional[str] = None,
                      ip: Optional[str] = None) -> Dict[str, Any]:
        """Import package to existing project as new worktree.
        
        Args:
            package_path: Path to the package file
            target_branch: Target branch name (defaults to package branch name)
            restore_data: Whether to restore volume data
            domain: Optional domain override (subdomain.domain.tld) for production/staging
            
        Returns:
            Dictionary with success status and worktree info
        """
        # Validate git repository for normal import
        from ..utils.validation import validate_git_repository
        if not validate_git_repository(self.project_root):
            return {
                "success": False,
                "error": "Normal import requires a git repository. Use --standalone for new projects."
            }
        
        temp_extract_dir = None
        try:
            # Extract and validate package
            temp_extract_dir, package_dir, metadata = self._extract_and_validate_package(package_path)
            
            # Determine target branch
            if not target_branch:
                target_branch = metadata.get("branch_name")
                if not target_branch:
                    return {
                        "success": False,
                        "error": "Could not determine target branch from package"
                    }
            
            # Check if target branch already exists
            if self.git_manager.validate_worktree_exists(target_branch):
                # Check if volumes exist for this branch
                from ..config.settings import get_volume_names
                from ..utils.validation import validate_volume_exists
                
                volume_names = get_volume_names(target_branch)
                existing_volumes = [name for name in volume_names.values() 
                                  if validate_volume_exists(name)]
                
                if existing_volumes and restore_data:
                    if not confirm_use_existing_worktree(target_branch):
                        return {
                            "success": False,
                            "error": "Import cancelled by user"
                        }
            
            # Create worktree using orchestrator
            log_info(f"Creating worktree for branch '{target_branch}'...")
            create_result = self.orchestrator.create_worktree(target_branch)
            if not create_result.get("success"):
                return {
                    "success": False,
                    "error": f"Failed to create worktree: {create_result.get('error')}"
                }
            
            worktree_path = self.git_manager.find_worktree_path(target_branch)
            if not worktree_path:
                return {
                    "success": False,
                    "error": "Worktree created but path not found"
                }
            
            # Restore environment files
            env_success = self._restore_environment_files(package_dir, worktree_path)
            if not env_success:
                log_warning("Failed to restore some environment files")
            
            # Apply domain/ip overrides if provided
            if domain:
                log_info(f"Applying domain overrides: {domain}")
                self.env_manager.apply_domain_overrides(worktree_path, domain)
            elif ip:
                log_info(f"Applying IP overrides: {ip}")
                self.env_manager.apply_ip_overrides(worktree_path, ip)
            
            # Restore volumes if requested
            # restore_volumes() handles stopping containers safely before restore
            if restore_data:
                volumes_backup = package_dir / "volumes" / f"backup_{metadata['branch_name']}.tar"
                if volumes_backup.exists():
                    log_info(f"Restoring volumes for {target_branch}...")
                    if not self.docker_manager.restore_volumes(target_branch, volumes_backup):
                        log_warning("Failed to restore volumes")
                else:
                    log_warning("Volume backup not found in package")
            
            # Extract code archive if present
            code_archive = package_dir / "code" / f"{metadata['branch_name']}.tar.gz"
            if code_archive.exists():
                log_info(f"Extracting code archive to {worktree_path}...")
                try:
                    with tarfile.open(code_archive, 'r:gz') as tar:
                        tar.extractall(worktree_path)
                except Exception as e:
                    log_warning(f"Failed to extract code archive: {e}")
            
            # Get worktree info
            worktree_info = self.orchestrator.get_worktree_info(target_branch)
            
            log_success(f"Package imported successfully to branch '{target_branch}'")
            return {
                "success": True,
                "mode": "normal",
                "worktree_info": worktree_info.get("data", {}),
                "metadata": metadata
            }
            
        except Exception as e:
            log_error(f"Error in normal import: {e}")
            return {
                "success": False,
                "error": f"Normal import failed: {str(e)}"
            }
        finally:
            # Clean up temporary directory
            if temp_extract_dir and temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
    
    def _standalone_import(self, package_path: Path, target_directory: Path = None,
                          restore_data: bool = True, domain: Optional[str] = None,
                          ip: Optional[str] = None, non_interactive: bool = False) -> Dict[str, Any]:
        """Import package in standalone mode - creates complete project.
        
        Creates new git repository, extracts code archive, initializes dockertree,
        and restores environment and volumes.
        
        Args:
            package_path: Path to the package file
            target_directory: Target directory for new project
            restore_data: Whether to restore volume data
            domain: Optional domain override (subdomain.domain.tld) for production/staging
            
        Returns:
            Dictionary with success status and project info
        """
        temp_extract_dir = None
        try:
            # Extract and validate package
            temp_extract_dir, package_dir, metadata = self._extract_and_validate_package(package_path)
            
            # Check if package includes code (required for standalone)
            if not metadata.get("include_code"):
                return {
                    "success": False,
                    "error": "Standalone import requires package with code (export with --include-code)"
                }
            
            # Determine target directory
            if not target_directory:
                project_name = metadata.get("project_name", "dockertree-project")
                target_directory = Path.cwd() / project_name
            
            target_directory = Path(target_directory).resolve()
            
            # Create target directory
            if target_directory.exists():
                return {
                    "success": False,
                    "error": f"Target directory already exists: {target_directory}"
                }
            
            target_directory.mkdir(parents=True, exist_ok=True)
            
            # Initialize git repository
            log_info(f"Initializing git repository in {target_directory}")
            subprocess.run(["git", "init"], cwd=target_directory, check=True, capture_output=True)
            
            # Extract code archive
            code_archive = package_dir / "code" / f"{metadata['branch_name']}.tar.gz"
            if code_archive.exists():
                log_info("Extracting code archive...")
                with tarfile.open(code_archive, 'r:gz') as tar:
                    tar.extractall(target_directory)
            
            # Commit initial code
            subprocess.run(["git", "add", "."], cwd=target_directory, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"Initial import from package: {metadata['branch_name']}"],
                cwd=target_directory, check=True, capture_output=True
            )
            
            # Initialize dockertree setup
            log_info("Initializing dockertree configuration...")
            original_project_name = metadata.get("project_name")
            from ..commands.setup import SetupManager
            setup_manager = SetupManager(project_root=target_directory)
            if not setup_manager.setup_project(project_name=original_project_name, domain=domain, ip=ip, non_interactive=non_interactive):
                return {
                    "success": False,
                    "error": "Failed to initialize dockertree setup"
                }
            
            # Restore environment files
            self._restore_environment_files(package_dir, target_directory)
            
            # Create worktree for the imported branch
            branch_name = metadata.get("branch_name")
            if branch_name:
                log_info(f"Creating worktree for branch '{branch_name}'...")
                orchestrator = WorktreeOrchestrator(project_root=target_directory)
                create_result = orchestrator.create_worktree(branch_name)
                if not create_result.get("success"):
                    log_warning(f"Failed to create worktree for branch '{branch_name}': {create_result.get('error')}")
                else:
                    log_success(f"Created worktree for branch '{branch_name}'")
                    
                    # Apply domain overrides to worktree if provided
                    if domain or ip:
                        worktree_path = Path(target_directory) / "worktrees" / branch_name
                        if worktree_path.exists():
                            env_manager = EnvironmentManager(project_root=target_directory)
                            if domain:
                                log_info(f"Applying domain overrides to worktree: {domain}")
                                env_manager.apply_domain_overrides(worktree_path, domain)
                            elif ip:
                                log_info(f"Applying IP overrides to worktree: {ip}")
                                env_manager.apply_ip_overrides(worktree_path, ip)
            
            # Restore volumes if requested
            # IMPORTANT: Stop any running containers first to ensure volumes can be restored safely.
            # Volume restoration works at the file level (extracting tar.gz directly into volumes),
            # but we must stop containers first because:
            # 1. PostgreSQL locks database files while running - overwriting them causes corruption
            # 2. Database containers expect clean shutdowns - file-level restoration requires unmounted volumes
            # 3. The restoration process extracts files directly into the volume (no database commands needed)
            if restore_data:
                if branch_name:
                    volumes_backup = package_dir / "volumes" / f"backup_{branch_name}.tar"
                    if volumes_backup.exists():
                        log_info(f"Restoring volumes...")
                        # Ensure containers are stopped before restoration (DRY: use shared function)
                        from ..core.docker_manager import DockerManager
                        docker_manager = DockerManager(project_root=target_directory)
                        # restore_volumes() handles stopping containers safely before restore
                        docker_manager.restore_volumes(branch_name, volumes_backup)
            
            log_success(f"Standalone import completed: {target_directory}")
            return {
                "success": True,
                "mode": "standalone",
                "project_directory": str(target_directory),
                "branch_name": metadata.get("branch_name"),
                "metadata": metadata
            }
            
        except Exception as e:
            log_error(f"Error in standalone import: {e}")
            return {
                "success": False,
                "error": f"Standalone import failed: {str(e)}"
            }
        finally:
            # Clean up temporary directory
            if temp_extract_dir and temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
    
    def validate_package(self, package_path: Path) -> Dict[str, Any]:
        """Validate package integrity.
        
        Args:
            package_path: Path to the package file
            
        Returns:
            Dictionary with validation results
        """
        try:
            if not package_path.exists():
                return {
                    "success": False,
                    "error": "Package file not found"
                }
            
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_extract_dir = Path(temp_dir)
                
                # Extract package
                if package_path.suffix == '.tar.gz':
                    with tarfile.open(package_path, 'r:gz') as tar:
                        tar.extractall(temp_extract_dir)
                else:
                    shutil.copytree(package_path, temp_extract_dir / package_path.name)
                    temp_extract_dir = temp_extract_dir / package_path.name
                
                # Check metadata - look for the package directory
                package_dirs = [d for d in temp_extract_dir.iterdir() if d.is_dir() and d.name.endswith('.dockertree-package')]
                if not package_dirs:
                    return {
                        "success": False,
                        "error": "Invalid package: package directory not found"
                    }
                
                package_dir = package_dirs[0]
                metadata_path = package_dir / "metadata.json"
                if not metadata_path.exists():
                    return {
                        "success": False,
                        "error": "Invalid package: metadata.json not found"
                    }
                
                with open(metadata_path) as f:
                    metadata = json.load(f)
                
                # Verify checksums
                checksum_valid = self._verify_package_checksums(package_dir, metadata)
                
                return {
                    "success": True,
                    "valid": checksum_valid,
                    "metadata": metadata,
                    "checksum_valid": checksum_valid
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Validation error: {str(e)}"
            }
    
    def list_packages(self, package_dir: Path) -> List[Dict[str, Any]]:
        """List available packages in directory.
        
        Args:
            package_dir: Directory to search for packages
            
        Returns:
            List of package information dictionaries
        """
        packages = []
        
        if not package_dir.exists():
            return packages
        
        for item in package_dir.iterdir():
            if item.is_file() and ('.tar.gz' in item.name or item.name.endswith('.dockertree-package')):
                # Validate package
                validation = self.validate_package(item)
                if validation.get("success"):
                    packages.append({
                        "name": item.name,
                        "path": str(item),
                        "size": item.stat().st_size,
                        "metadata": validation.get("metadata", {}),
                        "valid": validation.get("valid", False)
                    })
        
        return sorted(packages, key=lambda x: x["name"])
    
    def _copy_environment_files(self, worktree_path: Path, package_dir: Path, 
                                container_filter: Optional[List[Dict[str, str]]] = None,
                                exclude_deps: Optional[List[str]] = None) -> bool:
        """Copy environment files to package directory.
        
        Args:
            worktree_path: Path to worktree directory
            package_dir: Path to package directory
            container_filter: Optional list of dicts with 'worktree' and 'container' keys
                             to filter which services to include in compose file
        """
        try:
            env_dir = package_dir / "environment"
            env_dir.mkdir(exist_ok=True)
            
            # Copy .env file
            env_file = worktree_path / ".env"
            if env_file.exists():
                shutil.copy2(env_file, env_dir / ".env")
            
            # Copy .dockertree directory
            dockertree_dir = worktree_path / ".dockertree"
            if dockertree_dir.exists():
                shutil.copytree(dockertree_dir, env_dir / ".dockertree")
            
            # Copy docker-compose.dockertree.yml
            compose_file = worktree_path / "docker-compose.dockertree.yml"
            if compose_file.exists():
                shutil.copy2(compose_file, env_dir / "docker-compose.dockertree.yml")
            
            # If container_filter is provided, create filtered compose file
            if container_filter:
                worktree_compose_file = worktree_path / ".dockertree" / "docker-compose.worktree.yml"
                if worktree_compose_file.exists():
                    # Extract exclude_deps from container_filter if present
                    exclude_deps = None
                    for selection in container_filter:
                        if 'exclude_deps' in selection:
                            exclude_deps = selection.get('exclude_deps')
                            break
                    
                    filtered_compose = self._filter_compose_services(
                        worktree_compose_file, container_filter, worktree_path, exclude_deps
                    )
                    if filtered_compose:
                        filtered_path = env_dir / ".dockertree" / "docker-compose.worktree.filtered.yml"
                        filtered_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(filtered_path, 'w') as f:
                            yaml.dump(filtered_compose, f, default_flow_style=False, sort_keys=False)
                        log_info(f"Created filtered compose file with {len(filtered_compose.get('services', {}))} service(s)")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to copy environment files: {e}")
            return False
    
    def _filter_compose_services(self, compose_file: Path, 
                                 container_filter: List[Dict[str, str]],
                                 worktree_path: Path,
                                 exclude_deps: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Filter compose file to include only selected services and their dependencies.
        
        Args:
            compose_file: Path to the compose file to filter
            container_filter: List of dicts with 'worktree' and 'container' keys
            worktree_path: Path to worktree directory (for finding branch name)
            exclude_deps: Optional list of service names to exclude from dependency resolution
            
        Returns:
            Filtered compose data dict, or None if filtering fails
        """
        try:
            # Load compose file
            with open(compose_file) as f:
                compose_data = yaml.safe_load(f) or {}
            
            services = compose_data.get('services', {})
            if not services:
                log_warning("No services found in compose file")
                return None
            
            # Get branch name from worktree path
            branch_name = worktree_path.name
            
            # Extract service names from container_filter for this branch
            selected_services = []
            for selection in container_filter:
                if selection.get('worktree') == branch_name:
                    service_name = selection.get('container')
                    if service_name and service_name in services:
                        selected_services.append(service_name)
            
            if not selected_services:
                log_warning(f"No matching services found in container filter for branch {branch_name}")
                return None
            
            log_info(f"Filtering compose file to include services: {', '.join(selected_services)}")
            if exclude_deps:
                log_info(f"Excluding services from dependencies: {', '.join(exclude_deps)}")
            
            # Resolve dependencies
            services_to_include = resolve_service_dependencies(compose_data, selected_services, exclude_deps)
            log_info(f"Including services with dependencies: {', '.join(services_to_include)}")
            
            # Create filtered compose data
            filtered_compose = {
                'version': compose_data.get('version'),
                'services': {},
                'networks': compose_data.get('networks', {}),
                'volumes': {}
            }
            
            # Copy selected services and remove depends_on for excluded services
            exclude_set = set(exclude_deps or [])
            for service_name in services_to_include:
                if service_name in services:
                    service_config = services[service_name].copy()
                    
                    # Remove depends_on entries for excluded services
                    if 'depends_on' in service_config:
                        depends_on = service_config['depends_on']
                        if isinstance(depends_on, list):
                            # Filter out excluded services
                            filtered_deps = []
                            for dep in depends_on:
                                if isinstance(dep, str):
                                    if dep not in exclude_set:
                                        filtered_deps.append(dep)
                                elif isinstance(dep, dict):
                                    # Handle dict format: {service: {condition: ...}}
                                    dep_name = dep.get('service') or (list(dep.keys())[0] if dep else None)
                                    if dep_name and dep_name not in exclude_set:
                                        filtered_deps.append(dep)
                                else:
                                    filtered_deps.append(dep)
                            
                            if filtered_deps:
                                service_config['depends_on'] = filtered_deps
                            else:
                                # Remove depends_on if all dependencies are excluded
                                del service_config['depends_on']
                        elif isinstance(depends_on, dict):
                            # Filter out excluded services from dict
                            filtered_deps = {k: v for k, v in depends_on.items() if k not in exclude_set}
                            if filtered_deps:
                                service_config['depends_on'] = filtered_deps
                            else:
                                del service_config['depends_on']
                    
                    filtered_compose['services'][service_name] = service_config
            
            # Filter volumes to only include those used by selected services
            selected_volumes = set()
            for service_name, service_config in filtered_compose['services'].items():
                # Check volumes in service
                volumes = service_config.get('volumes', [])
                for volume in volumes:
                    if isinstance(volume, str):
                        # Parse volume string (e.g., "volume_name:/path" or "volume_name")
                        parts = volume.split(':')
                        if parts[0] and not parts[0].startswith('.') and not parts[0].startswith('/'):
                            selected_volumes.add(parts[0])
                    elif isinstance(volume, dict):
                        # Handle named volumes
                        if 'source' in volume or 'volume' in volume:
                            vol_name = volume.get('source') or volume.get('volume')
                            if vol_name and not vol_name.startswith('.') and not vol_name.startswith('/'):
                                selected_volumes.add(vol_name)
            
            # Copy only selected volumes
            all_volumes = compose_data.get('volumes', {})
            for vol_name in selected_volumes:
                if vol_name in all_volumes:
                    filtered_compose['volumes'][vol_name] = all_volumes[vol_name]
            
            return filtered_compose
            
        except Exception as e:
            log_error(f"Failed to filter compose services: {e}")
            return None
    
    def _restore_environment_files(self, package_dir: Path, worktree_path: Path) -> bool:
        """Restore environment files from package to worktree."""
        try:
            env_dir = package_dir / "environment"
            if not env_dir.exists():
                return False
            
            # Restore .env file
            env_file = env_dir / ".env"
            if env_file.exists():
                shutil.copy2(env_file, worktree_path / ".env")
            
            # Restore .dockertree directory
            dockertree_src = env_dir / ".dockertree"
            dockertree_dst = worktree_path / ".dockertree"
            if dockertree_src.exists():
                if dockertree_dst.exists():
                    shutil.rmtree(dockertree_dst)
                shutil.copytree(dockertree_src, dockertree_dst)
            
            # Check for filtered compose file and use it if available
            filtered_compose_file = dockertree_dst / "docker-compose.worktree.filtered.yml"
            worktree_compose_file = dockertree_dst / "docker-compose.worktree.yml"
            if filtered_compose_file.exists():
                log_info("Found filtered compose file in package, using it as worktree compose file")
                # Load filtered compose to get service count
                with open(filtered_compose_file) as f:
                    filtered_data = yaml.safe_load(f) or {}
                service_count = len(filtered_data.get('services', {}))
                # Replace the worktree compose file with the filtered one
                if worktree_compose_file.exists():
                    worktree_compose_file.unlink()
                shutil.copy2(filtered_compose_file, worktree_compose_file)
                log_info(f"Restored filtered compose file with {service_count} service(s)")
            
            # Restore docker-compose.dockertree.yml
            compose_file = env_dir / "docker-compose.dockertree.yml"
            if compose_file.exists():
                shutil.copy2(compose_file, worktree_path / "docker-compose.dockertree.yml")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to restore environment files: {e}")
            return False
    
    def _backup_selected_volumes(self, branch_name: str, volume_names: List[str], backup_dir: Path) -> Optional[Path]:
        """Backup only selected volumes to a tar file.
        
        Args:
            branch_name: Branch name for the worktree
            volume_names: List of volume names to backup
            backup_dir: Directory to save the backup
            
        Returns:
            Path to backup file if successful, None otherwise
        """
        import tempfile
        backup_file = backup_dir / f"backup_{branch_name}.tar"
        
        log_info(f"Backing up {len(volume_names)} selected volume(s) for {branch_name} to {backup_file}")
        
        # Check if worktree is running before backup
        was_running = self.docker_manager._is_worktree_running(branch_name)
        if was_running:
            log_info(f"Worktree containers are running, stopping them safely before backup...")
            from ..core.worktree_orchestrator import WorktreeOrchestrator
            orchestrator = WorktreeOrchestrator(project_root=self.project_root)
            stop_result = orchestrator.stop_worktree(branch_name)
            if not stop_result.get("success"):
                log_warning("Failed to stop containers, but continuing with backup")
            else:
                log_success("Containers stopped successfully")
        
        # Create backup directory
        backup_dir.mkdir(parents=True, exist_ok=True)
        temp_backup_dir = backup_dir / "temp_backup"
        temp_backup_dir.mkdir(exist_ok=True)
        
        try:
            from ..utils.validation import validate_volume_exists
            
            # Backup each selected volume
            for volume_name in volume_names:
                if not validate_volume_exists(volume_name):
                    log_warning(f"Volume {volume_name} not found, skipping")
                    continue
                
                log_info(f"Backing up volume: {volume_name}")
                
                # Use file-level backup
                volume_backup = temp_backup_dir / f"{volume_name}.tar.gz"
                
                try:
                    subprocess.run([
                        "docker", "run", "--rm",
                        "-v", f"{volume_name}:/data",
                        "-v", f"{temp_backup_dir.absolute()}:/backup",
                        "alpine", "tar", "czf", f"/backup/{volume_name}.tar.gz", "-C", "/data", "."
                    ], check=True, capture_output=True, text=True)
                    log_success(f"Volume backup created: {volume_name}.tar.gz")
                except subprocess.CalledProcessError as e:
                    log_error(f"Failed to backup volume {volume_name}: {e}")
                    if e.stderr:
                        log_error(f"Error details: {e.stderr}")
                    continue
            
            # Create combined backup
            subprocess.run([
                "tar", "czf", str(backup_file), "-C", str(temp_backup_dir), "."
            ], check=True, capture_output=True)
            
            # Cleanup temp directory
            shutil.rmtree(temp_backup_dir)
            
            log_success(f"Backup created: {backup_file}")
            
            # Restart containers if they were running before
            if was_running:
                log_info("Restarting worktree containers in background...")
                from ..core.worktree_orchestrator import WorktreeOrchestrator
                orchestrator = WorktreeOrchestrator(project_root=self.project_root)
                import threading
                
                def start_in_background():
                    start_result = orchestrator.start_worktree(branch_name)
                    if start_result.get("success"):
                        log_success("Containers restarted successfully")
                    else:
                        log_warning(f"Failed to restart containers: {start_result.get('error', 'Unknown error')}")
                
                thread = threading.Thread(target=start_in_background, daemon=True)
                thread.start()
            
            return backup_file
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to create backup: {e}")
            # Cleanup temp directory
            if temp_backup_dir.exists():
                shutil.rmtree(temp_backup_dir)
            
            # Try to restart containers if they were running
            if was_running:
                log_info("Attempting to restart containers after backup failure...")
                try:
                    from ..core.worktree_orchestrator import WorktreeOrchestrator
                    orchestrator = WorktreeOrchestrator(project_root=self.project_root)
                    orchestrator.start_worktree(branch_name)
                except Exception as restart_error:
                    log_error(f"Failed to restart containers: {restart_error}")
            
            return None
    
    def _generate_metadata(self, branch_name: str, package_dir: Path, include_code: bool, 
                          skip_volumes: bool = False, container_filter: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """Generate package metadata with checksums."""
        metadata = {
            "package_version": "1.0",
            "dockertree_version": "0.9.4",
            "created_at": datetime.now().isoformat(),
            "branch_name": branch_name,
            "project_name": get_project_name(),
            "include_code": include_code,
            "skip_volumes": skip_volumes,
            "container_filter": container_filter if container_filter else None,
            "checksums": {}
        }
        
        # Calculate checksums for all files
        for file_path in package_dir.rglob('*'):
            if file_path.is_file():
                try:
                    checksum = calculate_file_checksum(file_path)
                    relative_path = file_path.relative_to(package_dir)
                    metadata["checksums"][str(relative_path)] = checksum
                except Exception:
                    continue
        
        # Save metadata
        metadata_path = package_dir / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return metadata
    
    def _verify_package_checksums(self, package_dir: Path, metadata: Dict[str, Any]) -> bool:
        """Verify package checksums."""
        checksums = metadata.get("checksums", {})
        
        for relative_path, expected_checksum in checksums.items():
            file_path = package_dir / relative_path
            if not file_path.exists():
                log_warning(f"File not found in package: {relative_path}")
                return False
            
            if not verify_file_checksum(file_path, expected_checksum):
                log_warning(f"Checksum mismatch for: {relative_path}")
                return False
        
        return True
    
    def _compress_package(self, source_dir: Path, output_path: Path) -> bool:
        """Compress package directory to tar.gz."""
        try:
            with tarfile.open(output_path, 'w:gz') as tar:
                tar.add(source_dir, arcname=source_dir.name)
            return True
        except Exception as e:
            log_error(f"Failed to compress package: {e}")
            return False
