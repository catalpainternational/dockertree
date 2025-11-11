"""
Docker management for dockertree CLI.

This module provides Docker operations including network creation, volume management,
container lifecycle, and compose file execution.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import (
    CADDY_NETWORK, 
    get_compose_command, 
    get_volume_names,
    DEFAULT_ENV_VARS,
    get_project_root
)
from ..utils.logging import log_info, log_success, log_warning, log_error, show_progress
from ..utils.validation import (
    validate_docker_running, validate_network_exists, validate_volume_exists,
    get_containers_using_volume, are_containers_running, get_postgres_container_for_volume
)


class DockerManager:
    """Manages Docker operations for dockertree CLI."""
    
    def __init__(self, project_root: Optional[Path] = None, validate: bool = True):
        """Initialize Docker manager.
        
        Args:
            project_root: Project root directory. If None, uses get_project_root().
            validate: If True, raise exception if Docker not running. If False, just log warning.
        """
        # Use the provided project_root directly, don't fall back to get_project_root()
        # This ensures MCP server uses the correct working directory
        if project_root is None:
            self.project_root = get_project_root()
        else:
            self.project_root = Path(project_root).resolve()
        self.compose_cmd = get_compose_command()
        if validate:
            self._validate_docker()
        else:
            # Just check without raising
            if not validate_docker_running():
                log_warning("Docker is not running. Some operations may fail.")
    
    def _validate_docker(self) -> None:
        """Validate Docker is running."""
        if not validate_docker_running():
            raise RuntimeError("Docker is not running. Please start Docker and try again.")
    
    def create_network(self, network_name: str = CADDY_NETWORK) -> bool:
        """Create external network if it doesn't exist."""
        if validate_network_exists(network_name):
            log_info(f"Network {network_name} already exists")
            return True
        
        log_info(f"Creating external network: {network_name}")
        try:
            subprocess.run(
                ["docker", "network", "create", network_name],
                check=True,
                capture_output=True
            )
            log_success(f"Network {network_name} created")
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to create network {network_name}: {e}")
            return False
        except Exception as e:
            log_error(f"Failed to create network {network_name}: {e}")
            return False
    
    def copy_volume(self, source_volume: str, target_volume: str, source_project_name: str = None) -> bool:
        """Copy volume data from source to target with safe PostgreSQL handling."""
        log_info(f"Copying volume {source_volume} to {target_volume}...")
        
        # Check if source volume exists
        if not validate_volume_exists(source_volume):
            log_warning(f"Source volume {source_volume} does not exist, creating empty target volume")
            return self._create_volume(target_volume)
        
        # Create target volume if it doesn't exist
        if not self._create_volume(target_volume):
            return False
        
        # Detect if this is a PostgreSQL volume and handle safely
        if self._is_postgres_volume(source_volume) and source_project_name:
            return self.copy_postgres_volume_safely(source_volume, target_volume, source_project_name)
        
        # For non-PostgreSQL volumes (redis, media), use the existing fast copy method
        try:
            subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{source_volume}:/source:ro",
                "-v", f"{target_volume}:/dest",
                "alpine", "sh", "-c", "cp -r /source/* /dest/ 2>/dev/null || true"
            ], check=True, capture_output=True)
            log_success(f"Volume copy completed: {source_volume} -> {target_volume}")
            return True
        except subprocess.CalledProcessError:
            log_warning("Volume copy had issues, but continuing with empty volume")
            return True
    
    def _is_postgres_volume(self, volume_name: str) -> bool:
        """Check if a volume is a PostgreSQL data volume."""
        return 'postgres' in volume_name.lower() and 'data' in volume_name.lower()
    
    def copy_postgres_volume_safely(self, source_volume: str, target_volume: str, source_project_name: str) -> bool:
        """Safely copy PostgreSQL volume using pg_dump when database is running."""
        log_info("Detecting source database status...")
        
        # Find the PostgreSQL container using this volume
        postgres_container = get_postgres_container_for_volume(source_volume, source_project_name)
        
        if postgres_container and validate_container_running(postgres_container):
            log_info("Source database is running, creating consistent snapshot using pg_dump...")
            return self._copy_postgres_with_dump(source_volume, target_volume, postgres_container)
        else:
            log_info("Source database is stopped, using fast file copy...")
            return self._copy_postgres_files(source_volume, target_volume)
    
    def _copy_postgres_with_dump(self, source_volume: str, target_volume: str, postgres_container: str) -> bool:
        """Copy PostgreSQL data using pg_dump for consistency."""
        import tempfile
        import os
        
        try:
            # Create temporary backup file
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.sql', delete=False) as backup_file:
                backup_path = backup_file.name
            
            # Export database using pg_dumpall from the running container
            log_info("Creating database backup...")
            export_cmd = [
                "docker", "exec", postgres_container,
                "pg_dumpall", "-U", "postgres", "-c"
            ]
            
            with open(backup_path, 'w') as f:
                result = subprocess.run(export_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
                if result.returncode != 0:
                    log_error(f"pg_dumpall failed: {result.stderr}")
                    return False
            
            # Create target volume and restore data
            log_info("Restoring database to new volume...")
            restore_cmd = [
                "docker", "run", "--rm",
                "-v", f"{target_volume}:/var/lib/postgresql/data",
                "-v", f"{backup_path}:/backup.sql",
                "postgres:latest",
                "sh", "-c", """
                    # Initialize database
                    initdb -D /var/lib/postgresql/data
                    # Start postgres in background
                    postgres -D /var/lib/postgresql/data &
                    PG_PID=$!
                    # Wait for postgres to start
                    sleep 3
                    # Restore data
                    psql -U postgres -f /backup.sql
                    # Stop postgres
                    kill $PG_PID
                    wait $PG_PID
                """
            ]
            
            result = subprocess.run(restore_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log_error(f"Database restore failed: {result.stderr}")
                return False
            
            log_success("Database snapshot complete, safe to start worktree")
            return True
            
        except Exception as e:
            log_error(f"Failed to copy PostgreSQL volume safely: {e}")
            return False
        finally:
            # Clean up backup file
            if 'backup_path' in locals() and os.path.exists(backup_path):
                os.unlink(backup_path)
    
    def _copy_postgres_files(self, source_volume: str, target_volume: str) -> bool:
        """Copy PostgreSQL files directly (safe when database is stopped)."""
        try:
            subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{source_volume}:/source:ro",
                "-v", f"{target_volume}:/dest",
                "alpine", "sh", "-c", "cp -r /source/* /dest/ 2>/dev/null || true"
            ], check=True, capture_output=True)
            log_success("Database files copied successfully")
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to copy PostgreSQL files: {e}")
            return False
    
    def _create_volume(self, volume_name: str) -> bool:
        """Create a Docker volume."""
        try:
            subprocess.run(
                ["docker", "volume", "create", volume_name],
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to create volume {volume_name}: {e}")
            return False
    
    def create_worktree_volumes(self, branch_name: str, project_name: str = None, force_copy: bool = False) -> bool:
        """Create worktree-specific volumes, copying only if needed.
        
        Note: Only creates postgres, redis, and media volumes. Caddy volumes 
        are shared globally across all worktrees and should not be copied.
        """
        volume_names = get_volume_names(branch_name)
        
        # Use project name from config if not provided
        if project_name is None:
            from ..config.settings import get_project_name
            project_name = get_project_name()
        
        project_volumes = {
            "postgres": f"{project_name}_{volume_names['postgres'].split('_', 1)[1]}",
            "redis": f"{project_name}_{volume_names['redis'].split('_', 1)[1]}",
            "media": f"{project_name}_{volume_names['media'].split('_', 1)[1]}",
        }
        
        # Check if all volumes already exist
        all_volumes_exist = all(validate_volume_exists(vol_name) for vol_name in volume_names.values())
        
        if all_volumes_exist and not force_copy:
            log_info(f"Worktree volumes already exist for {branch_name}, skipping copy")
            return True
        
        # Determine appropriate log message
        if all_volumes_exist and force_copy:
            log_info(f"Recreating worktree-specific volumes for {branch_name}")
        else:
            log_info(f"Creating worktree-specific volumes for {branch_name}")
        
        # Add database-specific logging
        if 'postgres' in project_volumes:
            log_info("PostgreSQL volumes will be copied safely to prevent database corruption")
        
        success = True
        for volume_type, source_volume in project_volumes.items():
            target_volume = volume_names[volume_type]
            if not self.copy_volume(source_volume, target_volume, project_name):
                success = False
        
        if success:
            log_success(f"Worktree volumes created for {branch_name}")
        return success
    
    def remove_volumes(self, branch_name: str) -> bool:
        """Remove worktree-specific volumes.
        
        Note: Only removes postgres, redis, and media volumes. Caddy volumes 
        are shared globally across all worktrees and should never be deleted 
        during worktree removal.
        """
        log_info(f"Removing worktree-specific volumes for {branch_name}")
        
        volume_names = get_volume_names(branch_name)
        success = True
        
        for volume_type, volume_name in volume_names.items():
            if validate_volume_exists(volume_name):
                try:
                    subprocess.run(
                        ["docker", "volume", "rm", volume_name],
                        check=True,
                        capture_output=True
                    )
                    log_info(f"Removed volume: {volume_name}")
                except subprocess.CalledProcessError:
                    log_warning(f"Failed to remove volume {volume_name}")
                    success = False
            else:
                log_warning(f"Volume {volume_name} not found")
        
        return success
    
    def backup_volumes(self, branch_name: str, backup_dir: Path) -> Optional[Path]:
        """Backup worktree volumes to a tar file."""
        backup_file = backup_dir / f"backup_{branch_name}.tar"
        volume_names = get_volume_names(branch_name)
        
        log_info(f"Backing up volumes for {branch_name} to {backup_file}")
        
        # Create backup directory
        backup_dir.mkdir(parents=True, exist_ok=True)
        temp_backup_dir = backup_dir / "temp_backup"
        temp_backup_dir.mkdir(exist_ok=True)
        
        try:
            # Backup each volume
            for volume_type, volume_name in volume_names.items():
                if validate_volume_exists(volume_name):
                    log_info(f"Backing up volume: {volume_name}")
                    volume_backup = temp_backup_dir / f"{volume_name}.tar.gz"
                    
                    subprocess.run([
                        "docker", "run", "--rm",
                        "-v", f"{volume_name}:/data",
                        "-v", f"{temp_backup_dir.absolute()}:/backup",
                        "alpine", "tar", "czf", f"/backup/{volume_name}.tar.gz", "-C", "/data", "."
                    ], check=True, capture_output=True)
                else:
                    log_warning(f"Volume {volume_name} not found, skipping")
            
            # Create combined backup
            subprocess.run([
                "tar", "czf", str(backup_file), "-C", str(temp_backup_dir), "."
            ], check=True, capture_output=True)
            
            # Cleanup temp directory
            shutil.rmtree(temp_backup_dir)
            
            log_success(f"Backup created: {backup_file}")
            return backup_file
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to create backup: {e}")
            # Cleanup temp directory
            if temp_backup_dir.exists():
                shutil.rmtree(temp_backup_dir)
            return None
    
    def restore_volumes(self, branch_name: str, backup_file: Path) -> bool:
        """Restore worktree volumes from a backup file with enhanced logging."""
        if not backup_file.exists():
            log_error(f"Backup file {backup_file} not found")
            return False
        
        backup_size = backup_file.stat().st_size / (1024 * 1024)  # Size in MB
        log_info(f"Restoring volumes for {branch_name} from {backup_file} ({backup_size:.2f} MB)")
        
        volume_names = get_volume_names(branch_name)
        restore_temp_dir = backup_file.parent / "restore_temp"
        
        try:
            # Extract backup
            log_info(f"Extracting backup archive to temporary directory...")
            restore_temp_dir.mkdir(exist_ok=True)
            extract_result = subprocess.run([
                "tar", "xzf", str(backup_file), "-C", str(restore_temp_dir)
            ], check=True, capture_output=True, text=True)
            
            if extract_result.stderr:
                log_info(f"Extraction output: {extract_result.stderr}")
            
            log_success("Backup archive extracted successfully")
            
            # List available backups
            available_backups = list(restore_temp_dir.glob("*.tar.gz"))
            log_info(f"Found {len(available_backups)} volume backup(s) in archive")
            for backup in available_backups:
                backup_size_mb = backup.stat().st_size / (1024 * 1024)
                log_info(f"  - {backup.name} ({backup_size_mb:.2f} MB)")
            
            # Create mapping of backup files to volume types
            # Backup files may have different project names, so we need to match by volume type suffix
            # Volume types map to suffixes: postgres -> postgres_data, redis -> redis_data, media -> media_files
            volume_type_suffixes = {
                "postgres": "postgres_data",
                "redis": "redis_data", 
                "media": "media_files"
            }
            backup_map = {}
            for backup_file in available_backups:
                backup_name = backup_file.stem  # Remove .tar.gz
                for volume_type, volume_name in volume_names.items():
                    # Check if this backup matches the expected volume type by suffix
                    expected_suffix = f"_{volume_type_suffixes.get(volume_type, volume_type)}"
                    if backup_name.endswith(expected_suffix):
                        if volume_type not in backup_map:
                            backup_map[volume_type] = backup_file
                            log_info(f"Mapped backup {backup_file.name} to volume type {volume_type} (expected suffix: {expected_suffix})")
                            break
            
            # Restore each volume
            restored_count = 0
            skipped_count = 0
            failed_count = 0
            
            for volume_type, volume_name in volume_names.items():
                # Try exact match first
                volume_backup = restore_temp_dir / f"{volume_name}.tar.gz"
                
                # If exact match doesn't exist, try mapped backup
                if not volume_backup.exists() and volume_type in backup_map:
                    volume_backup = backup_map[volume_type]
                    log_info(f"Using mapped backup file: {volume_backup.name} for volume {volume_name}")
                
                if volume_backup.exists():
                    backup_size_mb = volume_backup.stat().st_size / (1024 * 1024)
                    log_info(f"Restoring volume: {volume_name} ({volume_type}, {backup_size_mb:.2f} MB)")
                    
                    # Check if volume already exists
                    if validate_volume_exists(volume_name):
                        # Check if volume is empty (less than 10KB)
                        try:
                            vol_size_check = subprocess.run([
                                "docker", "run", "--rm",
                                "-v", f"{volume_name}:/data",
                                "alpine", "sh", "-c", "du -sb /data 2>/dev/null | cut -f1 || echo 0"
                            ], check=False, capture_output=True, text=True, timeout=5)
                            vol_size_bytes = int(vol_size_check.stdout.strip() or "0")
                            
                            if vol_size_bytes < 10000:  # Less than 10KB is likely empty
                                log_warning(f"Volume {volume_name} exists but appears empty ({vol_size_bytes} bytes)")
                                log_info("Removing empty volume to allow restoration...")
                                containers = get_containers_using_volume(volume_name)
                                if containers:
                                    log_warning(f"Volume {volume_name} is in use by containers: {', '.join(containers)}")
                                    log_warning("Stopping containers to allow volume removal...")
                                    # Try to stop containers using this volume
                                    for container in containers:
                                        try:
                                            subprocess.run(["docker", "stop", container], 
                                                          check=False, capture_output=True, timeout=10)
                                            log_info(f"Stopped container: {container}")
                                        except Exception as e:
                                            log_warning(f"Could not stop container {container}: {e}")
                                    
                                    # Re-check if volume is still in use
                                    containers = get_containers_using_volume(volume_name)
                                    if containers:
                                        log_warning(f"Volume {volume_name} still in use, skipping restoration")
                                        skipped_count += 1
                                        continue
                                
                                # Remove empty volume
                                try:
                                    subprocess.run(["docker", "volume", "rm", volume_name], 
                                                  check=True, capture_output=True, timeout=10)
                                    log_success(f"Removed empty volume: {volume_name}")
                                except subprocess.CalledProcessError as e:
                                    log_error(f"Failed to remove volume {volume_name}: {e}")
                                    if e.stderr:
                                        log_error(f"Error: {e.stderr}")
                                    skipped_count += 1
                                    continue
                            else:
                                log_warning(f"Volume {volume_name} already exists with data ({vol_size_bytes} bytes)")
                                # Still try to restore if user wants, but warn
                                containers = get_containers_using_volume(volume_name)
                                if containers:
                                    log_warning(f"Volume {volume_name} is in use by containers: {', '.join(containers)}")
                                    log_warning("Skipping restoration of this volume")
                                    skipped_count += 1
                                    continue
                        except Exception as e:
                            log_warning(f"Could not check volume size: {e}, proceeding with restoration")
                    
                    # Create volume
                    log_info(f"Creating volume: {volume_name}")
                    if not self._create_volume(volume_name):
                        log_error(f"Failed to create volume: {volume_name}")
                        failed_count += 1
                        continue
                    log_success(f"Volume created: {volume_name}")
                    
                    # Restore data
                    log_info(f"Restoring data to volume {volume_name}...")
                    restore_result = subprocess.run([
                        "docker", "run", "--rm",
                        "-v", f"{volume_name}:/data",
                        "-v", f"{restore_temp_dir.absolute()}:/backup",
                        "alpine", "tar", "xzf", f"/backup/{volume_name}.tar.gz", "-C", "/data"
                    ], check=True, capture_output=True, text=True)
                    
                    if restore_result.stderr:
                        # tar may output warnings to stderr that are not errors
                        if "Removing leading" in restore_result.stderr:
                            log_info(f"tar output: {restore_result.stderr.strip()}")
                    
                    # Verify volume has data
                    try:
                        verify_result = subprocess.run([
                            "docker", "run", "--rm",
                            "-v", f"{volume_name}:/data",
                            "alpine", "sh", "-c", "du -sh /data | cut -f1"
                        ], check=True, capture_output=True, text=True, timeout=10)
                        volume_data_size = verify_result.stdout.strip()
                        log_success(f"Volume {volume_name} restored successfully (data size: {volume_data_size})")
                        restored_count += 1
                    except subprocess.TimeoutExpired:
                        log_warning(f"Timeout verifying volume {volume_name}, but restoration may have succeeded")
                        restored_count += 1
                    except subprocess.CalledProcessError as e:
                        log_error(f"Failed to verify volume {volume_name}: {e}")
                        failed_count += 1
                else:
                    log_warning(f"Volume backup {volume_name}.tar.gz not found in backup")
                    skipped_count += 1
            
            # Summary
            log_info(f"Volume restoration summary:")
            log_info(f"  - Restored: {restored_count}")
            log_info(f"  - Skipped: {skipped_count}")
            log_info(f"  - Failed: {failed_count}")
            
            if failed_count > 0:
                log_error(f"Failed to restore {failed_count} volume(s)")
                # Cleanup
                if restore_temp_dir.exists():
                    shutil.rmtree(restore_temp_dir)
                return False
            
            # Cleanup
            log_info("Cleaning up temporary extraction directory...")
            shutil.rmtree(restore_temp_dir)
            log_success(f"Volumes restored for {branch_name} ({restored_count} volume(s))")
            return True
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to restore volumes: {e}")
            if e.stdout:
                log_error(f"Command stdout: {e.stdout}")
            if e.stderr:
                log_error(f"Command stderr: {e.stderr}")
            # Cleanup
            if restore_temp_dir.exists():
                shutil.rmtree(restore_temp_dir)
            return False
        except Exception as e:
            log_error(f"Unexpected error during volume restoration: {e}")
            import traceback
            log_error(f"Traceback: {traceback.format_exc()}")
            # Cleanup
            if restore_temp_dir.exists():
                shutil.rmtree(restore_temp_dir)
            return False
    
    def run_compose_command(self, 
                          compose_file: Path, 
                          command: List[str], 
                          env_file: Optional[Path] = None,
                          project_name: Optional[str] = None,
                          working_dir: Optional[Path] = None,
                          extra_flags: Optional[List[str]] = None) -> bool:
        """Run a docker compose command.
        
        Args:
            compose_file: Path to the compose file
            command: Command to run (e.g., ["up", "-d"])
            env_file: Optional environment file
            project_name: Optional project name
            working_dir: Optional working directory
            extra_flags: Optional list of additional flags to append to the command
        """
        # Handle docker compose v2 vs v1 command format
        if self.compose_cmd == "docker compose":
            cmd = ["docker", "compose"]
        else:
            cmd = [self.compose_cmd]
        
        # Use working_dir if provided, otherwise fall back to project root
        if working_dir is None:
            working_dir = self.project_root
        
        # Convert to absolute path to ensure Docker resolves it correctly
        working_dir = working_dir.resolve() if isinstance(working_dir, Path) else Path(working_dir).resolve()

        # Explicitly load .env from the working directory first, if it exists
        main_env_file = working_dir / ".env"
        if main_env_file.exists():
            cmd.extend(["--env-file", str(main_env_file)])
        
        # Then, load the worktree-specific env.dockertree, which will override .env
        if env_file and env_file.exists():
            cmd.extend(["--env-file", str(env_file)])
        
        if project_name:
            cmd.extend(["-p", project_name])
        
        cmd.extend(["-f", str(compose_file)])
        cmd.extend(command)
        
        # Add any extra flags at the end
        if extra_flags:
            cmd.extend(extra_flags)
        
        # Set environment variables for build context
        import os
        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(working_dir)  # Absolute path to worktree or project root
        env["COMPOSE_PROJECT_ROOT"] = str(working_dir)
        env["PWD"] = str(working_dir)
        # Set COMPOSE_PROJECT_NAME to ensure Docker Compose uses correct project name for volumes
        if project_name:
            env["COMPOSE_PROJECT_NAME"] = project_name
        
        # Debug logging for path resolution
        log_info(f"Docker Compose execution context:")
        log_info(f"  Working directory: {working_dir}")
        log_info(f"  PROJECT_ROOT: {env['PROJECT_ROOT']}")
        log_info(f"  Compose file: {compose_file}")
        log_info(f"  Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=working_dir, env=env)
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"Docker compose command failed: {e}")
            if e.stdout:
                log_error(f"STDOUT: {e.stdout}")
            if e.stderr:
                log_error(f"STDERR: {e.stderr}")
            return False

    def run_compose_command_with_profile(self, compose_file: Path, compose_override: Path,
                                       command: List[str], env_file: Optional[Path] = None,
                                       project_name: Optional[str] = None,
                                       working_dir: Optional[Path] = None) -> bool:
        """Run a docker compose command with override file and dockertree profile."""
        # Handle docker compose v2 vs v1 command format
        if self.compose_cmd == "docker compose":
            cmd = ["docker", "compose"]
        else:
            cmd = [self.compose_cmd]

        if env_file and env_file.exists():
            cmd.extend(["--env-file", str(env_file)])

        if project_name:
            cmd.extend(["-p", project_name])

        # Add main compose file and override file with dockertree profile
        cmd.extend(["-f", str(compose_file)])
        cmd.extend(["-f", str(compose_override)])
        cmd.extend(["--profile", "dockertree"])
        cmd.extend(command)

        # Set working directory - use worktree_path if provided, otherwise project root
        if working_dir is None:
            # For worktree operations, use the worktree directory as working directory
            # This ensures environment files and relative paths work correctly
            working_dir = self.project_root

        # Convert to absolute path to ensure Docker resolves it correctly
        working_dir = working_dir.resolve() if isinstance(working_dir, Path) else Path(working_dir).resolve()

        # Set environment variables for build context
        import os
        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(working_dir)  # Absolute path to worktree or project root
        env["COMPOSE_PROJECT_ROOT"] = str(working_dir)
        env["PWD"] = str(working_dir)

        # Debug logging for path resolution
        log_info(f"Docker Compose execution context (with profile):")
        log_info(f"  Working directory: {working_dir}")
        log_info(f"  PROJECT_ROOT: {env['PROJECT_ROOT']}")
        log_info(f"  Compose file: {compose_file}")
        log_info(f"  Override file: {compose_override}")
        log_info(f"  Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=working_dir, env=env)
            return True
        except subprocess.CalledProcessError as e:
            log_error(f"Docker compose command with override failed: {e}")
            log_error(f"Command executed: {' '.join(cmd)}")
            log_error(f"Working directory: {working_dir}")
            if e.stdout:
                log_error(f"STDOUT: {e.stdout}")
            if e.stderr:
                log_error(f"STDERR: {e.stderr}")
            return False

    def start_services(self, compose_file: Path, env_file: Optional[Path] = None,
                      project_name: Optional[str] = None, working_dir: Optional[Path] = None) -> bool:
        """Start services using docker compose."""
        return self.run_compose_command(compose_file, ["up", "-d"], env_file, project_name, working_dir)

    def start_services_with_override(self, compose_file: Path, compose_override: Path,
                                   env_file: Optional[Path] = None, project_name: Optional[str] = None,
                                   working_dir: Optional[Path] = None) -> bool:
        """Start services using docker compose with override file and dockertree profile."""
        return self.run_compose_command_with_profile(compose_file, compose_override, ["up", "-d"],
                                                   env_file, project_name, working_dir)
    
    def stop_services(self, compose_file: Path, env_file: Optional[Path] = None,
                     project_name: Optional[str] = None, working_dir: Optional[Path] = None) -> bool:
        """Stop services using docker compose."""
        return self.run_compose_command(compose_file, ["down"], env_file, project_name, working_dir)
    
    def get_volume_sizes(self) -> Dict[str, str]:
        """Get sizes of all worktree volumes."""
        sizes = {}
        try:
            result = subprocess.run([
                "docker", "volume", "ls", "-q"
            ], capture_output=True, text=True, check=True)
            
            volumes = result.stdout.strip().split('\n')
            for volume in volumes:
                if volume and any(suffix in volume for suffix in ["_postgres_data", "_redis_data", "_media_files"]):
                    try:
                        size_result = subprocess.run([
                            "docker", "run", "--rm", "-v", f"{volume}:/data",
                            "alpine", "du", "-sh", "/data"
                        ], capture_output=True, text=True, check=True)
                        size = size_result.stdout.split()[0]
                        sizes[volume] = size
                    except subprocess.CalledProcessError:
                        sizes[volume] = "unknown"
            
        except subprocess.CalledProcessError:
            pass
        
        return sizes
    
    def list_volumes(self) -> List[str]:
        """List all worktree volumes."""
        volumes = []
        try:
            result = subprocess.run([
                "docker", "volume", "ls", "-q"
            ], capture_output=True, text=True, check=True)
            
            for volume in result.stdout.strip().split('\n'):
                if volume and any(suffix in volume for suffix in ["_postgres_data", "_redis_data", "_media_files"]):
                    volumes.append(volume)
                    
        except subprocess.CalledProcessError:
            pass
        
        return volumes
    
    def run_compose_passthrough(self, branch_name: str, compose_args: List[str]) -> bool:
        """Run docker compose command with automatic override file resolution.
        
        Args:
            branch_name: Name of the worktree/branch
            compose_args: Docker compose arguments to pass through
            
        Returns:
            True if command succeeded, False otherwise
        """
        from ..core.git_manager import GitManager
        from ..utils.path_utils import get_compose_override_path, get_env_compose_file_path
        from ..config.settings import get_project_name, sanitize_project_name
        
        # Validate worktree exists
        git_manager = GitManager()
        if not git_manager.validate_worktree_exists(branch_name):
            log_error(f"Worktree for branch '{branch_name}' does not exist")
            return False
        
        # Get worktree path
        worktree_path = git_manager.find_worktree_path(branch_name)
        if not worktree_path:
            log_error(f"Could not find worktree directory for branch '{branch_name}'")
            return False
        
        # Get compose override file
        compose_override_path = get_compose_override_path(worktree_path)
        if not compose_override_path or not compose_override_path.exists():
            log_error(f"Compose override file not found for worktree '{branch_name}'")
            return False
        
        # Get environment file
        env_file = get_env_compose_file_path(worktree_path)
        if not env_file.exists():
            log_error(f"Environment file not found: {env_file}")
            return False
        
        # Get project name
        project_name = sanitize_project_name(get_project_name())
        compose_project_name = f"{project_name}-{branch_name}"
        
        # Build docker compose command
        if self.compose_cmd == "docker compose":
            cmd = ["docker", "compose"]
        else:
            cmd = [self.compose_cmd]
        
        # Add environment file
        cmd.extend(["--env-file", str(env_file)])
        
        # Add project name
        cmd.extend(["-p", compose_project_name])
        
        # Add compose override file
        cmd.extend(["-f", str(compose_override_path)])
        
        # Add the passthrough arguments
        cmd.extend(compose_args)
        
        # Set environment variables
        import os
        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(worktree_path)
        env["COMPOSE_PROJECT_ROOT"] = str(worktree_path)
        env["PWD"] = str(worktree_path)
        
        log_info(f"Running docker compose command for worktree '{branch_name}':")
        log_info(f"  Working directory: {worktree_path}")
        log_info(f"  Compose file: {compose_override_path}")
        log_info(f"  Environment file: {env_file}")
        log_info(f"  Project name: {compose_project_name}")
        log_info(f"  Command: {' '.join(cmd)}")
        
        try:
            # Run command and stream output to user
            result = subprocess.run(cmd, cwd=worktree_path, env=env)
            return result.returncode == 0
        except Exception as e:
            log_error(f"Failed to run docker compose command: {e}")
            return False

    async def start_worktree_containers(self, branch_name: str, worktree_path: Path, 
                                       project_root: Path) -> Dict[str, Any]:
        """Start containers for a worktree asynchronously."""
        try:
            from ..utils.path_utils import get_compose_override_path, get_env_compose_file_path
            from ..config.settings import get_project_name, sanitize_project_name
            
            # Get compose files
            compose_override = get_compose_override_path(worktree_path)
            env_file = get_env_compose_file_path(worktree_path)
            
            if not compose_override or not compose_override.exists():
                return {"success": False, "error": f"Compose file not found for worktree '{branch_name}'"}
            
            # Get project name
            project_name = sanitize_project_name(get_project_name())
            compose_project_name = f"{project_name}-{branch_name}"
            
            # Start services
            success = self.run_compose_command(
                compose_override, 
                ["up", "-d"], 
                env_file=env_file,
                project_name=compose_project_name,
                working_dir=worktree_path
            )
            
            return {
                "success": success,
                "message": f"Started containers for worktree '{branch_name}'" if success else "Failed to start containers"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def stop_worktree_containers(self, branch_name: str) -> Dict[str, Any]:
        """Stop containers for a worktree asynchronously."""
        try:
            from ..core.git_manager import GitManager
            from ..utils.path_utils import get_compose_override_path, get_env_compose_file_path
            from ..config.settings import get_project_name, sanitize_project_name
            
            # Find worktree path
            git_manager = GitManager(validate=False)
            worktree_path = git_manager.find_worktree_path(branch_name)
            
            if not worktree_path:
                return {"success": False, "error": f"Worktree for branch '{branch_name}' not found"}
            
            # Get compose files
            compose_override = get_compose_override_path(worktree_path)
            env_file = get_env_compose_file_path(worktree_path)
            
            # Get project name
            project_name = sanitize_project_name(get_project_name())
            compose_project_name = f"{project_name}-{branch_name}"
            
            # Stop services
            success = self.stop_services(
                compose_override,
                env_file=env_file,
                project_name=compose_project_name,
                working_dir=worktree_path
            )
            
            return {
                "success": success,
                "message": f"Stopped containers for worktree '{branch_name}'" if success else "Failed to stop containers"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_worktree_containers(self, branch_name: str) -> List[Dict[str, Any]]:
        """Get container status for a worktree asynchronously."""
        try:
            from ..config.settings import get_project_name, sanitize_project_name
            
            project_name = sanitize_project_name(get_project_name())
            compose_project_name = f"{project_name}-{branch_name}"
            
            # Get containers for this project
            result = subprocess.run([
                "docker", "ps", "-a", 
                "--filter", f"label=com.docker.compose.project={compose_project_name}",
                "--format", "{{.Names}}|{{.Status}}|{{.Ports}}|{{.Image}}"
            ], capture_output=True, text=True, check=False)
            
            # If Docker is not running, return empty list
            if result.returncode != 0:
                return []
            
            containers = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    if len(parts) >= 4:
                        containers.append({
                            "name": parts[0],
                            "status": parts[1],
                            "state": "running" if "Up" in parts[1] else "stopped",
                            "ports": parts[2],
                            "image": parts[3]
                        })
            
            return containers
        except Exception as e:
            log_warning(f"Failed to get containers: {e}")
            return []

    async def get_worktree_volumes(self, branch_name: str) -> List[Dict[str, Any]]:
        """Get volumes for a worktree asynchronously."""
        try:
            from ..config.settings import get_volume_names
            from ..utils.validation import validate_volume_exists
            
            volume_names = get_volume_names(branch_name)
            volumes = []
            
            for volume_type, volume_name in volume_names.items():
                if validate_volume_exists(volume_name):
                    volumes.append({
                        "name": volume_name,
                        "type": volume_type,
                        "branch": branch_name,
                        "exists": True
                    })
            
            return volumes
        except Exception as e:
            log_warning(f"Failed to get volumes: {e}")
            return []

    async def clean_worktree_volumes(self, branch_name: str) -> Dict[str, Any]:
        """Clean up volumes for a worktree asynchronously."""
        try:
            success = self.remove_volumes(branch_name)
            return {
                "success": success,
                "message": f"Cleaned volumes for worktree '{branch_name}'" if success else "Failed to clean volumes"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}