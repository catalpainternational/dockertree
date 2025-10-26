"""
Package management for dockertree.

This module provides comprehensive environment export/import functionality
to enable sharing complete isolated development environments between team members.
"""

import json
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.settings import get_project_root, get_project_name
from ..core.docker_manager import DockerManager
from ..core.git_manager import GitManager
from ..core.environment_manager import EnvironmentManager
from ..core.worktree_orchestrator import WorktreeOrchestrator
from ..utils.logging import log_info, log_success, log_warning, log_error
from ..utils.checksum import calculate_file_checksum, verify_file_checksum
from ..utils.confirmation import confirm_use_existing_worktree


class PackageManager:
    """Manages environment package export/import operations."""
    
    def __init__(self, project_root: Optional[Path] = None):
        """Initialize package manager.
        
        Args:
            project_root: Project root directory. If None, uses get_project_root().
        """
        self.project_root = project_root or get_project_root()
        self.docker_manager = DockerManager(project_root=self.project_root)
        self.git_manager = GitManager(project_root=self.project_root)
        self.env_manager = EnvironmentManager(project_root=self.project_root)
        self.orchestrator = WorktreeOrchestrator(project_root=self.project_root)
    
    def export_package(self, branch_name: str, output_dir: Path, 
                      include_code: bool = False, compressed: bool = True) -> Dict[str, Any]:
        """Export worktree to package - orchestrates existing managers.
        
        Args:
            branch_name: Name of the branch to export
            output_dir: Directory to save the package
            include_code: Whether to include git archive of code
            compressed: Whether to compress the final package
            
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
            env_success = self._copy_environment_files(worktree_path, temp_package_dir)
            if not env_success:
                return {
                    "success": False,
                    "error": "Failed to copy environment files"
                }
            
            # 5. Backup volumes using existing DockerManager
            volumes_backup_path = temp_package_dir / "volumes" / f"backup_{branch_name}.tar"
            volumes_backup_path.parent.mkdir(exist_ok=True)
            
            log_info(f"Backing up volumes for {branch_name}...")
            backup_file = self.docker_manager.backup_volumes(branch_name, temp_package_dir / "volumes")
            if not backup_file:
                return {
                    "success": False,
                    "error": "Failed to backup volumes"
                }
            
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
            metadata = self._generate_metadata(branch_name, temp_package_dir, include_code)
            
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
                      restore_data: bool = True) -> Dict[str, Any]:
        """Import package to new worktree - uses WorktreeOrchestrator.
        
        Args:
            package_path: Path to the package file
            target_branch: Target branch name (defaults to package branch name)
            restore_data: Whether to restore volume data
            
        Returns:
            Dictionary with success status and worktree info
        """
        try:
            # 1. Validate package file
            if not package_path.exists():
                return {
                    "success": False,
                    "error": f"Package file not found: {package_path}"
                }
            
            # 2. Extract package to temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_extract_dir = Path(temp_dir)
                
                if package_path.suffix == '.tar.gz':
                    # Extract compressed package
                    with tarfile.open(package_path, 'r:gz') as tar:
                        tar.extractall(temp_extract_dir)
                else:
                    # Copy uncompressed package
                    shutil.copytree(package_path, temp_extract_dir / package_path.name)
                    temp_extract_dir = temp_extract_dir / package_path.name
                
                # 3. Verify package integrity - look for the package directory
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
                if not self._verify_package_checksums(package_dir, metadata):
                    return {
                        "success": False,
                        "error": "Package integrity check failed"
                    }
                
                # 4. Determine target branch
                if not target_branch:
                    target_branch = metadata.get("branch_name")
                    if not target_branch:
                        return {
                            "success": False,
                            "error": "Could not determine target branch from package"
                        }
                
                # 5. Check if target branch already exists
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
                
                # 6. Create worktree using orchestrator
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
                
                # 7. Restore environment files
                env_success = self._restore_environment_files(package_dir, worktree_path)
                if not env_success:
                    log_warning("Failed to restore some environment files")
                
                # 8. Restore volumes if requested
                if restore_data:
                    volumes_backup = package_dir / "volumes" / f"backup_{metadata['branch_name']}.tar"
                    if volumes_backup.exists():
                        log_info(f"Restoring volumes for {target_branch}...")
                        if not self.docker_manager.restore_volumes(target_branch, volumes_backup):
                            log_warning("Failed to restore volumes")
                    else:
                        log_warning("Volume backup not found in package")
                
                # 9. Extract code archive if present
                code_archive = package_dir / "code" / f"{metadata['branch_name']}.tar.gz"
                if code_archive.exists():
                    log_info(f"Extracting code archive to {worktree_path}...")
                    try:
                        with tarfile.open(code_archive, 'r:gz') as tar:
                            tar.extractall(worktree_path)
                    except Exception as e:
                        log_warning(f"Failed to extract code archive: {e}")
                
                # 10. Get worktree info
                worktree_info = self.orchestrator.get_worktree_info(target_branch)
                
                log_success(f"Package imported successfully to branch '{target_branch}'")
                return {
                    "success": True,
                    "worktree_info": worktree_info.get("data", {}),
                    "metadata": metadata
                }
                
        except Exception as e:
            log_error(f"Error importing package: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
    
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
    
    def _copy_environment_files(self, worktree_path: Path, package_dir: Path) -> bool:
        """Copy environment files to package directory."""
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
            
            return True
            
        except Exception as e:
            log_error(f"Failed to copy environment files: {e}")
            return False
    
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
            
            # Restore docker-compose.dockertree.yml
            compose_file = env_dir / "docker-compose.dockertree.yml"
            if compose_file.exists():
                shutil.copy2(compose_file, worktree_path / "docker-compose.dockertree.yml")
            
            return True
            
        except Exception as e:
            log_error(f"Failed to restore environment files: {e}")
            return False
    
    def _generate_metadata(self, branch_name: str, package_dir: Path, include_code: bool) -> Dict[str, Any]:
        """Generate package metadata with checksums."""
        metadata = {
            "package_version": "1.0",
            "dockertree_version": "0.9.1",
            "created_at": datetime.now().isoformat(),
            "branch_name": branch_name,
            "project_name": get_project_name(),
            "include_code": include_code,
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
